"""Price a day of absence at a thirtieth of the month, not a twenty sixth.

    odoo-bin shell -d <database> --no-http < tools/set_monthly_proration_rules.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/set_monthly_proration_rules.py

The localisation prorates by hours: wage times hours worked over hours
scheduled. On a six day week that makes an absent day cost a twenty sixth of
the month. This company has always charged a thirtieth - or a thirty first, or
a twenty eighth, whatever the month happens to hold - and so does the rest of
the country, and so does the Out of Contract rule three lines further down the
same structure, which divides by the days in the month and gets it right.

The difference is nineteen percent of a day's pay every time somebody is
absent, always against the employee.

    salary 1600, one day absent
        by scheduled hours   1600 / 26 = 61.54
        by days in the month 1600 / 31 = 51.61

Proved rather than argued: a payslip computed for July 2026 differed from what
was paid on exactly three employees out of forty, and each difference was the
absent days times gross over thirty one, to the fils.

WHAT DOES NOT CHANGE

Where the absence comes from. The punch stays the only evidence that somebody
worked - no punch, no day, and nobody has to remember to record an absence.
This changes what a missing day costs, not how a missing day is found.

A Friday costs nothing, because it was never a scheduled day. A day of paid
leave costs nothing, because it arrives as its own work entry and counts as
covered. Overtime is excluded from the count entirely: it is paid by its own
rules and an hour of it is not a day of attendance.

THE FIVE RULES

BASIC and the three allowances all take the same ratio, because a salary split
across four lines that prorate differently is not one salary. AEUNPAID moves
to the same divisor for the same reason - it was dividing by a figure derived
from the worked day lines, which is neither the scheduled days nor the days in
the month.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'

# Discovered, not listed. The tuple used to be (19..25) and a structure
# created afterwards - MALAK AL REEM Staff Pay, id 26 - was silently left on
# whatever its rules happened to say. A list of ids is a list that goes stale
# the day somebody adds a company.
SUFFIXES = ('Labour Pay', 'Staff Pay')

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

Rule = env['hr.salary.rule'].sudo()

STRUCTURES = tuple(
    structure.id
    for structure in env['hr.payroll.structure'].sudo().search([])
    if (structure.name or '').endswith(SUFFIXES)
)
print("structures in scope: %s" % (
    ", ".join("[%s] %s" % (
        s_.id, s_.name) for s_ in env['hr.payroll.structure'].sudo().browse(
            STRUCTURES)) or "(none)"))


def title(text):
    print()
    print("=" * 96)
    print(text)
    print("=" * 96)


# The shared preamble. Every one of the four earning rules asks the same
# question - what fraction of the month did this person actually cover - and
# they have to agree on the answer.
RATIO = """
# The period is what was worked; the MONTH is what a day is worth. A sheet
# running 1 to 25 is twenty five days of a thirty one day month, and dividing
# by its own length pays a whole month for five sixths of one - which is what
# it did while days_in_month held the period.
#
# Both halves of the fraction had to move. Keeping the old numerator against a
# month divisor gives (31 - 0) / 31 = 1, the same full salary by another road.
period_days = (payslip.date_to - payslip.date_from).days + 1
month_start = payslip.date_to.replace(day=1)
days_in_month = ((month_start + relativedelta(months=1)) - month_start).days
hours_per_day = version.resource_calendar_id.hours_per_day or 8.0
scheduled = payslip._get_l10n_ae_total_work_hours() / hours_per_day
covered = sum(l.number_of_days for l in payslip.worked_days_line_ids
              if not (l.work_entry_type_id.code or '').startswith('SSC_OT'))
absent = max(0.0, scheduled - covered)
ratio = (period_days - absent) / days_in_month if days_in_month else 0.0
"""

UNPAID = """
# An unpaid day costs a day of the month, not a day of the period - the same
# divisor the four rules above use, or one salary is priced two ways.
month_start = payslip.date_to.replace(day=1)
days_in_month = ((month_start + relativedelta(months=1)) - month_start).days
gross = (version.wage + version.l10n_ae_housing_allowance
         + version.l10n_ae_transportation_allowance
         + version.l10n_ae_other_allowances)
result = -worked_days['LEAVE90'].number_of_days * gross / days_in_month if days_in_month else 0.0
"""

PLAN = {
    'BASIC': RATIO + "result = version.wage * ratio\n",
    'HOUALLOW': RATIO + "result = version.l10n_ae_housing_allowance * ratio\n",
    'TRAALLOW': RATIO + "result = version.l10n_ae_transportation_allowance * ratio\n",
    'OTALLOW': RATIO + "result = version.l10n_ae_other_allowances * ratio\n",
    'AEUNPAID': UNPAID,
}

# ---------------------------------------------------------------------------
title("1. what each rule says today, on one structure")

for code in PLAN:
    rule = Rule.search([('struct_id', '=', 19), ('code', '=', code),
                        ('active', '=', True)], limit=1)
    if not rule:
        print(f"  {code:<10} MISSING on structure 19")
        continue
    body = (rule.amount_python_compute or '').strip().splitlines()
    print(f"  {code}")
    for line in body:
        print(f"      {line[:104]}")
    print()

# ---------------------------------------------------------------------------
title("2. what it will say instead")

for code, body in PLAN.items():
    print(f"  {code}")
    for line in body.strip().splitlines():
        print(f"      {line}")
    print()

# ---------------------------------------------------------------------------
title("3. how many rules")

targets = Rule.search([('struct_id', 'in', STRUCTURES),
                       ('code', 'in', list(PLAN)), ('active', '=', True)])
by_code = {}
for rule in targets:
    by_code.setdefault(rule.code, []).append(rule)
for code in PLAN:
    found = by_code.get(code, [])
    print(f"  {code:<10} {len(found)} rule(s) across {len(STRUCTURES)} structures")
missing = [code for code in PLAN if len(by_code.get(code, [])) != len(STRUCTURES)]
if missing:
    print()
    print(f"  {missing} is not on every structure - nothing is written")
    raise SystemExit

# ---------------------------------------------------------------------------
if APPLY:
    for rule in targets:
        rule.write({'amount_python_compute': PLAN[rule.code]})
    env.cr.commit()
    title("APPLIED")
    print(f"  rewrote {len(targets)} rule(s)")
    print()
    print("  Now re-run tools/compare_payslip_to_ssc.py without SSC_CALENDAR and")
    print("  the three employees who were absent should come out exact. The rest")
    print("  will still be short by their missing punches, which is the point.")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
