"""Compute a native payslip and hold it against the one ssc_payroll produced.

    odoo-bin shell -d <database> --no-http < tools/compare_payslip_to_ssc.py
    SSC_MONTH=2026-07 SSC_SAMPLE=8 odoo-bin shell -d <database> --no-http < ...

Read only in the sense that matters: a payslip is created so the engine has
something to compute, and the transaction is rolled back at the end. Nothing
survives this script.

WHY A COMPARISON AND NOT A TEST

There is no correct answer written down anywhere. ssc_payroll is what the
company paid, so ssc_payroll is the answer, and the only useful question is
where the two disagree and by how much. A rule that is wrong by four hundred
dirhams on one labourer is wrong by a hundred and eighty thousand across the
payroll, and averages hide that - so every employee in the sample is printed
with its own gap rather than a pass or a fail.

WHAT SHOULD MATCH ALREADY

Overtime. Both sides now compute basic over two hundred and forty, times 125%
on a working day and 150% on an off day, off the same attendance. If those two
columns disagree the overtime work is not finished.

WHAT SHOULD NOT MATCH YET

The basic salary. Odoo prorates by hours worked over hours scheduled;
ssc_payroll prorates by attended days over the days in the month, counts a
Friday as attended when the days either side of it were worked, and treats a
sick day as neither present nor absent. Nothing has been done about that yet,
so the gap this prints is the size of the job that is left.
"""
import os
from calendar import monthrange
from datetime import date

MONTH = os.environ.get('SSC_MONTH')
SAMPLE = int(os.environ.get('SSC_SAMPLE') or 6)

# Try the change without making it: switch the sampled contracts to take their
# base from the working schedule instead of the punches, rebuild their work
# entries, and see what the payslips come out at. The whole run is rolled back,
# so this answers the question without committing to the answer.
AS_CALENDAR = os.environ.get('SSC_CALENDAR') == '1'

# Staff and labour are paid on different structures and fail in different ways,
# so they are worth looking at apart. SSC_WHO=staff or SSC_WHO=labour narrows
# the sample; leaving it out takes both.
WHO = (os.environ.get('SSC_WHO') or '').strip().lower()

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

# The payslip must compute in a context where archived records are archived.
# The env above runs with active_test=False so that cancelled employees and old
# records can be read, and a payslip computed under it picks up every retired
# salary rule as well - End of Service Provision came back from the dead on
# four separate reports before anyone noticed the measurement was doing it.
Slip = env['hr.payslip'].sudo().with_context(active_test=True)
Ssc = env['ssc.payslip'].sudo() if 'ssc.payslip' in env else None


def title(text):
    print()
    print("=" * 104)
    print(text)
    print("=" * 104)


if Ssc is None:
    print("ssc.payslip is not on this database - nothing to compare against")
    raise SystemExit

# ---------------------------------------------------------------------------
title("1. which month")

if MONTH:
    year, month = (int(part) for part in MONTH.split('-'))
else:
    latest = Ssc.search([('from_date', '!=', False)], order='from_date desc', limit=1)
    if not latest:
        print("no ssc.payslip carries a date - pass SSC_MONTH=YYYY-MM")
        raise SystemExit
    year, month = latest.from_date.year, latest.from_date.month

start = date(year, month, 1)
end = date(year, month, monthrange(year, month)[1])
print(f"  {start} .. {end}")

source = Ssc.search([('from_date', '>=', start), ('from_date', '<=', end)])
print(f"  ssc payslips in that month : {len(source)}")
if not source:
    print("  nothing to compare - try another month")
    raise SystemExit

# The ones with overtime say the most, because overtime is the part that is
# supposed to agree already.
if WHO == 'staff':
    source = source.filtered(lambda s: s.is_staff)
elif WHO == 'labour':
    source = source.filtered(lambda s: not s.is_staff)
if WHO:
    print(f"  narrowed to {WHO} : {len(source)}")
if not source:
    print("  nothing left after that filter")
    raise SystemExit

# Overtime says the most where there is any; office staff have none, so they
# are ranked by what they are paid instead.
if WHO == 'staff':
    picked = source.sorted(lambda s: -s.gross_salary)[:SAMPLE]
else:
    picked = source.sorted(lambda s: -(s.overtime_reg + s.overtime_off))[:SAMPLE]

# ---------------------------------------------------------------------------
title("2. computing the native payslips")

people = picked.mapped('hr_employee_id')
if AS_CALENDAR:
    versions = people.mapped('current_version_id')
    was = {v.work_entry_source for v in versions}
    versions.write({'work_entry_source': 'calendar', 'overtime_from_attendance': True})
    print(f"  switched {len(versions)} contract(s) from {sorted(was)} to calendar")
    made = people.generate_work_entries(start, end, force=True)
    print(f"  rebuilt work entries: {len(made)} created")

rows = []
for old in picked:
    employee = old.hr_employee_id
    if not employee:
        print(f"  {old.employee_id.display_name[:40]:<40} no linked hr.employee - skipped")
        continue
    try:
        with env.cr.savepoint():
            slip = Slip.create({
                'name': f'comparison {start}',
                'employee_id': employee.id,
                'date_from': start,
                'date_to': end,
            })
            slip.compute_sheet()
            lines = {line.code: line.total for line in slip.line_ids}
            worked = {line.code: (line.number_of_days, line.number_of_hours)
                      for line in slip.worked_days_line_ids}
            rows.append((employee, old, slip, lines, worked))
    except Exception as error:
        print(f"  {employee.name[:40]:<40} refused: {str(error).splitlines()[0][:56]}")

print(f"  computed {len(rows)} of {len(picked)}")
if rows:
    first = rows[0]
    print(f"  structure chosen: {first[2].struct_id.name or 'NONE'}")
    print(f"  contract        : {first[2].version_id.name or 'NONE'}")

# ---------------------------------------------------------------------------
title("3. overtime - this is supposed to agree")

print(f"  {'employee':<28} {'reg hrs':>8} {'ssc':>10} {'odoo':>10} {'gap':>9}   "
      f"{'off hrs':>8} {'ssc':>10} {'odoo':>10} {'gap':>9}")
ot_gap = 0.0
for employee, old, slip, lines, worked in rows:
    reg = lines.get('OT_REG', 0.0)
    off = lines.get('OT_OFF', 0.0)
    gap_reg = reg - old.overtime_reg_amount
    gap_off = off - old.overtime_off_amount
    ot_gap += gap_reg + gap_off
    print(f"  {employee.name[:28]:<28} {old.overtime_reg:>8.1f} "
          f"{old.overtime_reg_amount:>10.2f} {reg:>10.2f} {gap_reg:>9.2f}   "
          f"{old.overtime_off:>8.1f} {old.overtime_off_amount:>10.2f} "
          f"{off:>10.2f} {gap_off:>9.2f}")
print(f"  total overtime gap across the sample: {ot_gap:>12.2f}")

# ---------------------------------------------------------------------------
title("4. salary for the month - basic plus the three allowances")

print(f"  {'employee':<28} {'days':>6} {'attended':>9} {'ssc pay':>11} "
      f"{'odoo pay':>11} {'gap':>10}  {'hours':>8}")
basic_gap = 0.0
for employee, old, slip, lines, worked in rows:
    odoo_basic = sum(lines.get(code, 0.0)
                     for code in ('BASIC', 'HOUALLOW', 'TRAALLOW', 'OTALLOW'))
    gap = odoo_basic - old.total_salary
    basic_gap += gap
    hours = sum(h for _d, h in worked.values())
    print(f"  {employee.name[:28]:<28} {old.days:>6} {old.total_attendance:>9.1f} "
          f"{old.total_salary:>11.2f} {odoo_basic:>11.2f} {gap:>10.2f}  {hours:>8.1f}")
print(f"  total basic gap across the sample:    {basic_gap:>12.2f}")

# ---------------------------------------------------------------------------
title("5. the sample added up")

ssc_pay = sum(o.total_salary for _e, o, _s, _l, _w in rows)
ssc_ot = sum(o.overtime_reg_amount + o.overtime_off_amount for _e, o, _s, _l, _w in rows)
odoo_pay = sum(sum(l.get(code, 0.0) for code in ('BASIC', 'HOUALLOW', 'TRAALLOW', 'OTALLOW'))
               for _e, _o, _s, l, _w in rows)
odoo_ot = sum(l.get('OT_REG', 0.0) + l.get('OT_OFF', 0.0) for _e, _o, _s, l, _w in rows)
print(f"  {'':<22} {'ssc_payroll':>14} {'odoo':>14} {'gap':>14}")
print(f"  {'salary for the month':<22} {ssc_pay:>14.2f} {odoo_pay:>14.2f} "
      f"{odoo_pay - ssc_pay:>14.2f}")
print(f"  {'overtime':<22} {ssc_ot:>14.2f} {odoo_ot:>14.2f} {odoo_ot - ssc_ot:>14.2f}")
print(f"  {'together':<22} {ssc_pay + ssc_ot:>14.2f} {odoo_pay + odoo_ot:>14.2f} "
      f"{(odoo_pay + odoo_ot) - (ssc_pay + ssc_ot):>14.2f}")
print()
exact = sum(1 for _e, o, _s, l, _w in rows
            if abs(sum(l.get(c, 0.0) for c in ('BASIC', 'HOUALLOW', 'TRAALLOW', 'OTALLOW'))
                   - o.total_salary) < 0.01)
print(f"  salary exact to the fils on {exact} of {len(rows)}")

# ---------------------------------------------------------------------------
title("6. one payslip in full, so the shape is visible")

if rows:
    employee, old, slip, lines, worked = rows[0]
    print(f"  {employee.name}   {start} .. {end}")
    print()
    print("  worked days the engine saw")
    for code, (days, hours) in sorted(worked.items()):
        print(f"      {code:<14} {days:>7.2f} day(s) {hours:>9.2f} hour(s)")
    print()
    print("  lines it produced")
    for line in slip.line_ids.sorted('sequence'):
        if line.total:
            print(f"      {line.code:<18} {line.name[:38]:<38} "
                  f"qty {line.quantity:>8.2f}  amount {line.amount:>10.2f}  "
                  f"total {line.total:>11.2f}")
    print()
    print("  what ssc_payroll paid")
    print(f"      basic {old.basic_salary:>10.2f}   allowances "
          f"{old.house_allowance + old.transport_allowance + old.other_allowance:>10.2f}"
          f"   gross {old.gross_salary:>10.2f}")
    print(f"      salary for the month {old.total_salary:>10.2f}   "
          f"overtime {old.overtime_salary:>10.2f}   "
          f"adjustments {old.salary_adjustment:>10.2f}")
    print(f"      net {old.net_amount:>10.2f}")

env.cr.rollback()
title("ROLLED BACK - no payslip was kept")
