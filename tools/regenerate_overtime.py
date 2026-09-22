"""Recompute overtime for a period, instead of for all of history.

    # required: a period. Report only, writes nothing:
    SSC_FROM=2026-07-25 SSC_TO=2026-08-24 \
        odoo-bin shell -d <database> --no-http 2>/dev/null < tools/regenerate_overtime.py

    # same again, this time writing:
    SSC_FROM=2026-07-25 SSC_TO=2026-08-24 SSC_APPLY=1 odoo-bin shell ...

The Regenerate overtimes button on a ruleset has no period. It recomputes from
the earliest contract version - on this database, 2018 - so pressing it re-rates
years of history that nobody is going to pay, and buries the current cycle in a
number nobody can check.

The method behind the button takes a domain:

    def _update_overtime(self, attendance_domain=None):
        all_overtime_lines = self.env['hr.attendance.overtime.line'].search(attendance_domain)

so this passes one bounded by dates, and touches nothing outside them.

Scope is the employees whose contract sits on a ruleset matching SSC_RULESET
(default "Overtime") - the ones deliberately moved onto the new rules. Everybody
still on Legacy Rules is left exactly as they are.

There is no default period on purpose: a forgotten variable must not quietly
become "all of it".

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

APPLY = os.environ.get('SSC_APPLY') == '1'
DATE_FROM = (os.environ.get('SSC_FROM') or '').strip()
DATE_TO = (os.environ.get('SSC_TO') or '').strip()
WANTED = os.environ.get('SSC_RULESET') or 'Overtime'
ONLY_COMPANY = (os.environ.get('SSC_COMPANY') or '').strip().lower()

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92
NEVER = ('legacy', 'default')


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def summarise(lines):
    """Hours per rate, so a before and after can be compared at a glance."""
    per_rate = defaultdict(float)
    for line in lines:
        per_rate[round(line.amount_rate, 4)] += line.duration
    return per_rate


if not DATE_FROM or not DATE_TO:
    print("SSC_FROM and SSC_TO are required - both are dates, YYYY-MM-DD.\n")
    print("  SSC_FROM=2026-07-25 SSC_TO=2026-08-24 odoo-bin shell ... "
          "< tools/regenerate_overtime.py\n")
    print("No default period is offered: a forgotten variable must not quietly")
    print("become every year on the database.")
elif 'hr.attendance' not in env or 'hr.attendance.overtime.line' not in env:
    print("This database has no attendance overtime - nothing to recompute.")
else:
    Attendance = env['hr.attendance'].sudo()
    Line = env['hr.attendance.overtime.line'].sudo()
    Version = env['hr.version'].sudo()

    # --- whose overtime -------------------------------------------------------

    title("1. scope")

    print(f"  period: {DATE_FROM} .. {DATE_TO}")

    rulesets = env['hr.attendance.overtime.ruleset'].sudo().search([])
    chosen = rulesets.filtered(
        lambda r: WANTED.lower() in (r.name or '').lower()
        and not any(word in (r.name or '').lower() for word in NEVER))
    if ONLY_COMPANY:
        chosen = chosen.filtered(
            lambda r: ONLY_COMPANY in (r.company_id.name or '').lower())
    labels = [f"{r.name} ({r.company_id.name or 'all companies'})" for r in chosen]
    print(f"  rulesets in scope: {', '.join(labels) or '(none)'}")

    versions = Version.search([('ruleset_id', 'in', chosen.ids)]) if chosen \
        else Version.browse()
    employees = versions.employee_id
    print(f"  contracts on them: {len(versions)}  "
          f"covering {len(employees)} employee(s)")

    if not employees:
        print("\n  Nobody is on those rulesets yet - move contracts onto them first")
        print("  with tools/assign_overtime_ruleset.py.")

    # --- what is there now ----------------------------------------------------

    domain = [
        ('employee_id', 'in', employees.ids),
        ('date', '>=', DATE_FROM),
        ('date', '<=', DATE_TO),
    ]

    title("2. what this period holds today")

    attendances = Attendance.search(domain) if employees else Attendance.browse()
    before = Line.search(domain) if employees else Line.browse()
    print(f"  attendances in the period: {len(attendances)}")
    print(f"  overtime lines today:      {len(before)} "
          f"({sum(before.mapped('duration')):,.1f} h)")
    for rate, hours in sorted(summarise(before).items()):
        print(f"    at rate {rate:<6g} {hours:>10,.1f} h")
    outside = Line.search_count([('employee_id', 'in', employees.ids)]) - len(before) \
        if employees else 0
    print(f"  overtime lines OUTSIDE the period: {outside} - untouched by this run")

    # --- apply ----------------------------------------------------------------

    title("summary")

    if not employees:
        print("  nothing in scope")
    elif not attendances:
        print("  no attendance in this period, so there is nothing to recompute")
    else:
        print(f"  would delete and rebuild {len(before)} overtime line(s) from "
              f"{len(attendances)} attendance(s)")
        print("  strictly inside the period; every other line stays as it is")

    if not APPLY:
        env.cr.rollback()
        print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write.")
    elif not attendances:
        env.cr.rollback()
        print("\nnothing to do.")
    else:
        attendances._update_overtime(domain)
        env.cr.commit()
        after = Line.search(domain)
        print(f"\nwritten: {len(after)} overtime line(s) now cover the period "
              f"({sum(after.mapped('duration')):,.1f} h)")
        for rate, hours in sorted(summarise(after).items()):
            print(f"    at rate {rate:<6g} {hours:>10,.1f} h")
        print("\nCheck a payslip over the same period before validating anything.")
