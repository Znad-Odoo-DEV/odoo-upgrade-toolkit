"""Move the approved leave requests out of Studio and into hr.leave.

    odoo-bin shell -d <database> --no-http < tools/migrate_annual_leave_to_hr.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/migrate_annual_leave_to_hr.py

x_all_requests carries 1148 rows of every kind - materials, payment
certificates, advances, resignations - and 276 of them are leave: 223 annual,
53 emergency. 185 are approved, covering 7824 calendar days across 156
employees between December 2024 and November 2026. Fifty days each on average,
because Overseas Leave is on 274 of the 276: labourers going home for six or
seven weeks at a stretch.

THE PAPERWORK AND THE PUNCHES DISAGREE

Twenty-three of the approved leaves have attendance inside them, and drawing
the span out day by day shows two different stories. Six are punched across the
whole period - those people never left, the request was approved and then not
taken and nothing closed it. The rest are punched only at one end or the other:
the leave happened, it just started later or ended earlier than the form says.

So the span is trimmed rather than thrown away. Punched days come off the front
and off the back, and what remains is the leave that actually happened. If
punches survive in the middle after trimming, nobody left and the request is
skipped and listed for HR to cancel at the source.

Punches are counted strictly inside the span. A punch the day after a leave
ends is somebody coming back to work, which is what should happen.

THE ALLOCATION

Per calendar year, not cumulative from the joining date. Thirty days a year
once a year of service is behind you, two a month between six and twelve
months. Eight years of accrual measured against twenty months of leave records
would report two hundred spare days that nobody ever owed; a year at a time
says something true about the period there is data for. Whatever was earned
before that is an opening balance and only HR can state it.

Annual Leave is allowed a negative balance, because some of these people took
more than they had accrued and refusing the leave would not make that untrue.

WHAT THIS DOES NOT TOUCH

Payroll. The standard engine is not paying anybody yet, so these sit in Time
Off as record and report. The day ssc_payroll is switched off, the leave salary
it pays in advance goes with it, or the same days are paid twice - the rule
that governs the timesheets as well: one rail carries the money.
"""
import os
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

APPLY = os.environ.get('SSC_APPLY') == '1'

SOURCE = 'x_all_requests'
APPROVED = 'S5'
KINDS = {'ALR': 'Annual Leave', 'ELR': 'Emergency Leave'}
NEGATIVE_CAP = 30
OFF_WEEKDAY = 4                     # Friday, per the working schedule
EMERGENCY_WORK_ENTRY = 'LEAVE100'   # Generic Time Off - paid, and its own line

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    # Migrating an absence that finished months ago is not news. Without this
    # every approval writes to the employee, and a hundred and sixty of them
    # walk straight into the server's daily email limit.
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
    mail_notify_force_send=False,
))

Request = env.get(SOURCE)
Employee = env['hr.employee'].sudo()
Attendance = env['hr.attendance'].sudo()
Leave = env['hr.leave'].sudo()
Allocation = env['hr.leave.allocation'].sudo()
LeaveType = env['hr.leave.type'].sudo()
WorkEntryType = env['hr.work.entry.type'].sudo()
Ssc = env['ssc.employee'].sudo() if 'ssc.employee' in env else None


def title(text):
    print("\n" + "=" * 90)
    print(text)
    print("=" * 90)


def badge(value):
    return re.sub(r'[^A-Za-z0-9]', '', (value or '').strip())[:18].upper()


def entitlement_for_year(joined, year):
    """Annual leave earned inside one calendar year, per Decree-Law 33 of 2021."""
    if not joined:
        return 0.0
    year_start, year_end = date(year, 1, 1), date(year, 12, 31)
    if joined > year_end:
        return 0.0
    earning_from = max(year_start, joined + relativedelta(months=6))
    if earning_from > year_end:
        return 0.0
    full_rate_from = max(year_start, joined + relativedelta(months=12))
    days = 0.0
    if full_rate_from > earning_from:
        partial_end = min(full_rate_from, year_end + timedelta(days=1))
        days += (partial_end - earning_from).days / 30.44 * 2
    if full_rate_from <= year_end:
        days += ((year_end - max(full_rate_from, year_start)).days + 1) / 365.0 * 30.0
    return round(days, 2)


def trim(start, end, punched):
    """The leave that actually happened, or None if the person never left.

    Punched days come off the front and off the back. Anything punched still
    sitting in the middle means the person was here throughout and the request
    was never taken.
    """
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


if Request is None:
    print(f"{SOURCE} is not on this database - nothing to do")
    raise SystemExit

types = {}
for code, name in KINDS.items():
    found = LeaveType.search([('name', '=', name), ('active', '=', True)], limit=1)
    if not found:
        print(f"leave type {name!r} does not exist - stopping")
        raise SystemExit
    types[code] = found

annual, emergency = types['ALR'], types['ELR']
generic = WorkEntryType.search([('code', '=', EMERGENCY_WORK_ENTRY)], limit=1)

# ---------------------------------------------------------------------------
title("1. leave type configuration")

config = []
if not annual.allows_negative:
    config.append((annual, {'allows_negative': True,
                            'max_allowed_negative': NEGATIVE_CAP},
                   f"allow a negative balance down to {NEGATIVE_CAP} days"))
if emergency.requires_allocation:
    config.append((emergency, {'requires_allocation': False},
                   "stop requiring an allocation"))
if not emergency.work_entry_type_id and generic:
    config.append((emergency, {'work_entry_type_id': generic.id},
                   f"work entry type -> {generic.name}"))
for record, _vals, what in config:
    print(f"  {record.name:<22} {what}")
if not config:
    print("  already configured")

# ---------------------------------------------------------------------------
title("2. reading the approved requests")

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

items, unmatched = [], []
for request in Request.sudo().search([
        ('x_studio_type_of_request_1', 'in', list(KINDS)),
        ('x_studio_status', '=', APPROVED)]):
    start, end = request.x_studio_first_day_of_leave, request.x_studio_last_day_of_leave
    if not (start and end) or end < start:
        continue
    employee = by_badge.get(badge(
        getattr(request.x_studio_requested_for, 'x_studio_attendance_id', False)))
    if employee:
        items.append((employee, start, end, request))
    else:
        unmatched.append(request)

print(f"  approved   : {len(items) + len(unmatched)}")
print(f"  matched    : {len(items)}")
print(f"  unmatched  : {len(unmatched)}")

# ---------------------------------------------------------------------------
title("3. trimming against the punches")

planned, never_left, trimmed = [], [], []
for employee, start, end, request in items:
    punched = {p.check_in.date() for p in Attendance.search([
        ('employee_id', '=', employee.id),
        ('check_in', '>=', start),
        ('check_in', '<', end + timedelta(days=1)),
    ])}
    punched = {d for d in punched if start <= d <= end}
    if not punched:
        planned.append((employee, start, end, request))
        continue
    kept = trim(start, end, punched)
    if kept is None:
        never_left.append((employee, start, end, request, len(punched)))
        continue
    planned.append((employee, kept[0], kept[1], request))
    trimmed.append((employee, start, end, kept, len(punched)))

print(f"  untouched          : {len(planned) - len(trimmed)}")
print(f"  trimmed            : {len(trimmed)}")
print(f"  never left, skipped: {len(never_left)}\n")
for employee, start, end, kept, punches in sorted(trimmed, key=lambda x: x[1]):
    was = (end - start).days + 1
    now = (kept[1] - kept[0]).days + 1
    print(f"  {employee.name[:30]:<30} {start} .. {end} ({was:>3}d) "
          f"-> {kept[0]} .. {kept[1]} ({now:>3}d)   {punches} punch(es)")

title("4. NEVER LEFT - approved but not taken, cancel these at the source")
for employee, start, end, request, punches in sorted(never_left, key=lambda x: x[1]):
    days = (end - start).days + 1
    print(f"  {employee.name[:32]:<32} {start} .. {end}  ({days:>3}d)  "
          f"{punches:>3} punch(es)  {request.x_name or ''}")

# ---------------------------------------------------------------------------
title("5. splitting around time off already booked")

split, swallowed, adjusted, done = [], [], [], []
for employee, start, end, request in planned:
    leave_type = types[request.x_studio_type_of_request_1]

    # Already migrated, on an earlier run or by a request asking for the same
    # days twice. Settle that before splitting, or a second run would cut every
    # leave against the copy of itself it made the first time.
    if Leave.search_count([('employee_id', '=', employee.id),
                           ('holiday_status_id', '=', leave_type.id),
                           ('state', '=', 'validate'),
                           ('request_date_from', '<=', end),
                           ('request_date_to', '>=', start)]):
        done.append((employee, start, end, request))
        continue

    booked = set()
    for other in Leave.search([('employee_id', '=', employee.id),
                               ('holiday_status_id', '!=', leave_type.id),
                               ('state', '=', 'validate'),
                               ('request_date_from', '<=', end),
                               ('request_date_to', '>=', start)]):
        day = max(other.request_date_from, start)
        while day <= min(other.request_date_to, end):
            booked.add(day)
            day += timedelta(days=1)
    if not booked:
        split.append((employee, start, end, request))
        continue
    segments, run = [], None
    day = start
    while day <= end:
        if day in booked:
            if run:
                segments.append(run)
                run = None
        else:
            run = (run[0] if run else day, day)
        day += timedelta(days=1)
    if run:
        segments.append(run)
    segments = [s for s in segments
                if any((s[0] + timedelta(days=i)).weekday() != OFF_WEEKDAY
                       for i in range((s[1] - s[0]).days + 1))]
    if not segments:
        swallowed.append((employee, start, end, request))
        continue
    for first, last in segments:
        split.append((employee, first, last, request))
    adjusted.append((employee, start, end, segments))

planned = split
print(f"  untouched                  : {len(planned) - sum(len(a[3]) for a in adjusted)}")
print(f"  cut around another leave   : {len(adjusted)}")
print(f"  already covered end to end : {len(swallowed)}")
print(f"  already in Time Off        : {len(done)}")
print()
for employee, start, end, segments in sorted(adjusted, key=lambda x: x[1]):
    pieces = "  +  ".join(f"{a} .. {b}" for a, b in segments)
    print(f"  {employee.name[:30]:<30} {start} .. {end}  ->  {pieces}")
for employee, start, end, request in sorted(swallowed, key=lambda x: x[1]):
    print(f"  {employee.name[:30]:<30} {start} .. {end}  DROPPED, the days are "
          f"already off  ({request.x_name or ''})")

# ---------------------------------------------------------------------------
title("6. allocations, one per employee per calendar year")

years_needed = defaultdict(set)
earliest = {}
for employee, start, end, request in planned:
    if request.x_studio_type_of_request_1 != 'ALR':
        continue
    for year in range(start.year, end.year + 1):
        years_needed[employee].add(year)
        key = (employee.id, year)
        opens = max(start, date(year, 1, 1))
        earliest[key] = min(earliest.get(key, opens), opens)

# An allocation counts only if its window is open on the day the leave starts.
# Keying on the year alone let a balance that opens in November stand in for a
# leave taken in July, and the employee was then refused for having nothing.
held = set()
for allocation in Allocation.search([('holiday_status_id', '=', annual.id),
                                     ('state', '=', 'validate')]):
    for (employee_id, year), opens in earliest.items():
        if allocation.employee_id.id != employee_id:
            continue
        if (allocation.date_from or opens) <= opens and (
                not allocation.date_to or allocation.date_to >= opens):
            held.add((employee_id, year))

to_allocate, no_joining = [], []
for employee, years in years_needed.items():
    joined = joined_by_employee.get(employee.id)
    if not joined:
        no_joining.append(employee)
        continue
    for year in sorted(years):
        if (employee.id, year) in held:
            continue
        days = entitlement_for_year(joined, year)
        if days > 0:
            to_allocate.append((employee, year, days, joined))

print(f"  employees taking annual leave : {len(years_needed)}")
print(f"  allocations to create         : {len(to_allocate)}")
if no_joining:
    print(f"  no joining date, skipped      : {[e.name for e in no_joining]}")
print()
for employee, year, days, joined in sorted(to_allocate, key=lambda x: (x[0].name, x[1]))[:14]:
    print(f"  {employee.name[:32]:<32} {year}  joined {joined}  {days:>6.2f} day(s)")
if len(to_allocate) > 14:
    print(f"  ... and {len(to_allocate) - 14} more")

# ---------------------------------------------------------------------------
title("7. leaves to create")

counts = Counter(types[r.x_studio_type_of_request_1].name for _e, _s, _x, r in planned)
print(f"  {len(planned)} leave(s)")
for name, number in counts.most_common():
    print(f"      {name:<22} {number}")

# ---------------------------------------------------------------------------
if APPLY:
    for record, vals, _what in config:
        record.write(vals)

    made_allocations, failed_allocations = 0, []
    for employee, year, days, joined in to_allocate:
        try:
            with env.cr.savepoint():
                allocation = Allocation.create({
                    'name': f'Annual leave entitlement {year}',
                    'employee_id': employee.id,
                    'holiday_status_id': annual.id,
                    'number_of_days': days,
                    'date_from': max(date(year, 1, 1), joined),
                })
                if allocation.state != 'validate':
                    allocation.action_approve()
                if allocation.state != 'validate' and hasattr(allocation, 'action_validate'):
                    allocation.action_validate()
            made_allocations += 1
        except Exception as error:
            failed_allocations.append((employee.name, year, str(error).splitlines()[0][:76]))

    made, already, failed = 0, 0, []
    for employee, start, end, request in planned:
        leave_type = types[request.x_studio_type_of_request_1]
        if Leave.search_count([('employee_id', '=', employee.id),
                               ('holiday_status_id', '=', leave_type.id),
                               ('request_date_from', '<=', end),
                               ('request_date_to', '>=', start)]):
            already += 1
            continue
        label = request.x_name or request.x_studio_reason_of_leave or leave_type.name
        try:
            with env.cr.savepoint():
                leave = Leave.create({
                    'employee_id': employee.id,
                    'holiday_status_id': leave_type.id,
                    'request_date_from': start,
                    'request_date_to': end,
                    'name': str(label)[:120],
                })
                if leave.state != 'validate':
                    leave.action_approve()
                if leave.state != 'validate' and hasattr(leave, 'action_validate'):
                    leave.action_validate()
            made += 1
        except Exception as error:
            failed.append((employee.name, start, str(error).splitlines()[0][:76]))

    env.cr.commit()
    title("APPLIED")
    print(f"  configuration changes : {len(config)}")
    print(f"  allocations created   : {made_allocations} / {len(to_allocate)}")
    print(f"  leaves created        : {made} | already there {already} | refused {len(failed)}")
    for name, year, message in failed_allocations:
        print(f"      allocation refused {name[:26]:<26} {year}  {message}")
    for name, start, message in failed:
        print(f"      leave refused {name[:26]:<26} {start}  {message}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
