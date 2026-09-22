"""Put the ground under standard Payroll straight, before any salary rule is
written on top of it.

    # report only, writes nothing:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/setup_native_payroll.py

    # same again, this time writing:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http 2>/dev/null < tools/setup_native_payroll.py

Five things are wrong or missing on the database today, and every one of them
would quietly corrupt a payslip rather than fail:

  1. the main company's default working schedule holds NO working day at all,
     so a contract that inherits it is paid `hours x wage / 0`;
  2. there is not one public holiday on any calendar, while the whole off-day
     overtime and holiday rules read them off the calendar;
  3. half the fleet computes from the working schedule and half from
     attendances, so the same company pays two different ways;
  4. overtime needs a manager's approval in one company and none in the other
     three, on the same kind of work;
  5. the labour schedule that IS correct - six days, Friday off - is not the
     one every contract points at.

Nothing here invents data. The holidays are copied from `ssc.public.holiday`,
which is the list the business already maintains; the target schedule is the
existing "Standard 48 hours/week"; the overtime settings are the ones the main
company already chose. It is idempotent: run it twice and the second run
reports nothing left to do.

What it deliberately does NOT do, because it needs code rather than data: the
two overtime work entry types, the two overtime rate fields on the contract,
the SSC salary structure and its rules, and the leave-salary-on-approval hook.
Those come with the module.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

import pytz

from odoo import fields as odoo_fields

APPLY = os.environ.get('SSC_APPLY') == '1'

# The schedule the labour force actually works: six days, Friday off. Staff and
# engineers were confirmed to work the same one.
TARGET_CALENDAR = os.environ.get('SSC_CALENDAR') or 'Standard 48 hours/week'
FRIDAY = '4'

# The four companies were confirmed to run the same rules: Friday off, six days
# worked, attendance-driven. The punches agree - Friday holds 1-14% of an
# ordinary day everywhere it is recorded. So every version moves onto the one
# schedule. SSC_MOVE=broken narrows it back to repairing the schedules that
# hold no working day at all, for when only that is wanted.
MOVE_ALL = (os.environ.get('SSC_MOVE') or 'all') != 'broken'

# Whether overtime needs a manager's approval is a policy, not a repair, so it
# is left exactly as each company has it unless somebody asks for a change:
#   SSC_OT_VALIDATION=by_manager   (or no_validation)
# The tolerance is different - the companies plainly meant the same thing and
# only three of them were ever configured, so that one is aligned.
OVERTIME_VALIDATION = os.environ.get('SSC_OT_VALIDATION') or None
OVERTIME_THRESHOLD = float(os.environ.get('SSC_OT_TOLERANCE') or 15)

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 88
todo = []


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def plan(line):
    """Something this run would change. Printed again at the end."""
    todo.append(line)
    print(f"  -> {line}")


contract_model = 'hr.version' if 'hr.version' in env else 'hr.contract'
Contract = env[contract_model].sudo()
Company = env['res.company'].sudo()
Calendar = env['resource.calendar'].sudo()

# --- 0. scope ----------------------------------------------------------------

title("0. scope")

companies = Company.search([])
in_scope = companies.filtered(
    lambda c: Contract.search_count([('company_id', '=', c.id)]))
print(f"  {len(companies)} company(ies), {len(in_scope)} with contracts:")
for company in in_scope:
    print(f"    {company.name[:44]:<44} "
          f"{Contract.search_count([('company_id', '=', company.id)]):>5} version(s)")

target = Calendar.search([('name', '=', TARGET_CALENDAR)], limit=1)
if not target:
    print(f"\n  !! no calendar named {TARGET_CALENDAR!r} - nothing can be done")
else:
    worked = defaultdict(float)
    for line in target.attendance_ids:
        if 'day_period' in line._fields and line.day_period == 'lunch':
            continue
        worked[line.dayofweek] += line.hour_to - line.hour_from
    print(f"\n  target schedule: {target.name} (id {target.id}), tz {target.tz}, "
          f"{target.hours_per_day} h/day")
    print(f"    working days: {sorted(worked)}   Friday off: "
          f"{'yes' if FRIDAY not in worked else 'NO - CHECK THIS'}")
    if FRIDAY in worked:
        print("    !! the target schedule works Friday; off-day overtime would be wrong")

# --- 1. the empty schedules --------------------------------------------------

title("1. schedules with no working day")

broken = Calendar.browse()
for calendar in Calendar.search([]):
    lines = [line for line in calendar.attendance_ids
             if not ('day_period' in line._fields and line.day_period == 'lunch')]
    if not lines:
        broken |= calendar
        users = Contract.search_count([('resource_calendar_id', '=', calendar.id)])
        default_for = Company.search_count([('resource_calendar_id', '=', calendar.id)])
        print(f"  {calendar.name[:40]:<40} company={calendar.company_id.name or '-'}")
        print(f"      {users} version(s) point at it, "
              f"default for {default_for} company(ies)")
if not broken:
    print("  none - every schedule holds at least one working day")

# --- 1b. which day is actually the weekly off day ----------------------------

title("1b. the weekly off day, read off the attendances")

# The configured value is no evidence: ssc_weekly_off_day defaults to Friday, so
# a company nobody ever configured also reads Friday. The punches are evidence.
LOOKBACK_DAYS = int(os.environ.get('SSC_LOOKBACK') or 180)
DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
tz_name = (target.tz if target else None) or 'UTC'

by_company_day = defaultdict(lambda: defaultdict(int))
if 'hr.attendance' in env:
    env.cr.execute(
        """
        SELECT e.company_id,
               EXTRACT(DOW FROM (a.check_in AT TIME ZONE 'UTC' AT TIME ZONE %s))::int,
               COUNT(*)
          FROM hr_attendance a
          JOIN hr_employee e ON e.id = a.employee_id
         WHERE a.check_in > (now() - (%s || ' days')::interval)
      GROUP BY 1, 2
        """, (tz_name, str(LOOKBACK_DAYS)))
    for company_id, postgres_dow, count in env.cr.fetchall():
        # Postgres counts Sunday as 0; Odoo counts Monday as 0.
        by_company_day[company_id][(postgres_dow + 6) % 7] += count

print(f"  punches over the last {LOOKBACK_DAYS} day(s), {tz_name}\n")
for company in in_scope:
    days = by_company_day.get(company.id) or {}
    if not days:
        print(f"  {company.name[:40]:<40} NO ATTENDANCE AT ALL")
        continue
    # Over all seven days, not only the ones that have punches: a day with none
    # at all is the clearest off day there is, and it carries no key here.
    per_day = {day: days.get(day, 0) for day in range(7)}
    busiest = max(per_day.values())
    quietest_day = min(per_day, key=lambda d: per_day[d])
    counts = "  ".join(f"{DAY_NAMES[d]} {per_day[d]:>5}" for d in range(7))
    print(f"  {company.name[:40]:<40} {counts}")
    verdict = (f"off day looks like {DAY_NAMES[quietest_day]}"
               if per_day[quietest_day] < busiest * 0.25 else
               "NO clear off day - every day is worked")
    print(f"  {'':<40} -> {verdict}")

# --- 2. point everything at the target schedule ------------------------------

title("2. schedules in use")

if target:
    by_calendar = defaultdict(int)
    for version in Contract.search([('company_id', 'in', in_scope.ids)]):
        by_calendar[version.resource_calendar_id.id or 0] += 1
    for calendar_id, count in sorted(by_calendar.items(), key=lambda kv: -kv[1]):
        calendar = Calendar.browse(calendar_id) if calendar_id else None
        mark = '  <- target' if calendar_id == target.id else ''
        print(f"  {(calendar.name if calendar else '(none)')[:44]:<44} "
              f"{count:>5} version(s){mark}")

    # Two very different moves hide behind "not on the target schedule".
    # Leaving a schedule that holds no working day is a repair: those versions
    # are paid `hours x wage / 0` today, and any schedule is better. Leaving a
    # VALID schedule is a business change - the other companies work Monday to
    # Friday, and putting them on six days with Friday off moves the hours
    # their pay is measured against. Only the repair runs by default.
    move_now = Contract.search([
        ('company_id', 'in', in_scope.ids),
        ('resource_calendar_id', 'in', broken.ids),
    ]) if broken else Contract.browse()
    held = Contract.search([
        ('company_id', 'in', in_scope.ids),
        ('resource_calendar_id', '!=', target.id),
        ('resource_calendar_id', 'not in', broken.ids),
    ])
    if MOVE_ALL:
        move_now |= held
        held = Contract.browse()

    if move_now:
        plan(f"repoint {len(move_now)} version(s) to {target.name}")
    if held:
        print(f"\n  HELD: {len(held)} version(s) sit on a VALID schedule that is not "
              f"the target:")
        per_calendar = defaultdict(int)
        for version in held:
            per_calendar[version.resource_calendar_id] += 1
        for calendar, count in per_calendar.items():
            days = sorted({line.dayofweek for line in calendar.attendance_ids})
            print(f"    {calendar.name[:26]:<26} "
                  f"{(calendar.company_id.name or '-')[:30]:<30} "
                  f"{count:>4} version(s)  works {days}")
        print("    Moving them changes the hours their pay is measured against.")
        print("    Re-run with SSC_MOVE=all once that is a decision, not an accident.")

    default_now = in_scope.filtered(lambda c: c.resource_calendar_id != target) \
        if MOVE_ALL else Company.browse()
    if default_now:
        plan(f"set {target.name} as the default schedule of "
             f"{len(default_now)} company(ies): "
             f"{', '.join(c.name[:20] for c in default_now)}")
    elif not MOVE_ALL:
        off_default = in_scope.filtered(lambda c: c.resource_calendar_id != target)
        if off_default:
            print(f"  HELD: {len(off_default)} company default schedule(s), same reason")

# --- 3. public holidays ------------------------------------------------------

title("3. public holidays")

Leaves = env['resource.calendar.leaves'].sudo()
existing = Leaves.search([('resource_id', '=', False)])
print(f"  {len(existing)} global calendar leave(s) today")

holiday_type = env['hr.work.entry.type'].sudo().search(
    [('code', '=', 'AEPUBLICH')], limit=1) if 'hr.work.entry.type' in env else None
print(f"  work entry type AEPUBLICH: {'found' if holiday_type else 'MISSING'}")

holidays = env['ssc.public.holiday'].sudo().search([], order='date') \
    if 'ssc.public.holiday' in env else None
if holidays is None:
    print("  ssc.public.holiday is not on this database - nothing to copy from")
    holidays = []
else:
    print(f"  {len(holidays)} holiday(s) on ssc.public.holiday")
    per_company = defaultdict(int)
    for holiday in holidays:
        per_company[holiday.company_id.name or '(all companies)'] += 1
    for name, count in sorted(per_company.items()):
        print(f"    {name[:44]:<44} {count:>4}")

new_holidays = []
if target and holidays:
    timezone = pytz.timezone(target.tz or 'UTC')
    for holiday in holidays:
        if holiday.company_id:
            # The target schedule is shared by every company, so a holiday that
            # applies to only one of them cannot be hung off it. Reported, not
            # guessed at.
            continue
        start = timezone.localize(
            odoo_fields.Datetime.to_datetime(str(holiday.date) + ' 00:00:00')
        ).astimezone(pytz.utc).replace(tzinfo=None)
        end = timezone.localize(
            odoo_fields.Datetime.to_datetime(str(holiday.date) + ' 23:59:59')
        ).astimezone(pytz.utc).replace(tzinfo=None)
        if Leaves.search_count([
                ('calendar_id', '=', target.id),
                ('resource_id', '=', False),
                ('date_from', '<=', end),
                ('date_to', '>=', start)]):
            continue
        vals = {
            'name': holiday.name,
            'calendar_id': target.id,
            'date_from': start,
            'date_to': end,
            'resource_id': False,
        }
        if holiday_type and 'work_entry_type_id' in Leaves._fields:
            vals['work_entry_type_id'] = holiday_type.id
        if 'time_type' in Leaves._fields:
            vals['time_type'] = 'leave'
        # Reported by its own date, not by date_from: stored UTC is four hours
        # behind Dubai, so a 1 January holiday would print as 31 December and
        # read as an off-by-one to whoever approves this run.
        new_holidays.append((holiday.date, vals))

    company_specific = [h for h in holidays if h.company_id]
    if company_specific:
        print(f"\n  {len(company_specific)} holiday(s) belong to ONE company and are "
              f"skipped:")
        for holiday in company_specific[:10]:
            print(f"    {holiday.date}  {holiday.name[:40]:<40} {holiday.company_id.name}")
        print("    (a shared schedule cannot carry a per-company holiday - decide first)")

if new_holidays:
    plan(f"create {len(new_holidays)} public holiday(s) on {target.name}")
    for day, vals in new_holidays[:12]:
        print(f"       {day}  {vals['name']}")
    if len(new_holidays) > 12:
        print(f"       ... and {len(new_holidays) - 12} more")

# --- 4. one way of counting the work ----------------------------------------

title("4. work entry source")

source_now = Contract.browse()
if 'work_entry_source' not in Contract._fields:
    print(f"  {contract_model} has no work_entry_source in this version")
else:
    counts = defaultdict(int)
    for version in Contract.search([('company_id', 'in', in_scope.ids)]):
        counts[version.work_entry_source] += 1
    for value, count in sorted(counts.items()):
        print(f"  {str(value):<16} {count:>5} version(s)")

    punching = set()
    if 'hr.attendance' in env:
        env.cr.execute(
            "SELECT DISTINCT employee_id FROM hr_attendance "
            "WHERE employee_id IS NOT NULL")
        punching = {row[0] for row in env.cr.fetchall()}

    source_now = Contract.search([
        ('company_id', 'in', in_scope.ids),
        ('work_entry_source', '!=', 'attendance'),
    ])
    if source_now:
        plan(f"set work_entry_source=attendance on {len(source_now)} version(s)")

    # Every company runs the same rules, so every version goes onto attendance -
    # but an attendance-based contract belonging to somebody who never punches
    # is paid for ZERO hours. It does not fail; it quietly pays nothing. Whoever
    # approves this run has to see that list, because those payslips will look
    # finished and be wrong.
    silent = Contract.search([('company_id', 'in', in_scope.ids)]).filtered(
        lambda v: v.employee_id and v.employee_id.id not in punching)
    if silent:
        print(f"\n  !! WARNING: {len(silent)} version(s) belong to employees with NO "
              f"attendance at all")
        per_company = defaultdict(set)
        for version in silent:
            per_company[version.company_id.name or '-'].add(version.employee_id.id)
        for name, employees in sorted(per_company.items(),
                                      key=lambda kv: -len(kv[1])):
            print(f"     {name[:44]:<44} {len(employees):>4} employee(s)")
        print("     On 'attendance' they compute to zero until punches arrive.")
        print("     Do not validate their payslips before then - "
              "tools/check_payslip_hours.py names them.")

# --- 5. overtime settings ----------------------------------------------------

title("5. overtime settings")

fields_to_align = {
    'overtime_company_threshold': OVERTIME_THRESHOLD,
    'overtime_employee_threshold': OVERTIME_THRESHOLD,
}
if OVERTIME_VALIDATION:
    fields_to_align['attendance_overtime_validation'] = OVERTIME_VALIDATION
else:
    print("  approval mode left as each company has it "
          "(SSC_OT_VALIDATION=by_manager would change it)")
present = {name: value for name, value in fields_to_align.items()
           if name in Company._fields}
if not present:
    print("  this database has no overtime settings on res.company")
else:
    for company in in_scope:
        current = {name: company[name] for name in present}
        drift = {name: value for name, value in present.items()
                 if company[name] != value}
        print(f"  {company.name[:40]:<40} "
              f"{'  '.join(f'{k}={v}' for k, v in current.items())}")
        if drift:
            plan(f"align {company.name[:28]}: "
                 f"{', '.join(f'{k} -> {v}' for k, v in drift.items())}")

# --- 6. reported only, never changed automatically ---------------------------

title("6. needs a human decision (reported, not changed)")

if 'hr.leave.type' not in env:
    print("  hr_holidays is not installed - no leave types to look at")
else:
    LeaveType = env['hr.leave.type'].sudo()
    annual = LeaveType.search([('name', 'ilike', 'annual')])
    print(f"  {len(annual)} leave type(s) named like 'Annual':")
    for leave_type in annual:
        work_entry = leave_type.work_entry_type_id if 'work_entry_type_id' \
            in leave_type._fields else None
        print(f"    {leave_type.name[:30]:<30} "
              f"work entry={work_entry.code if work_entry else '-':<10} "
              f"allocation={leave_type.requires_allocation}  "
              f"company={leave_type.company_id.name or 'all'}")
    if len(annual) > 1:
        print("    -> duplicates: keep one, so a request cannot be filed against "
              "the wrong one")
    print("    -> Unpaid is CORRECT here: leave salary is paid separately, so the "
          "days must not be paid twice")

print("\n  still to come with the module, not doable as data:")
for line in ("work entry types SSC_OT_REG / SSC_OT_OFF",
             "overtime rate fields on the contract, filled from ssc.employee",
             "the SSC salary structure and its day-based rules",
             "leave salary computed on hr.leave approval, paid on its own payslip"):
    print(f"    . {line}")

# --- apply -------------------------------------------------------------------

title("summary")

if not todo:
    print("  nothing to change - the ground is already straight")
else:
    for line in todo:
        print(f"  . {line}")

if not APPLY:
    env.cr.rollback()
    print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write.")
else:
    written = []
    if target:
        # Exactly the recordsets the report named - so what was approved on
        # screen is what gets written, with no second search to drift from it.
        if move_now:
            move_now.write({'resource_calendar_id': target.id})
            written.append(f"{len(move_now)} version(s) repointed")
        if default_now:
            default_now.write({'resource_calendar_id': target.id})
            written.append(f"{len(default_now)} company default(s) set")
    if new_holidays:
        Leaves.create([vals for _day, vals in new_holidays])
        written.append(f"{len(new_holidays)} public holiday(s) created")
    if source_now:
        source_now.write({'work_entry_source': 'attendance'})
        written.append(f"{len(source_now)} version(s) set to attendance")
    if present:
        for company in in_scope:
            drift = {name: value for name, value in present.items()
                     if company[name] != value}
            if drift:
                company.write(drift)
                written.append(f"{company.name[:24]} overtime aligned")

    env.cr.commit()
    print("\nwritten:")
    for line in written:
        print(f"  . {line}")
    print("\nWork entries for open periods are now stale - regenerate them before "
          "trusting a payslip.")
