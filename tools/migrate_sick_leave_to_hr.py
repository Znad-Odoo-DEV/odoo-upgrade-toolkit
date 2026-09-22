"""Move the approved sick-leave reports out of Studio and into hr.leave.

    odoo-bin shell -d <database> --no-http < tools/migrate_sick_leave_to_hr.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/migrate_sick_leave_to_hr.py

x_sick_leave_reports holds 330 rows, 226 of them approved, covering 400
calendar days between February 2025 and July 2026. Payroll has been reading
them straight from Studio and paying the day through attendance instead, so
hr.leave knows nothing: no balance, no work entry, and a sick day looks like an
absence to anything standard.

THE LADDER

Federal Decree-Law 33 of 2021 gives ninety sick days a year, and pays them in
three bands: the first fifteen in full, the next thirty at half, the last
forty-five at nothing. Each employee's days are walked in date order within the
calendar year and land in whichever band they fall into, so one report can turn
into two or three leaves if it crosses a line.

On today's data nothing crosses: 378 working days, all of them inside the first
fifteen. The ladder costs nothing now and starts earning its keep the first time
somebody is ill for a month.

Days are counted the way Odoo counts them, off the working schedule, because
that is what payroll will pay. Counting calendar days and paying working days
would put the balance and the money permanently out of step.

WHAT IS LEFT ALONE

A report whose span already carries a punch is skipped and listed. Fifteen of
them do: short absences where somebody clocked in and then went to a doctor.
Both facts are true, and creating the leave on top would have the day counted
twice. A person decides those, not this.

The medical bill amount does not come across either. It is a reimbursement, and
it belongs in the payslip inputs, not in a leave record.
"""
import os
import re
from collections import defaultdict
from datetime import timedelta

APPLY = os.environ.get('SSC_APPLY') == '1'

SOURCE = 'x_sick_leave_reports'
STATUS_FIELD = 'x_studio_selection_field_632_1ii4lpujj'
APPROVED = 'Approved'
OFF_WEEKDAY = 4                       # Friday, per the working schedule

# band ceiling in days -> the leave type that pays it
LADDER = [
    (15, 'Sick Time Off'),            # full pay
    (45, 'Sick Leave 50%'),           # half pay
    (90, 'Sick Leave 0%'),            # unpaid
]

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    # Migrating an absence that finished months ago is not news. Without this
    # every approval writes to the employee, and a hundred and sixty of them
    # walk straight into the server's daily email limit.
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
    mail_notify_force_send=False,
))

Report = env.get(SOURCE)
Employee = env['hr.employee'].sudo()
Attendance = env['hr.attendance'].sudo()
Leave = env['hr.leave'].sudo()
LeaveType = env['hr.leave.type'].sudo()


def title(text):
    print("\n" + "=" * 86)
    print(text)
    print("=" * 86)


def badge(value):
    return re.sub(r'[^A-Za-z0-9]', '', (value or '').strip())[:18].upper()


def working_days(start, end):
    """The days Odoo will actually charge, Friday excepted."""
    day, count = start, 0
    while day <= end:
        if day.weekday() != OFF_WEEKDAY:
            count += 1
        day += timedelta(days=1)
    return count


if Report is None:
    print(f"{SOURCE} is not on this database - nothing to do")
    raise SystemExit

types = {}
for label in (name for _ceiling, name in LADDER):
    found = LeaveType.search([('name', '=', label)], limit=1)
    if not found:
        print(f"leave type {label!r} does not exist - stopping")
        raise SystemExit
    types[label] = found

by_badge = {}
for employee in Employee.search([]):
    if employee.barcode:
        by_badge.setdefault(badge(employee.barcode), employee)

# ---------------------------------------------------------------------------
# read the source
# ---------------------------------------------------------------------------
items, unmatched, undated = [], [], []
for report in Report.sudo().search([(STATUS_FIELD, '=', APPROVED)]):
    source = report.x_studio_employee
    if report.x_studio_for == 'value_2':
        start, end = report.x_studio_from_date, report.x_studio_to_date
    else:
        start = end = report.x_studio_date or report.x_studio_from_date
    if not (start and end):
        undated.append(report)
        continue
    employee = by_badge.get(badge(getattr(source, 'x_studio_attendance_id', False)))
    if not employee:
        unmatched.append((report, getattr(source, 'x_name', '') or '?'))
        continue
    items.append((employee, start, end, report))

title("source")
print(f"  approved reports    : {len(items) + len(unmatched) + len(undated)}")
print(f"  matched to employee : {len(items)}")
print(f"  no employee found   : {len(unmatched)}")
for _report, who in unmatched:
    print(f"      {who}")
print(f"  no usable dates     : {len(undated)}")

# ---------------------------------------------------------------------------
# a punch inside the span means a person has to decide
# ---------------------------------------------------------------------------
clashes, clean = [], []
for employee, start, end, report in items:
    punches = Attendance.search_count([
        ('employee_id', '=', employee.id),
        ('check_in', '>=', start),
        ('check_in', '<=', end + timedelta(days=1)),
    ])
    (clashes if punches else clean).append((employee, start, end, report, punches))

title("skipped - the span already carries a punch")
print(f"  {len(clashes)} report(s)\n")
for employee, start, end, _report, punches in sorted(clashes, key=lambda x: x[1]):
    print(f"  {employee.name[:32]:<32} {start} .. {end}  "
          f"({(end - start).days + 1}d)  attendance={punches}")

# ---------------------------------------------------------------------------
# walk the ladder
# ---------------------------------------------------------------------------
per_year = defaultdict(list)
for employee, start, end, report, _punches in clean:
    per_year[(employee, start.year)].append((start, end, report))

planned = []
for (employee, _year), spans in per_year.items():
    used = 0
    for start, end, report in sorted(spans):
        day = start
        run_start, run_label = None, None
        while day <= end:
            if day.weekday() == OFF_WEEKDAY:
                day += timedelta(days=1)
                continue
            used += 1
            label = next((name for ceiling, name in LADDER if used <= ceiling), None)
            if label != run_label:
                if run_start is not None:
                    planned.append((employee, run_start, previous, run_label, report))
                run_start, run_label = day, label
            previous = day
            day += timedelta(days=1)
        if run_start is not None and run_label is not None:
            planned.append((employee, run_start, previous, run_label, report))

title("leaves to create")
counts = defaultdict(int)
for _employee, start, end, label, _report in planned:
    counts[label] += working_days(start, end)
print(f"  {len(planned)} leave record(s) from {len(clean)} report(s)")
for _ceiling, label in LADDER:
    print(f"      {label:<20} {counts.get(label, 0):>4} working day(s)")
print()
for employee, start, end, label, _report in sorted(planned, key=lambda x: (x[0].name, x[1]))[:20]:
    print(f"  {employee.name[:30]:<30} {start} .. {end}  {label}")
if len(planned) > 20:
    print(f"  ... and {len(planned) - 20} more")

# ---------------------------------------------------------------------------
if APPLY:
    created, skipped, failed = 0, 0, []
    for employee, start, end, label, report in planned:
        leave_type = types[label]
        existing = Leave.search_count([
            ('employee_id', '=', employee.id),
            ('holiday_status_id', '=', leave_type.id),
            ('request_date_from', '<=', end),
            ('request_date_to', '>=', start),
        ])
        if existing:
            skipped += 1
            continue
        try:
            with env.cr.savepoint():
                leave = Leave.create({
                    'employee_id': employee.id,
                    'holiday_status_id': leave_type.id,
                    'request_date_from': start,
                    'request_date_to': end,
                    'name': (getattr(report, 'x_name', '') or 'Sick leave')[:120],
                })
                if leave.state != 'validate':
                    leave.action_approve()
                if leave.state != 'validate' and hasattr(leave, 'action_validate'):
                    leave.action_validate()
            created += 1
        except Exception as error:
            failed.append((employee.name, start, str(error).splitlines()[0][:80]))
    env.cr.commit()
    title("APPLIED")
    print(f"  created {created} | already there {skipped} | refused {len(failed)}")
    for name, start, message in failed:
        print(f"      {name[:30]:<30} {start}  {message}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
