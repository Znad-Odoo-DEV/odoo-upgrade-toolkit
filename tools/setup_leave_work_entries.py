"""Point each time off type at the work entry type the UAE payroll actually reads.

    cd ~/src/user

    # report only, writes nothing - read this first:
    odoo-bin shell -d <database> --no-http < tools/setup_leave_work_entries.py

    # write the mapping, and carry it onto the leaves already approved:
    SSC_APPLY=1 odoo-bin shell ...

Why this exists
---------------
A time off type carries a work entry type. An approved leave turns into work
entries of that type, the payslip groups them into its Worked Days lines, and
the salary rules read those lines by CODE. Get the code wrong and the rule
never fires - silently, because a rule whose condition is false simply does not
appear.

Two of those codes are wrong on this database, and both cost the employee money:

  * Annual Leave points at LEAVE90, "Unpaid", which the structure lists as an
    unpaid work entry type. Every annual leave is therefore deducted rather
    than paid - the exact opposite of what annual leave means.

  * Sick Leave 50% and Sick Leave 0% point at the generic SICKLEAVE50 and
    SICKLEAVE0, while the localisation's own rules read AESICKLEAVE50 and
    AESICKLEAVE0:

        SL50 condition:  version.work_entry_source == 'calendar'
                         and employee.active and 'AESICKLEAVE50' in worked_days

    So the sick leave rules can never fire, whatever an employee is granted.

And Unpaid leave points at nothing at all, so a day taken without pay costs
nothing.

What it sets

    Annual Leave      -> LEAVE120        Paid Time Off
    Unpaid leave      -> LEAVE90         Unpaid
    Sick Time Off     -> LEAVE110        Sick Time Off        (already right)
    Sick Leave 50%    -> AESICKLEAVE50   Sick Leave 50
    Sick Leave 0%     -> AESICKLEAVE0    Sick Leave 0

Only those five, matched by their exact name. Every other type on the database
- and there are seventy, one per localisation Odoo ships - is left alone.

The type lives on the TIME OFF TYPE, not on the leave. But an approved leave
has already stamped the old one onto its resource calendar leave, and onto any
work entry generated from it, so both are carried over as well - otherwise the
leaves on record keep paying by the old code while new ones pay by the new.

In the interface
----------------
  * the mapping         Time Off > Configuration > Time Off Types > Work Entry Type
  * a work entry        Payroll > Work Entries
  * the calendar leave  Employees > Configuration > Working Schedules > Time Off

Nothing here inherits, patches or extends a native model.

Reads only unless SSC_APPLY=1.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92

# time off type name -> the work entry type code the payroll rules read
WANTED = {
    'Annual Leave': 'LEAVE120',
    'Unpaid leave': 'LEAVE90',
    'Sick Time Off': 'LEAVE110',
    'Sick Leave 50%': 'AESICKLEAVE50',
    'Sick Leave 0%': 'AESICKLEAVE0',
}


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def short(text, size=30):
    text = text or '-'
    return text if len(text) <= size else text[:size - 1] + '.'


LeaveType = env['hr.leave.type'].sudo() if 'hr.leave.type' in env else None
WorkEntryType = env['hr.work.entry.type'].sudo() if 'hr.work.entry.type' in env else None
Leave = env['hr.leave'].sudo() if 'hr.leave' in env else None
Structure = env['hr.payroll.structure'].sudo() if 'hr.payroll.structure' in env else None

if LeaveType is None or WorkEntryType is None:
    title("nothing to do")
    print("  time off or work entries are not installed on this database.")
elif 'work_entry_type_id' not in LeaveType._fields:
    title("nothing to do")
    print("  hr_work_entry_holidays is not installed, so a time off type carries")
    print("  no work entry type and payroll cannot see leaves at all.")
else:
    # ------------------------------------------------------------------
    title("1. the types this database actually uses")

    plan = []
    for name, code in WANTED.items():
        kind = LeaveType.search([('name', '=ilike', name)], limit=1)
        target = WorkEntryType.search([('code', '=', code)], limit=1)
        taken = Leave.search_count([('holiday_status_id', '=', kind.id)]) if kind else 0
        if not kind:
            print(f"  {short(name, 18):<18} no such time off type - skipped")
            continue
        if not target:
            print(f"  {short(name, 18):<18} !! no work entry type with code {code!r}")
            continue
        current = kind.work_entry_type_id
        mark = 'already right' if current == target else \
            f"-> {target.code} {target.name}"
        print(f"  {short(name, 18):<18} {taken:>4} leave(s) | "
              f"now: {current.code or '(none)':<14} {mark}")
        plan.append({'type': kind, 'target': target, 'current': current})

    # ------------------------------------------------------------------
    title("2. the leaves already approved carry the old code")

    CalendarLeave = env['resource.calendar.leaves'].sudo()
    WorkEntry = env['hr.work.entry'].sudo() if 'hr.work.entry' in env else None
    for entry in plan:
        if entry['current'] == entry['target']:
            continue
        leaves = Leave.search([('holiday_status_id', '=', entry['type'].id)])
        # The stamp an approved leave left behind, on the calendar closure it
        # created and on every work entry generated from it.
        closures = CalendarLeave.search([('holiday_id', 'in', leaves.ids)]).filtered(
            lambda c, t=entry['target']: c.work_entry_type_id != t)
        entries = WorkEntry.search([('leave_id', 'in', leaves.ids)]) if WorkEntry else None
        entries = entries.filtered(
            lambda w, t=entry['target']: w.work_entry_type_id != t) if entries else None
        states = {}
        for work_entry in entries or []:
            states[work_entry.state] = states.get(work_entry.state, 0) + 1
        detail = ', '.join(f"{count} {state}" for state, count in sorted(states.items()))
        print(f"  {short(entry['type'].name, 18):<18} {len(leaves):>4} leave(s) | "
              f"{len(closures):>4} calendar closure(s) | "
              f"{len(entries or []):>5} work entry/entries"
              + (f"  ({detail})" if detail else ""))
        entry['closures'] = closures
        entry['entries'] = entries
    if not any(e.get('closures') or e.get('entries') for e in plan):
        print("  none - nothing on record carries the old code.")

    # ------------------------------------------------------------------
    title("3. what each structure treats as unpaid")

    if Structure is None or 'unpaid_work_entry_type_ids' not in Structure._fields:
        print("  no unpaid list on this Odoo.")
    else:
        for structure in Structure.search([]):
            codes = structure.unpaid_work_entry_type_ids.mapped('code')
            if not codes:
                continue
            print(f"  {short(structure.name, 44):<44} {', '.join(sorted(codes))}")
        print("\n  Read this against the mapping above. AESICKLEAVE0 belongs in the")
        print("  unpaid list wherever SICKLEAVE0 sits today - but the structures are")
        print("  rebuilt from the localisation in the next step, which brings its own")
        print("  list, so this is left alone here rather than fixed twice.")

    # ------------------------------------------------------------------
    title("summary")

    changes = [e for e in plan if e['current'] != e['target']]
    for entry in changes:
        print(f"  {short(entry['type'].name, 18):<18} "
              f"{entry['current'].code or '(none)'} -> {entry['target'].code}"
              f"   with {len(entry.get('closures') or [])} closure(s) and "
              f"{len(entry.get('entries') or [])} work entry/entries")
    if not changes:
        print("  every type already points where the rules look.")

    if not APPLY:
        env.cr.rollback()
        print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write.")
    else:
        written = []
        for entry in changes:
            entry['type'].work_entry_type_id = entry['target'].id
            written.append(f"{short(entry['type'].name, 20)}: -> {entry['target'].code}")
            closures = entry.get('closures')
            if closures:
                closures.write({'work_entry_type_id': entry['target'].id})
                written.append(f"{short(entry['type'].name, 20)}: {len(closures)} "
                               f"calendar closure(s) re-stamped")
            entries = entry.get('entries')
            if entries:
                # A validated work entry has already been counted by something;
                # it is named rather than rewritten.
                movable = entries.filtered(lambda w: w.state != 'validated')
                stuck = entries - movable
                if movable:
                    movable.write({'work_entry_type_id': entry['target'].id})
                    written.append(f"{short(entry['type'].name, 20)}: {len(movable)} "
                                   f"work entry/entries re-typed")
                if stuck:
                    written.append(f"{short(entry['type'].name, 20)}: {len(stuck)} "
                                   f"validated work entry/entries LEFT as they were")
        env.cr.commit()
        print("\nwritten:")
        for line in written or ['(nothing)']:
            print(f"  . {line}")
        print("\nnext: the staff contracts move to the Working Schedule source, so a")
        print("month is paid as a month and their leave comes with it.")
