"""One employee, one month, both payslips side by side.

    SSC_NAME="Ahmad Chiekh Youssef" SSC_MONTH=2026-07 \
        odoo-bin shell -d <database> --no-http < tools/compare_one_employee.py

The sample comparison answers how far off the payroll is. This answers why, for
one person, which is the only way to settle an argument about a number. It
prints the contract the engine reads, every work entry it saw, every line it
produced, and beside them the payslip that was actually paid, down to the
individual advances and fines that make up the adjustment.

A payslip is created so the engine has something to compute, and the
transaction is rolled back. Nothing survives the run.
"""
import os
from calendar import monthrange
from datetime import date

NAME = os.environ.get('SSC_NAME') or ''
MONTH = os.environ.get('SSC_MONTH')

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

Employee = env['hr.employee'].sudo()
# The payslip must compute in a context where archived records are archived.
# The env above runs with active_test=False so that cancelled employees and old
# records can be read, and a payslip computed under it picks up every retired
# salary rule as well - End of Service Provision came back from the dead on
# four separate reports before anyone noticed the measurement was doing it.
Slip = env['hr.payslip'].sudo().with_context(active_test=True)
Ssc = env['ssc.payslip'].sudo() if 'ssc.payslip' in env else None


def title(text):
    print()
    print("=" * 92)
    print(text)
    print("=" * 92)


def money(label, value, width=34):
    print(f"  {label:<{width}} {value:>14,.2f}")


if not NAME:
    print('pass SSC_NAME="employee name"')
    raise SystemExit

people = Employee.search([('name', 'ilike', NAME)])
if not people:
    print(f"no employee matching {NAME!r}")
    raise SystemExit
if len(people) > 1:
    print(f"{len(people)} employees match {NAME!r} - be more specific:")
    for person in people:
        print(f"    id={person.id:<6} active={person.active} "
              f"badge={person.barcode or '-':<10} {person.name}")
    raise SystemExit
employee = people

if MONTH:
    year, month = (int(part) for part in MONTH.split('-'))
else:
    latest = None
    if Ssc is not None:
        for candidate in Ssc.search([('from_date', '!=', False)],
                                    order='from_date desc'):
            if candidate.hr_employee_id == employee:
                latest = candidate
                break
    if not latest or not latest.from_date:
        print("no payslip to take a month from - pass SSC_MONTH=YYYY-MM")
        raise SystemExit
    year, month = latest.from_date.year, latest.from_date.month
start = date(year, month, 1)
end = date(year, month, monthrange(year, month)[1])

# ---------------------------------------------------------------------------
title(f"{employee.name}   {start} .. {end}")

version = employee.current_version_id
print(f"  contract        {version.name or '-'}")
print(f"  company         {employee.company_id.name}")
print(f"  structure type  {version.structure_type_id.name or '-'}")
print(f"  work entries    {version.work_entry_source}")
print(f"  overtime rules  {version.ruleset_id.name or 'none'}")
print(f"  calendar        {version.resource_calendar_id.name or '-'}")
print(f"  contract dates  {version.contract_date_start} .. "
      f"{version.contract_date_end or 'open'}")
print()
money("wage (basic)", version.wage)
money("housing allowance", version.l10n_ae_housing_allowance)
money("transportation allowance", version.l10n_ae_transportation_allowance)
money("other allowances", version.l10n_ae_other_allowances)
money("total on the contract", version.l10n_ae_total_salary)

# ---------------------------------------------------------------------------
title("what the engine computes")

slip = Slip.create({
    'name': f'single comparison {start}',
    'employee_id': employee.id,
    'date_from': start,
    'date_to': end,
})
slip.compute_sheet()

print("  work entries it saw")
if not slip.worked_days_line_ids:
    print("      none at all")
for line in slip.worked_days_line_ids.sorted('code'):
    print(f"      {line.code:<14} {line.number_of_days:>7.2f} day(s) "
          f"{line.number_of_hours:>9.2f} hour(s)  paid={line.is_paid}")
print()
print("  lines")
for line in slip.line_ids.sorted('sequence'):
    if not line.total:
        continue
    print(f"      {line.code:<12} {line.name[:34]:<34} "
          f"qty {line.quantity:>8.2f}  amount {line.amount:>11.2f}  "
          f"total {line.total:>12.2f}")

lines = {line.code: line.total for line in slip.line_ids}
odoo_salary = sum(lines.get(code, 0.0)
                  for code in ('BASIC', 'HOUALLOW', 'TRAALLOW', 'OTALLOW'))
odoo_ot = lines.get('OT_REG', 0.0) + lines.get('OT_OFF', 0.0)

# ---------------------------------------------------------------------------
title("what ssc_payroll paid")

# hr_employee_id is a related field and is not stored, so it cannot be
# searched on - the month is fetched and the link read afterwards.
old = None
# Not `if Ssc:` - an empty recordset is falsy and this one always is, so the
# whole lookup would be skipped and the report would say there was no payslip
# for a month that has one.
if Ssc is not None:
    for candidate in Ssc.search([('from_date', '>=', start),
                                 ('from_date', '<=', end)]):
        if candidate.hr_employee_id == employee:
            old = candidate
            break
if not old:
    print("  no ssc payslip for that month - nothing to compare against")
else:
    print(f"  days in month {old.days}      attended {old.total_attendance}")
    print()
    money("basic", old.basic_salary)
    money("house + transport + other",
          old.house_allowance + old.transport_allowance + old.other_allowance)
    money("gross", old.gross_salary)
    money("rate per day", old.rate_per_day)
    print()
    money("salary for the month", old.total_salary)
    print(f"  {'overtime regular':<34} {old.overtime_reg:>7.1f} h "
          f"x {old.ot_rate_regular:>6.4f} = {old.overtime_reg_amount:>11,.2f}")
    print(f"  {'overtime off days':<34} {old.overtime_off:>7.1f} h "
          f"x {old.ot_rate_off:>6.4f} = {old.overtime_off_amount:>11,.2f}")
    money("adjustments", old.salary_adjustment)
    money("net paid", old.net_amount)

    if old.attachment_ids:
        print()
        print("  what the adjustment is made of")
        for item in old.attachment_ids:
            print(f"      {item.name[:52]:<52} {item.signed_value:>12,.2f}")

# ---------------------------------------------------------------------------
title("side by side")

if old:
    print(f"  {'':<28} {'ssc_payroll':>14} {'odoo':>14} {'gap':>14}")
    print(f"  {'salary for the month':<28} {old.total_salary:>14,.2f} "
          f"{odoo_salary:>14,.2f} {odoo_salary - old.total_salary:>14,.2f}")
    print(f"  {'overtime':<28} {old.overtime_salary:>14,.2f} "
          f"{odoo_ot:>14,.2f} {odoo_ot - old.overtime_salary:>14,.2f}")
    print(f"  {'adjustments':<28} {old.salary_adjustment:>14,.2f} "
          f"{0.0:>14,.2f} {-old.salary_adjustment:>14,.2f}")
    print(f"  {'':<28} {'':>14} {'':>14} {'':>14}")
    print(f"  {'net':<28} {old.net_amount:>14,.2f} "
          f"{lines.get('NET', 0.0):>14,.2f} "
          f"{lines.get('NET', 0.0) - old.net_amount:>14,.2f}")
    print()
    print("  The adjustment column is zero on the Odoo side for everybody:")
    print("  advances, fines and loans have not been brought across yet.")

env.cr.rollback()
title("ROLLED BACK - no payslip was kept")
