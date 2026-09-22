"""Look at the 23 approved leaves that have punches inside them.

    odoo-bin shell -d <database> --no-http < tools/inspect_leave_attendance_clash.py

Read only.

An approved fifty-day leave with fifty-four punches against it did not happen.
Either the request was approved and then not taken - plans change and nobody
closes the record - or the punches belong to somebody else. The two look
nothing alike once the days are laid out.

For each request the whole span is drawn a day at a time:

    #   a punch that day
    .   nothing
    _   Friday

Spread evenly across the span means the person never left. Clustered at one
end means they travelled and the dates are off by a few days. A short burst in
the middle means they came back early, or came in once for something.
"""
import re
from datetime import timedelta

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

Request = env['x_all_requests'].sudo()
Employee = env['hr.employee'].sudo()
Attendance = env['hr.attendance'].sudo()


def badge(value):
    return re.sub(r'[^A-Za-z0-9]', '', (value or '').strip())[:18].upper()


by_badge = {}
for employee in Employee.search([]):
    if employee.barcode:
        by_badge.setdefault(badge(employee.barcode), employee)

rows = []
for request in Request.search([('x_studio_type_of_request_1', 'in', ['ALR', 'ELR']),
                               ('x_studio_status', '=', 'S5')]):
    start = request.x_studio_first_day_of_leave
    end = request.x_studio_last_day_of_leave
    if not (start and end) or end < start:
        continue
    employee = by_badge.get(badge(
        getattr(request.x_studio_requested_for, 'x_studio_attendance_id', False)))
    if not employee:
        continue
    punches = Attendance.search([
        ('employee_id', '=', employee.id),
        ('check_in', '>=', start),
        ('check_in', '<=', end + timedelta(days=1)),
    ])
    if punches:
        rows.append((employee, start, end, request, punches))

print(f"{len(rows)} approved leave(s) with attendance inside the span\n")
print("legend:  # punched    . nothing    _ Friday\n")

for employee, start, end, request, punches in sorted(rows, key=lambda r: r[1]):
    days = (end - start).days + 1
    punched = {p.check_in.date() for p in punches}
    line, hit_positions = [], []
    day = start
    index = 0
    while day <= end:
        if day in punched:
            line.append('#')
            hit_positions.append(index)
        elif day.weekday() == 4:
            line.append('_')
        else:
            line.append('.')
        day += timedelta(days=1)
        index += 1

    # where the punches sit inside the span
    first_fifth = sum(1 for p in hit_positions if p < days * 0.2)
    last_fifth = sum(1 for p in hit_positions if p >= days * 0.8)
    middle = len(hit_positions) - first_fifth - last_fifth
    coverage = len(hit_positions) / max(days, 1)

    if coverage > 0.5:
        verdict = "NEVER LEFT - the leave did not happen"
    elif middle == 0 and (first_fifth or last_fifth):
        verdict = "edges only - the dates are off by a few days"
    elif coverage > 0.2:
        verdict = "came back early, or was in and out"
    else:
        verdict = "a handful of days - check individually"

    print(f"{employee.name[:34]:<34} {request.x_studio_type_of_request_1}  "
          f"{start} .. {end}  ({days:>3}d, {len(punched):>3} punched, "
          f"{coverage:>4.0%})")
    print(f"    {''.join(line)}")
    print(f"    start {first_fifth} | middle {middle} | end {last_fifth}   ->  {verdict}\n")
