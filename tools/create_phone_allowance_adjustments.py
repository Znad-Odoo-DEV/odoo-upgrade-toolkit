"""Turn the phone allowance columns into Salary Adjustment records.

    odoo-bin shell -d <database> --no-http < tools/create_phone_allowance_adjustments.py

Dry run by default. Prefix the command with APPLY=1 to write:

    APPLY=1 odoo-bin shell -d <database> --no-http < tools/create_phone_allowance_adjustments.py

The dry run is not a simulation: every record is really created inside a
savepoint, validated by Odoo, and rolled back. If a value is not acceptable it
fails here rather than on the day somebody presses Apply.

ssc.employee carried two columns for this - phone_bill_allowance saying whether,
agreed_monthly_allowance saying how much - and eight employees carry both. That
is exactly what one hr.salary.attachment says on its own, and it is native: it
appears on the employee, it shows what has been paid against it, and it stops
on a date instead of running until somebody remembers to untick a box. Ending
at 31 December 2026 was the instruction.

One record per employee rather than one covering all eight. The amounts differ
- six at 50, one at 100, one at 250 - the employees sit in two companies, and
company is required, so they could not share a record anyway. More to the
point, one each is one each: when a person leaves, their allowance closes
without touching anybody else's.

The type is created here rather than in the module's data. hr.payslip.input.type
belongs to enterprise hr_payroll, and putting a record for it in ssc_payroll
would make this module depend on enterprise and fail to install anywhere else.

NOTHING is removed. phone_bill_allowance and agreed_monthly_allowance stay
where they are, and ssc_payroll keeps generating its own attachment from them -
so until those columns go, the allowance exists twice. Create these on the same
day the columns are dropped, not before.
"""
import os
from datetime import date

APPLY = os.environ.get('APPLY') == '1'

# The instruction: run it to the end of the year and stop.
DATE_END = date(2026, 12, 31)
# Start on the first of the current month, so the adjustment lines up with a
# payroll period instead of beginning mid-cycle.
TODAY = date.today()
DATE_START = date(TODAY.year, TODAY.month, 1)

TYPE_NAME = 'Phone Bill Allowance'
TYPE_CODE = 'PHONEBILL'

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

Ssc = env['ssc.employee']
Adjustment = env.get('hr.salary.attachment')
InputType = env.get('hr.payslip.input.type')
if Adjustment is None or InputType is None:
    raise SystemExit("hr_payroll is not installed on this database.")

print("start %s   end %s   apply=%s" % (DATE_START, DATE_END, APPLY))

# ----------------------------------------------------------------------
# The type. Reused if somebody already made one; never duplicated.
# ----------------------------------------------------------------------
input_type = InputType.search([('code', '=', TYPE_CODE)], limit=1)
if input_type:
    print("input type: reusing %r [%s]" % (input_type.name, input_type.code))
else:
    print("input type: creating %r [%s]" % (TYPE_NAME, TYPE_CODE))

# ----------------------------------------------------------------------
# The people.
# ----------------------------------------------------------------------
owed = Ssc.search([('phone_bill_allowance', '=', True),
                   ('agreed_monthly_allowance', '>', 0)])
skipped = []
targets = []
for employee in owed:
    hr_employee = employee.hr_employee_id
    if not hr_employee:
        skipped.append("%s [%s] has no hr.employee"
                       % (employee.name, employee.employee_code or '-'))
        continue
    targets.append((employee, hr_employee))

# Anybody flagged without an amount, or paid without the flag, is not carried
# across silently - one would be an adjustment worth nothing and the other is
# money entered without the tick that pays it.
odd = Ssc.search(['|',
                  '&', ('phone_bill_allowance', '=', True),
                       ('agreed_monthly_allowance', '=', 0),
                  '&', ('phone_bill_allowance', '=', False),
                       ('agreed_monthly_allowance', '>', 0)])
for employee in odd:
    skipped.append("%s [%s] flag=%s amount=%s - inconsistent, left alone"
                   % (employee.name, employee.employee_code or '-',
                      employee.phone_bill_allowance,
                      employee.agreed_monthly_allowance))

print("\n%s employee(s) to give an adjustment, %s skipped\n"
      % (len(targets), len(skipped)))


def build(hr_employee, employee, type_id):
    months = ((DATE_END.year - DATE_START.year) * 12
              + DATE_END.month - DATE_START.month + 1)
    return {
        'employee_ids': [(6, 0, [hr_employee.id])],
        'other_input_type_id': type_id,
        'monthly_amount': employee.agreed_monthly_allowance,
        # What the whole run is worth, so the record can say how much of itself
        # is left rather than only when it stops.
        'total_amount': employee.agreed_monthly_allowance * months,
        'date_start': DATE_START,
        'date_end': DATE_END,
        'duration_type': 'limited',
        'description': 'Monthly phone bill allowance, carried over from the '
                       'SSC payroll employee record.',
        'company_id': employee.company_id.id,
    }


print("%-38s %-13s %-10s %-11s %s"
      % ("NAME", "BADGE", "MONTHLY", "TOTAL", "COMPANY"))
print("-" * 96)

created = 0
existing = 0
errors = []

# Every record is really created and really validated. Each one gets its own
# savepoint, because a create that raises aborts the transaction in Postgres
# and everything after it would fail for the wrong reason.
type_id = input_type.id if input_type else False
if not type_id:
    type_id = InputType.create({'name': TYPE_NAME, 'code': TYPE_CODE}).id

for employee, hr_employee in targets:
    already = Adjustment.search_count([
        ('employee_ids', 'in', hr_employee.id),
        ('other_input_type_id', '=', type_id),
        ('state', '=', 'open'),
    ])
    if already:
        existing += 1
        print("%-38s %-13s %-10s %-11s %s"
              % (employee.name[:38], employee.employee_code or '-',
                 '-', '-', 'already has one - skipped'))
        continue
    values = build(hr_employee, employee, type_id)
    try:
        with env.cr.savepoint():
            Adjustment.create(values)
    except Exception as exc:
        errors.append("%s: %s" % (employee.name, exc))
        continue
    created += 1
    print("%-38s %-13s %-10s %-11s %s"
          % (employee.name[:38], employee.employee_code or '-',
             values['monthly_amount'], values['total_amount'],
             (employee.company_id.name or '')[:30]))

print()
print("=" * 96)
print("%s adjustment(s) %s, %s employee(s) already had one."
      % (created, "created" if (APPLY and not errors) else "validated and rolled back",
         existing))

if skipped:
    print()
    print("Skipped (%s):" % len(skipped))
    for line in skipped:
        print("   ", line)

if errors:
    print()
    print("REFUSED by Odoo - nothing was written:")
    for line in errors:
        print("   ", line)

print()
print("REMEMBER: phone_bill_allowance and agreed_monthly_allowance still exist,")
print("and ssc_payroll still generates its own attachment from them. Until those")
print("columns are dropped the allowance is recorded twice.")

if APPLY and not errors:
    env.cr.commit()
    print("\nCommitted.")
else:
    env.cr.rollback()
    print("\nDRY RUN - nothing was kept. Re-run with APPLY=1 to apply."
          if not APPLY else "\nRolled back because of the errors above.")
