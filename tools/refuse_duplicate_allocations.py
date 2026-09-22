"""Where one year was granted twice, refuse the copy that is not the entitlement.

    odoo-bin shell -d <database> --no-http < tools/refuse_duplicate_allocations.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/refuse_duplicate_allocations.py

Two employees ended up holding sixty days for a single year. Somebody had
already granted them thirty by hand in the Time Off screen - one opening in
November 2025 with no end, one boxed into a month of September 2026 - and the
entitlement run then granted the year properly, because a balance opening in
November is not a grant for the year and the run was right to say so.

Both are real records and both are thirty days, so the balance is double what
the law gives and the liability figure is wrong by that much.

WHICH ONE GOES

The one that is not the yearly entitlement. Every allocation this project
creates is named 'Annual leave entitlement <year>' and opens on the first of
January, or the joining date when that falls later; anything else in the same
year is a hand-made record. The hand-made one is refused, because the
entitlement is the one that says something general and repeatable, and its
window is the wider of the two - a balance running from January with no end
covers every day the boxed one covered.

Refused, not deleted. The balance leaves the calculation, the record stays and
says it was refused, and somebody who disagrees can set it back.

If a year holds two allocations and neither is an entitlement, or both are,
nothing is touched and the pair is printed. That is not a duplicate this file
knows how to read.
"""
import os
from collections import defaultdict

APPLY = os.environ.get('SSC_APPLY') == '1'

TYPE_NAME = 'Annual Leave'
ENTITLEMENT = 'Annual leave entitlement'

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
    mail_notify_force_send=False,
))

Allocation = env['hr.leave.allocation'].sudo()
LeaveType = env['hr.leave.type'].sudo()


def title(text):
    print()
    print("=" * 90)
    print(text)
    print("=" * 90)


annual = LeaveType.search([('name', '=', TYPE_NAME), ('active', '=', True)], limit=1)
if not annual:
    print(f"leave type {TYPE_NAME!r} does not exist - stopping")
    raise SystemExit

groups = defaultdict(list)
for allocation in Allocation.search([('holiday_status_id', '=', annual.id),
                                     ('state', '=', 'validate')]):
    if allocation.date_from:
        groups[(allocation.employee_id, allocation.date_from.year)].append(allocation)

doubled = {key: found for key, found in groups.items() if len(found) > 1}

title("years granted more than once")
print(f"  {len(doubled)} employee-year(s)")

to_refuse, unreadable = [], []
for (employee, year), found in sorted(doubled.items(), key=lambda x: x[0][0].name):
    entitlements = [a for a in found if (a.name or '').startswith(ENTITLEMENT)]
    others = [a for a in found if a not in entitlements]
    print()
    print(f"  {employee.name}   {year}   {sum(f.number_of_days for f in found):.2f} day(s) in total")
    for allocation in sorted(found, key=lambda a: a.date_from):
        keep = allocation in entitlements
        print(f"      {'KEEP   ' if keep else 'REFUSE '} id={allocation.id:<6} "
              f"{allocation.date_from} .. {str(allocation.date_to or 'open'):<10}  "
              f"{allocation.number_of_days:>6.2f}d  created {str(allocation.create_date)[:10]}  "
              f"{allocation.name or ''}")
    if len(entitlements) == 1 and others:
        to_refuse.extend(others)
    else:
        unreadable.append((employee, year, found))

if unreadable:
    title("left alone - not a shape this file can read")
    for employee, year, found in unreadable:
        entitlements = sum(1 for a in found if (a.name or '').startswith(ENTITLEMENT))
        print(f"  {employee.name[:36]:<36} {year}   {len(found)} allocation(s), "
              f"{entitlements} of them an entitlement")
    print()
    print("  A year holding two entitlements, or none, is not a duplicate this")
    print("  file knows how to settle. A person should look.")

title("what changes")
print(f"  {len(to_refuse)} allocation(s) to refuse")
print(f"  {sum(a.number_of_days for a in to_refuse):.2f} day(s) leaving the balance")

if APPLY:
    done, failed = 0, []
    for allocation in to_refuse:
        try:
            with env.cr.savepoint():
                if hasattr(allocation, 'action_refuse'):
                    allocation.action_refuse()
                else:
                    allocation.write({'state': 'refuse'})
            done += 1
        except Exception as error:
            failed.append((allocation.id, str(error).splitlines()[0][:74]))
    env.cr.commit()
    title("APPLIED")
    print(f"  refused {done} | failed {len(failed)}")
    for identifier, message in failed:
        print(f"      id={identifier}  {message}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to refuse.")
