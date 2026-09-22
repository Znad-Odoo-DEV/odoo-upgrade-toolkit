"""Explain the approved leaves that hr.leave refused to take.

    odoo-bin shell -d <database> --no-http < tools/diagnose_leave_refusals.py

Read only.

The migration created 155 of 169 and refused 10, in three voices: no valid
allocation, no allocation at all, and an overlap with time off already booked.
The messages name the problem but not the cause, and the cause is different
each time - a balance that starts after the leave does, a year the person had
not yet earned anything in, or a sick leave already sitting on the same days.

For each refusal this prints the joining date, every annual allocation the
person holds with its window, and any leave of any type that touches the span.
That is enough to say which of the three it is without opening a single form.
"""
import re
from datetime import timedelta

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

SOURCE = 'x_all_requests'
KINDS = {'ALR': 'Annual Leave', 'ELR': 'Emergency Leave'}

Request = env[SOURCE].sudo()
Employee = env['hr.employee'].sudo()
Attendance = env['hr.attendance'].sudo()
Leave = env['hr.leave'].sudo()
Allocation = env['hr.leave.allocation'].sudo()
LeaveType = env['hr.leave.type'].sudo()
Ssc = env['ssc.employee'].sudo() if 'ssc.employee' in env else None


def badge(value):
    return re.sub(r'[^A-Za-z0-9]', '', (value or '').strip())[:18].upper()


def trim(start, end, punched):
    first, last = start, end
    while first <= last and first in punched:
        first += timedelta(days=1)
    while last >= first and last in punched:
        last -= timedelta(days=1)
    if first > last:
        return None
    day = first
    while day <= last:
        if day in punched:
            return None
        day += timedelta(days=1)
    return first, last


types = {code: LeaveType.search([('name', '=', name)], limit=1)
         for code, name in KINDS.items()}

by_badge = {}
for employee in Employee.search([]):
    if employee.barcode:
        by_badge.setdefault(badge(employee.barcode), employee)

joined_by_employee = {}
if Ssc is not None:
    for record in Ssc.with_context(active_test=False).search([]):
        if not record.joining_date:
            continue
        if record.hr_employee_id:
            joined_by_employee.setdefault(record.hr_employee_id.id, record.joining_date)
        key = badge(record.attendance_code)
        if key and key in by_badge:
            joined_by_employee.setdefault(by_badge[key].id, record.joining_date)

missing = []
for request in Request.search([('x_studio_type_of_request_1', 'in', list(KINDS)),
                               ('x_studio_status', '=', 'S5')]):
    start, end = request.x_studio_first_day_of_leave, request.x_studio_last_day_of_leave
    if not (start and end) or end < start:
        continue
    employee = by_badge.get(badge(
        getattr(request.x_studio_requested_for, 'x_studio_attendance_id', False)))
    if not employee:
        continue
    punched = {p.check_in.date() for p in Attendance.search([
        ('employee_id', '=', employee.id),
        ('check_in', '>=', start),
        ('check_in', '<', end + timedelta(days=1))])}
    punched = {d for d in punched if start <= d <= end}
    if punched:
        kept = trim(start, end, punched)
        if kept is None:
            continue
        start, end = kept
    leave_type = types[request.x_studio_type_of_request_1]
    if Leave.search_count([('employee_id', '=', employee.id),
                           ('holiday_status_id', '=', leave_type.id),
                           ('request_date_from', '<=', end),
                           ('request_date_to', '>=', start)]):
        continue
    missing.append((employee, start, end, leave_type, request))

print("=" * 94)
print(f"{len(missing)} planned leave(s) are still not in hr.leave")
print("=" * 94)

for employee, start, end, leave_type, request in sorted(missing, key=lambda x: x[1]):
    joined = joined_by_employee.get(employee.id)
    print(f"\n{employee.name}   id={employee.id}  badge={employee.barcode or '-'}")
    print(f"  wants     {leave_type.name}  {start} .. {end}  "
          f"({(end - start).days + 1}d)   {request.x_name or ''}")
    print(f"  joined    {joined or 'UNKNOWN'}")

    allocations = Allocation.search([('employee_id', '=', employee.id),
                                     ('holiday_status_id', '=', leave_type.id)])
    if not allocations:
        print(f"  balance   none at all for {leave_type.name}")
    for allocation in allocations.sorted('date_from'):
        covers = (allocation.date_from or start) <= start and (
            not allocation.date_to or allocation.date_to >= end)
        print(f"  balance   {allocation.number_of_days:>6.2f}d  "
              f"{allocation.date_from} .. {allocation.date_to or 'open'}  "
              f"{allocation.state:<10} {'covers it' if covers else 'DOES NOT COVER'}")

    # what the balance actually adds up to on the day the leave starts
    usable = allocations.filtered(
        lambda a: a.state == 'validate'
        and (not a.date_from or a.date_from <= start)
        and (not a.date_to or a.date_to >= start))
    granted = sum(usable.mapped('number_of_days'))
    taken = sum(Leave.search([('employee_id', '=', employee.id),
                              ('holiday_status_id', '=', leave_type.id),
                              ('state', '=', 'validate')]).mapped('number_of_days'))
    day, wanted = start, 0
    while day <= end:
        if day.weekday() != 4:
            wanted += 1
        day += timedelta(days=1)
    left = granted - taken - wanted
    cap = leave_type.max_allowed_negative if leave_type.allows_negative else 0
    print(f"  arithmetic {granted:>6.2f} granted - {taken:>6.2f} taken - "
          f"{wanted:>3} wanted = {left:>7.2f}   "
          f"{'within' if left >= -cap else 'PAST'} the -{cap} cap")

    others = Leave.search([('employee_id', '=', employee.id),
                           ('request_date_from', '<=', end),
                           ('request_date_to', '>=', start)])
    for other in others:
        print(f"  clashes   {other.holiday_status_id.name:<22} "
              f"{other.request_date_from} .. {other.request_date_to}  {other.state}")
    if not others:
        print("  clashes   nothing booked over these days")

print("\n" + "=" * 94)
print("nothing was written")
print("=" * 94)
