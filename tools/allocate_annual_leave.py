"""Give every active employee the annual leave balance the law already gave them.

    odoo-bin shell -d <database> --no-http < tools/allocate_annual_leave.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/allocate_annual_leave.py

The leave migration created a hundred and fifty three allocations, one per
employee per year, but only for the hundred and thirty people who actually took
annual leave. The balance was a means there, not the point: without one the
leave would not save. Everybody else is sitting on zero.

Zero is wrong three ways and none of them are cosmetic. The employee cannot
file a request, because the form refuses a type with no balance. End of service
is understated, since unused annual leave is cashed out and a zero balance says
there is nothing to cash. And the company has no figure for what it owes:
accrued unused leave is a liability, and today it is visible for a hundred and
thirty people out of four hundred and forty eight.

WHERE IT STARTS

2025. Service before that is treated as settled and paid, which is the simplest
reading and the one the company chose. It assumes leave was taken or cashed as
it was earned. If that turns out to be untrue for somebody, the answer is an
opening balance HR states for that person, not a rule in this file.

NOT WRITING THE SAME BALANCE TWICE

These allocations carry no end date. An unused day is cashed out when somebody
leaves, not written off in December, so the balance has to keep running.

Which is what makes the obvious duplicate test wrong. A balance that opens in
January 2025 and never closes is still open in January 2026, so asking whether
an employee has a balance covering the day their 2026 entitlement starts finds
the 2025 one and skips the year - twenty seven days for two years instead of
twenty seven and then thirty. The question is not whether a window is open, it
is whether this particular year has already been granted, so the test is the
year the allocation opens in. One grant per employee per year, and a balance
that already exists is never topped up, replaced or duplicated.
"""
import os
import re
from collections import defaultdict
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

APPLY = os.environ.get('SSC_APPLY') == '1'

TYPE_NAME = 'Annual Leave'
FIRST_YEAR = 2025
LAST_YEAR = date.today().year

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
    mail_notify_force_send=False,
))

Employee = env['hr.employee'].sudo()
Leave = env['hr.leave'].sudo()
Allocation = env['hr.leave.allocation'].sudo()
LeaveType = env['hr.leave.type'].sudo()
Ssc = env['ssc.employee'].sudo() if 'ssc.employee' in env else None


def title(text):
    print()
    print("=" * 88)
    print(text)
    print("=" * 88)


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


annual = LeaveType.search([('name', '=', TYPE_NAME), ('active', '=', True)], limit=1)
if not annual:
    print(f"leave type {TYPE_NAME!r} does not exist - stopping")
    raise SystemExit

# ---------------------------------------------------------------------------
title("1. who is in scope")

active = Employee.with_context(active_test=True).search([])

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

with_date = [e for e in active if joined_by_employee.get(e.id)]
without = [e for e in active if not joined_by_employee.get(e.id)]

print(f"  active employees      : {len(active)}")
print(f"  joining date known    : {len(with_date)}")
print(f"  no joining date       : {len(without)}")
print(f"  years                 : {FIRST_YEAR} to {LAST_YEAR}")

# ---------------------------------------------------------------------------
title("2. balances that already exist")

# Every validated annual allocation, kept whole so its window can be tested
# against each employee's own opening day rather than a shared date.
existing = defaultdict(list)
for allocation in Allocation.search([('holiday_status_id', '=', annual.id),
                                     ('state', '=', 'validate')]):
    existing[allocation.employee_id.id].append(allocation)


def already_has(employee, year):
    """Has this employee already been granted this particular year?

    Keyed on the year the allocation opens, not on whether its window happens
    to be open on some day. The allocations here carry no end date, because an
    unused day is cashed out at the end of service rather than expiring in
    December - so a balance opening in January 2025 is still open in 2026, and
    asking whether a window covers a day would let one year's grant stand in
    for the next one. Twenty seven days for two years instead of twenty seven
    and then thirty.
    """
    for allocation in existing.get(employee.id, ()):
        if allocation.date_from and allocation.date_from.year == year:
            return allocation
    return None


held = defaultdict(int)
to_create = []
nothing_earned = []
for employee in with_date:
    joined = joined_by_employee[employee.id]
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        days = entitlement_for_year(joined, year)
        if days <= 0:
            nothing_earned.append((employee, year, joined))
            continue
        opens = max(date(year, 1, 1), joined)
        if already_has(employee, year):
            held[year] += 1
            continue
        to_create.append((employee, year, days, opens, joined))

print(f"  {sum(held.values())} employee-year(s) already carry one and are left alone")
for year in sorted(held):
    print(f"      {year}   {held[year]:>4}")
print()
print(f"  {len(nothing_earned)} employee-year(s) earned nothing, joined too late in the year")

# ---------------------------------------------------------------------------
title("3. balances to create")

per_year = defaultdict(lambda: [0, 0.0])
for _employee, year, days, _opens, _joined in to_create:
    per_year[year][0] += 1
    per_year[year][1] += days

print(f"  {len(to_create)} allocation(s)")
print()
print(f"  {'year':<8} {'people':>8} {'days':>12}")
for year in sorted(per_year):
    number, days = per_year[year]
    print(f"  {year:<8} {number:>8} {days:>12.2f}")
print()
for employee, year, days, opens, joined in sorted(
        to_create, key=lambda x: (x[0].name, x[1]))[:12]:
    print(f"  {employee.name[:32]:<32} {year}  joined {joined}  opens {opens}  "
          f"{days:>6.2f} day(s)")
if len(to_create) > 12:
    print(f"  ... and {len(to_create) - 12} more")

if without:
    title("4. no joining date, skipped - nothing can be worked out for these")
    for employee in sorted(without, key=lambda e: e.name):
        print(f"  {employee.name[:38]:<38} id={employee.id:<6} "
              f"badge={employee.barcode or '-'}")

# ---------------------------------------------------------------------------
title("5. what the company will owe once this is in")

granted_now = sum(a.number_of_days for group in existing.values() for a in group)
granted_after = granted_now + sum(d for _e, _y, d, _o, _j in to_create)
taken = sum(Leave.search([('holiday_status_id', '=', annual.id),
                          ('state', '=', 'validate')]).mapped('number_of_days'))

print(f"  granted today   {granted_now:>10.2f} day(s)")
print(f"  granted after   {granted_after:>10.2f} day(s)")
print(f"  taken           {taken:>10.2f} day(s)")
print(f"  unused          {granted_after - taken:>10.2f} day(s)")
print()
print("  Unused annual leave is cashed out at end of service, so that last")
print("  figure is money the company owes. It has been invisible until now.")

# ---------------------------------------------------------------------------
if APPLY:
    # Written in batches, and the state set directly rather than through
    # action_approve. Approving walks the whole notification machinery for every
    # record - partners, followers, web push devices - and the first attempt at
    # this spent sixteen minutes doing that for five hundred and ninety grants
    # whose notifications we had already switched off. The work is the rows.
    CHUNK = 100
    rows = [({
        'name': f'Annual leave entitlement {year}',
        'employee_id': employee.id,
        'holiday_status_id': annual.id,
        'number_of_days': days,
        'date_from': opens,
    }, employee.name, year) for employee, year, days, opens, _joined in to_create]

    made, failed = 0, []
    for index in range(0, len(rows), CHUNK):
        batch = rows[index:index + CHUNK]
        try:
            with env.cr.savepoint():
                created = Allocation.create([vals for vals, _n, _y in batch])
                pending = created.filtered(lambda a: a.state != 'validate')
                if pending:
                    pending.write({'state': 'validate'})
            made += len(batch)
        except Exception:
            # One bad row must not cost the ninety nine good ones beside it.
            for vals, name, year in batch:
                try:
                    with env.cr.savepoint():
                        allocation = Allocation.create(vals)
                        if allocation.state != 'validate':
                            allocation.write({'state': 'validate'})
                    made += 1
                except Exception as error:
                    failed.append((name, year, str(error).splitlines()[0][:74]))
        env.cr.commit()
        print(f"  {made + len(failed):>4} / {len(rows)}")

    title("APPLIED")
    print(f"  created {made} | refused {len(failed)}")
    for name, year, message in failed:
        print(f"      {name[:28]:<28} {year}  {message}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
