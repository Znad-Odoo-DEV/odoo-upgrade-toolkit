"""Rebuild the overtime lines, a month at a time, from the rules as they stand.

    odoo-bin shell -d <database> --no-http < tools/rebuild_overtime.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/rebuild_overtime.py
    SSC_FROM=2026-05 SSC_TO=2026-08 SSC_APPLY=1 odoo-bin shell -d ... < ...

Kasem Abdulaziz Alhaj Ahmad worked ten hours and twenty three minutes on the
25th of August and the record says he did eleven hours and twenty three minutes
of overtime - more overtime than he worked hours, and exactly the raw span from
clock-in to clock-out with the lunch hour put back in. Every day of his month
reads the same way. His August overtime totals two hundred and twenty six hours
against a true twenty eight.

The rule is right and the contract is right. Asked today, the calendar answers
that the 25th of August expects eight hours, which is what it should say. The
stored figures were computed at some earlier point, when something was not
right, and nothing has recomputed them since - `overtime_hours` only re-sums
the lines that already exist, so it cannot notice they are wrong.

`_update_overtime` deletes the lines in the period and builds them again from
the rules, the calendars and the contracts as they are now. It keeps anybody's
manual correction: a line whose duration was edited by hand comes back marked
for approval rather than being silently replaced by the computed figure.

WHY THIS MATTERS BEFORE ANYTHING ELSE IS MEASURED

The July payslip comparison found several labourers whose overtime in Odoo came
out higher than what ssc_payroll paid, and it was put down to the two systems
measuring differently. They are these people. Anything compared against these
figures is compared against a number that was never true.

A MONTH AT A TIME

Each month deletes and rebuilds the lines for three hundred people, and the
totals before and after are printed for each one, so a month that moves the
wrong way can be seen before the next one runs. From May 2026, which is where
the work entries begin - anything earlier reaches no payslip.
"""
import os
from calendar import monthrange
from datetime import date

APPLY = os.environ.get('SSC_APPLY') == '1'
FROM = os.environ.get('SSC_FROM') or '2026-05'
TO = os.environ.get('SSC_TO') or date.today().strftime('%Y-%m')

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

Attendance = env['hr.attendance'].sudo()
Line = env['hr.attendance.overtime.line'].sudo()


def title(text):
    print()
    print("=" * 92)
    print(text)
    print("=" * 92)


def months(first, last):
    year, month = (int(part) for part in first.split('-'))
    end_year, end_month = (int(part) for part in last.split('-'))
    while (year, month) <= (end_year, end_month):
        yield date(year, month, 1), date(year, month, monthrange(year, month)[1])
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


title(f"rebuilding overtime from {FROM} to {TO}")
print(f"  {'month':<10} {'people':>7} {'days':>7} {'before':>12} {'after':>12} {'change':>12}")

grand_before = grand_after = 0.0
for start, end in months(FROM, TO):
    domain = [('date', '>=', start), ('date', '<=', end)]
    rows = Attendance.search(domain)
    if not rows:
        print(f"  {start:%Y-%m}    no attendance")
        continue

    before = sum(rows.mapped('overtime_hours'))
    people = len(rows.mapped('employee_id'))
    days = len(set(rows.mapped('date')))

    if APPLY:
        Attendance._update_overtime(domain)
        env.cr.commit()
        env.invalidate_all()
        rows = Attendance.search(domain)
        after = sum(rows.mapped('overtime_hours'))
    else:
        # Without writing, the honest thing to report is what is stored now and
        # how many lines would be thrown away. What replaces them cannot be
        # known without doing it.
        after = float('nan')

    grand_before += before
    grand_after += 0.0 if after != after else after
    shown_after = '-' if after != after else f"{after:,.1f}"
    change = '-' if after != after else f"{after - before:,.1f}"
    print(f"  {start:%Y-%m}    {people:>7} {days:>7} {before:>12,.1f} "
          f"{shown_after:>12} {change:>12}")

print()
if APPLY:
    print(f"  {'total':<10} {'':>7} {'':>7} {grand_before:>12,.1f} "
          f"{grand_after:>12,.1f} {grand_after - grand_before:>12,.1f}")
    title("APPLIED - each month committed as it finished")
else:
    lines = Line.search([('date', '>=', date(*(int(p) for p in FROM.split('-')), 1))])
    print(f"  overtime hours stored today across the period : {grand_before:,.1f}")
    print(f"  overtime lines that would be deleted and rebuilt: {len(lines):,}")
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to rebuild.")
