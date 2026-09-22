"""Give a contract a start date, so the month stops being out of contract.

    odoo-bin shell -d <database> --no-http < tools/set_contract_start_dates.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/set_contract_start_dates.py

Forty six active contracts have no start date, and Odoo takes that literally: it
generates no working day for them at all. The whole month comes back as OUT, and
then two rules disagree about what that means. BASIC counts every covered day
and OUT is covered, so it pays the month in full. Out of Contract, which exists
precisely to take those days back, reads the contract dates to find them and
there are none, so it takes back nothing.

Eddie Kayondo, October 2025: twenty six days marked out of contract and three
thousand five hundred dirhams paid for them.

It is not a rule to fix. Both rules are right about what they were told. The
contract simply does not say when it began.

WHERE THE DATE COMES FROM

`joining_date` on ssc.employee - the same field the annual leave allocations
were built on, and the company's own answer to when somebody started. Where
that is empty, the first day they ever punched or the first period they were
ever paid for, whichever is earlier, since neither can precede the job.

Anyone with none of the three is printed and left alone. A contract that cannot
say when it started is a question for HR, not a date to invent.

WHAT IT DOES NOT TOUCH

The end date. Some of these contracts carry one from the ministry permit list
and some are open, and both are fine - this is only about the beginning.
"""
import os
import re
from datetime import date

APPLY = os.environ.get('SSC_APPLY') == '1'

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

Employee = env['hr.employee'].sudo()
Attendance = env['hr.attendance'].sudo()
Ssc = env['ssc.employee'].sudo() if 'ssc.employee' in env else None
Slip = env['ssc.payslip'].sudo() if 'ssc.payslip' in env else None


today = date.today()


def title(text):
    print()
    print("=" * 96)
    print(text)
    print("=" * 96)


def badge(value):
    return re.sub(r'[^A-Za-z0-9]', '', (value or '').strip())[:18].upper()


by_badge = {}
for person in Employee.search([]):
    if person.barcode:
        by_badge.setdefault(badge(person.barcode), person)

joined, ssc_of = {}, {}
if Ssc is not None:
    for record in Ssc.with_context(active_test=False).search([]):
        person = record.hr_employee_id or by_badge.get(badge(record.attendance_code))
        if not person:
            continue
        ssc_of.setdefault(person.id, record)
        if record.joining_date:
            joined.setdefault(person.id, record.joining_date)

# ---------------------------------------------------------------------------
title("1. contracts with no start date")

missing = Employee.with_context(active_test=True).search([]).filtered(
    lambda e: e.current_version_id and not e.current_version_id.contract_date_start)
print(f"  {len(missing)} active employee(s)")

planned, stuck = [], []
for person in missing:
    from_ssc = joined.get(person.id)

    first_punch = Attendance.search([('employee_id', '=', person.id)],
                                    order='check_in asc', limit=1)
    punched = first_punch.check_in.date() if first_punch else None

    paid = None
    record = ssc_of.get(person.id)
    if Slip is not None and record:
        first_slip = Slip.search([('employee_id', '=', record.id),
                                  ('from_date', '!=', False)],
                                 order='from_date asc', limit=1)
        paid = first_slip.from_date if first_slip else None

    # A contract cannot begin after today. One of these joining dates reads
    # 2032, and writing it would put every month outside the contract - the
    # same fault, arrived at from the other side.
    if from_ssc and from_ssc <= today:
        start, source = from_ssc, 'joining date'
    else:
        earliest = min([d for d in (punched, paid) if d and d <= today], default=None)
        if not earliest:
            stuck.append((person, record, from_ssc))
            continue
        start = earliest
        source = 'first punch' if earliest == punched else 'first payslip'
        if from_ssc:
            source += f' (joining date {from_ssc} is in the future)'
    planned.append((person, start, source, from_ssc, punched, paid))

# ---------------------------------------------------------------------------
title("2. the date each contract will get")

print(f"  {'employee':<34} {'joining':<12} {'1st punch':<12} {'1st slip':<12} "
      f"{'start':<12} from")
for person, start, source, from_ssc, punched, paid in sorted(planned,
                                                             key=lambda r: r[1]):
    print(f"  {person.name[:34]:<34} {str(from_ssc or '-'):<12} "
          f"{str(punched or '-'):<12} {str(paid or '-'):<12} "
          f"{str(start):<12} {source}")

from collections import Counter
print()
for source, number in Counter(row[2] for row in planned).most_common():
    print(f"  {source:<16} {number}")

# ---------------------------------------------------------------------------
if stuck:
    title("3. nothing to derive a date from - left alone")
    for person, record, from_ssc in sorted(stuck, key=lambda r: r[0].name):
        note = f"  joining date {from_ssc} is in the future" if from_ssc else ""
        print(f"  {person.name[:36]:<36} badge={(person.barcode or '-'):<10} "
              f"company={person.company_id.name[:26]}{note}")

# ---------------------------------------------------------------------------
title("4. what will be written")
print(f"  contract_date_start on {len(planned)} contract(s)")
print("  nothing else - the end date, open or from the permit list, is left as it is")

# ---------------------------------------------------------------------------
if APPLY:
    done, failed = 0, []
    for person, start, _source, _j, _p, _q in planned:
        try:
            with env.cr.savepoint():
                person.current_version_id.contract_date_start = start
            done += 1
        except Exception as error:
            failed.append((person.name, str(error).splitlines()[0][:70]))
    env.cr.commit()

    title("APPLIED")
    print(f"  written {done} | refused {len(failed)}")
    for name, message in failed:
        print(f"      {name[:32]:<32} {message}")
    left = Employee.with_context(active_test=True).search([]).filtered(
        lambda e: e.current_version_id and not e.current_version_id.contract_date_start)
    print()
    print(f"  active contracts still without a start date: {len(left)}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
