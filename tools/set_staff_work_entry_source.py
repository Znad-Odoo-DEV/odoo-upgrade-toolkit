"""Pay office staff a month, and site labour the hours they punched.

    cd ~/src/user

    # report only, writes nothing - read this first:
    odoo-bin shell -d <database> --no-http < tools/set_staff_work_entry_source.py

    # one company at a time:
    SSC_COMPANY="ROYAL ARROW" SSC_APPLY=1 odoo-bin shell ...

    # everything, once the first has been checked on a payslip:
    SSC_APPLY=1 odoo-bin shell ...

Why this exists
---------------
The UAE localisation pays two entirely different ways, and the switch between
them is one field on the contract - `work_entry_source`:

    calendar     BASIC = the wage, whole. Allowances are their monthly amounts,
                 whole. A paid leave is inside that month already, so AEPAID
                 does not fire (its condition is work_entry_source != calendar)
                 and nothing is paid twice. Unpaid leave is deducted by
                 AEUNPAID, and sick leave at 50% and 0% by SL50 and SL0 -
                 all three of which ONLY run in this mode.

    attendance   BASIC = hours worked x (wage / hours in the period), and each
                 allowance likewise. Nothing worked, nothing paid - so a day of
                 leave pays nothing until AEPAID pays it from the LEAVE120
                 hours. Unpaid leave needs no rule: no hours, no money.

Office staff never touch the biometric device. On the attendance source their
punch count is zero, so their basic and every allowance compute to zero and
they are paid the leave rule alone. They belong on `calendar`: a month is a
month, and their annual leave rides inside it at the full gross - which is what
the business asked for.

Site labour stays on `attendance`, where the hours actually decide the money.

Who is staff is read from the structure type the contract already carries -
`<company> Staff` - which this database set when the labour and staff
structures were split. Nothing here consults a custom model.

What it checks before writing
  * a contract on `calendar` with no working schedule pays nothing and blocks
    work entry generation, so one without a calendar is named and skipped;
  * the schedule each staff contract carries, because in this mode the schedule
    is what says how long a month is - and AEUNPAID divides by it.

In the interface
----------------
  * the field           Employees > the employee > Work Information >
                        Work Entry Source
  * the schedule        the same tab, Working Schedule

Nothing here inherits, patches or extends a native model.

Reads only unless SSC_APPLY=1.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'
ONLY_COMPANY = (os.environ.get('SSC_COMPANY') or '').strip().lower()
STAFF_SUFFIX = os.environ.get('SSC_STAFF_SUFFIX') or 'Staff'

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def short(text, size=40):
    text = text or '-'
    return text if len(text) <= size else text[:size - 1] + '.'


Version = env['hr.version'].sudo() if 'hr.version' in env else None
WorkEntry = env['hr.work.entry'].sudo() if 'hr.work.entry' in env else None
Company = env['res.company'].sudo()

if Version is None or 'work_entry_source' not in Version._fields:
    title("nothing to do")
    print("  this database has no work entry source on the contract.")
else:
    sources = dict(Version._fields['work_entry_source'].selection or [])
    if 'calendar' not in sources:
        title("nothing to do")
        print(f"  the only sources here are {list(sources)} - no Working Schedule.")
    else:
        # ------------------------------------------------------------------
        title("1. where the contracts stand")

        companies = Company.search([])
        if ONLY_COMPANY:
            companies = companies.filtered(
                lambda c: ONLY_COMPANY in (c.name or '').lower())
            print(f"  restricted to companies matching {ONLY_COMPANY!r}\n")

        plan = []
        for company in companies:
            versions = Version.search([('company_id', '=', company.id)])
            if not versions:
                continue
            staff = versions.filtered(
                lambda v, s=STAFF_SUFFIX: (v.structure_type_id.name or '').endswith(s))
            labour = versions - staff
            def spread(records):
                """How many of them sit on each source."""
                return ', '.join(
                    f"{src}={len(records.filtered(lambda v, s=src: v.work_entry_source == s))}"
                    for src in sources)

            print(f"\n  {company.name}")
            print(f"      staff  {len(staff):>4} contract version(s)   {spread(staff)}")
            print(f"      labour {len(labour):>4} contract version(s)   {spread(labour)}")
            plan.append({'company': company, 'staff': staff, 'labour': labour})

        if not plan:
            print("  no company has a contract - nothing to do.")

        # ------------------------------------------------------------------
        title("2. can they be paid on the schedule?")

        blocked = Version.browse()
        for entry in plan:
            for version in entry['staff']:
                if not version.resource_calendar_id:
                    blocked |= version
        for entry in plan:
            calendars = {}
            for version in entry['staff']:
                name = version.resource_calendar_id.name or '(none)'
                calendars[name] = calendars.get(name, 0) + 1
            if not calendars:
                continue
            print(f"\n  {short(entry['company'].name, 44)}")
            for name, count in sorted(calendars.items(), key=lambda kv: -kv[1]):
                print(f"      {short(name, 40):<40} {count:>4} staff contract(s)")
        if blocked:
            print(f"\n  !! {len(blocked)} staff contract(s) carry NO working schedule.")
            print("     On the schedule source they would generate no work entries and")
            print("     pay nothing, so they are skipped until one is set:")
            for version in blocked[:10]:
                print(f"       {short(version.employee_id.name, 34)}")
        print("\n  In this mode the schedule decides how long a month is, and AEUNPAID")
        print("  divides by it. A six-day site schedule on an office contract is not")
        print("  wrong for the salary - the wage is paid whole either way - but it is")
        print("  what an unpaid day and a leave duration are measured against.")

        # ------------------------------------------------------------------
        title("3. the work entries already on record")

        if WorkEntry is None:
            print("  no work entry model.")
        else:
            for entry in plan:
                if not entry['staff']:
                    continue
                count = WorkEntry.search_count(
                    [('employee_id', 'in', entry['staff'].employee_id.ids)])
                print(f"  {short(entry['company'].name, 44):<44} {count:>7} entry/entries "
                      f"for staff employees")
            print("\n  Entries already generated from punches keep their dates. Odoo")
            print("  regenerates from the schedule going forward; use Payroll > Work")
            print("  Entries > Regenerate for a period that has to be rebuilt.")

        # ------------------------------------------------------------------
        title("summary")

        moving = Version.browse()
        for entry in plan:
            batch = (entry['staff'] - blocked).filtered(
                lambda v: v.work_entry_source != 'calendar')
            moving |= batch
            wrong_labour = entry['labour'].filtered(
                lambda v: v.work_entry_source != 'attendance')
            bits = []
            if batch:
                bits.append(f"{len(batch)} staff -> calendar")
            if wrong_labour and 'attendance' in sources:
                bits.append(f"!! {len(wrong_labour)} labour not on attendance")
            print(f"  {short(entry['company'].name):<40} " + ("; ".join(bits) or "nothing to do"))

        if not APPLY:
            env.cr.rollback()
            print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write,")
            print("one company at a time with SSC_COMPANY=... while you watch it.")
        elif not moving:
            print("\nnothing to write.")
        else:
            moving.write({'work_entry_source': 'calendar'})
            env.cr.commit()
            print(f"\nwritten:\n  . {len(moving)} staff contract version(s) now paid on "
                  f"the working schedule")
            print("\nnext: make one payslip for a staff employee with a leave in the")
            print("period. BASIC must be the whole wage, each allowance its whole")
            print("monthly amount, and AEPAID absent - the leave is already inside the")
            print("month, and paying it again is the one thing this mode must not do.")
