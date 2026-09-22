"""Which employees are staff, according to each of the three flags that claim to say.

    odoo-bin shell -d <database> --no-http < tools/probe_staff_flags.py

Read only. Nothing is written, ever.

ssc.employee carries three flags that all sound like the same fact and are not:

  is_engineer_office  36   what the code actually uses - twelve record rules,
                           the staff attendance routing, the labour sheet
                           exclusion, and the salary hiding all read this one.
  is_staff            56   mirrored from Studio's x_studio_staff and read by
                           almost nothing on the employee itself.
  overtime_eligible  405   whether overtime is paid at all.

They are being collapsed into one field, and staff will mean "no overtime". So
the question is which set survives - and the twenty people between 36 and 56
are twenty people who either gain overtime they should not have or lose
overtime they should. Print the cross-tab and name them, one by one, rather
than pick a set and find out at the next payroll run.
"""
from collections import Counter

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

Ssc = env['ssc.employee']
Payslip = env['ssc.payslip']


def title(text):
    print()
    print("=" * 104)
    print(text)
    print("=" * 104)


employees = Ssc.search([])
print("%s ssc.employee record(s)" % len(employees))

# ----------------------------------------------------------------------
title("1. THE CROSS-TAB")
# ----------------------------------------------------------------------
combos = Counter()
for emp in employees:
    combos[(bool(emp.is_engineer_office), bool(emp.is_staff),
            bool(emp.overtime_eligible))] += 1

print("%-14s %-10s %-12s %s" % ("engineer/office", "is_staff", "ot_eligible", "count"))
print("-" * 60)
for (eng, staff, ot), count in sorted(combos.items(), key=lambda kv: -kv[1]):
    mark = ""
    # The rows that contradict "staff means no overtime".
    if staff and ot:
        mark = "  <-- staff WITH overtime"
    elif not staff and not ot:
        mark = "  <-- labour WITHOUT overtime"
    print("%-14s %-10s %-12s %s%s" % (eng, staff, ot, count, mark))

# ----------------------------------------------------------------------
title("2. THE TWENTY IN BETWEEN - is_staff BUT NOT engineer/office")
# ----------------------------------------------------------------------
between = employees.filtered(lambda e: e.is_staff and not e.is_engineer_office)
print("%s employee(s). Under is_engineer_office they are LABOUR and get "
      "overtime;\nunder is_staff they are STAFF and do not.\n" % len(between))
print("%-40s %-14s %-8s %-9s %s"
      % ("NAME", "BADGE", "OT elig", "OT rate", "COMPANY"))
for emp in between:
    print("%-40s %-14s %-8s %-9s %s"
          % (emp.name[:40], emp.employee_code or '-',
             'yes' if emp.overtime_eligible else 'no',
             emp.ot_rate_regular or 0, emp.company_id.name[:26]))

other_way = employees.filtered(lambda e: e.is_engineer_office and not e.is_staff)
print()
print("And the other way - engineer/office but NOT is_staff: %s" % len(other_way))
for emp in other_way:
    print("%-40s %-14s %-8s %-9s %s"
          % (emp.name[:40], emp.employee_code or '-',
             'yes' if emp.overtime_eligible else 'no',
             emp.ot_rate_regular or 0, emp.company_id.name[:26]))

# ----------------------------------------------------------------------
title("3. WHAT THE PAYSLIPS SAY - who was ACTUALLY paid overtime")
# ----------------------------------------------------------------------
# The flags are what somebody ticked. This is what was paid, which is the only
# evidence of how the business actually treats each person.
recent = Payslip.search([('overtime_salary', '>', 0)], order='id desc', limit=4000)
paid_ot = recent.mapped('employee_id')
print("%s payslip(s) with overtime, covering %s employee(s)"
      % (len(recent), len(paid_ot)))

staff_paid_ot = paid_ot.filtered('is_staff')
eng_paid_ot = paid_ot.filtered('is_engineer_office')
print()
print("of those, flagged is_staff           : %s" % len(staff_paid_ot))
print("of those, flagged is_engineer_office : %s" % len(eng_paid_ot))
print()
print("Every name below was PAID overtime while flagged as staff. If the flag")
print("is right, they were overpaid; if the payslip is right, the flag is wrong.")
for emp in staff_paid_ot:
    slips = recent.filtered(lambda s: s.employee_id == emp)
    print("    %-40s %-12s %s slip(s), %s AED"
          % (emp.name[:40], emp.employee_code or '-', len(slips),
             round(sum(slips.mapped('overtime_salary')), 2)))

# ----------------------------------------------------------------------
title("4. AND THE STAFF ATTENDANCE SIDE")
# ----------------------------------------------------------------------
# ssc_staff_attendance routes on is_engineer_office. Whoever is staff has to be
# on those sheets, or their attendance has no source at all.
StaffLine = env['ssc.staff.attendance.line']
on_staff_sheets = StaffLine.search([]).mapped('employee_id')
print("%s employee(s) appear on a staff attendance sheet" % len(on_staff_sheets))
print("of them flagged is_engineer_office : %s"
      % len(on_staff_sheets.filtered('is_engineer_office')))
print("of them flagged is_staff           : %s"
      % len(on_staff_sheets.filtered('is_staff')))
missing = on_staff_sheets.filtered(lambda e: not e.is_engineer_office and not e.is_staff)
print()
print("On a staff sheet but flagged NEITHER: %s" % len(missing))
for emp in missing[:15]:
    print("    %s [%s]" % (emp.name, emp.employee_code or '-'))

print("\nDone. Read only - nothing was written.")
