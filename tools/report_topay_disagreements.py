"""The 131 salaries the two Studio payroll models disagree about.

    odoo-bin shell --no-http --shell-interface=python < tools/report_topay_disagreements.py

Reads only. Our payslips match x_all_payslips exactly - four figures, 4,565
records, no difference at all - so what this reports is not a migration fault.
It is x_to_pay and x_all_payslips disagreeing with each other about the salary
of the same employee in the same month, and our side inheriting one of the two
answers because that is the one it was told to mirror.

To Pay is higher every time. That is the shape of a figure that was revised
after the payslip was written, or of a payslip that was written from an older
rate - and which of those it is decides whether 131 people were underpaid on our
records or the old list simply never caught up.

Each one is printed with its parts on both sides: the basic, the allowances, the
overtime and the adjustment, so the difference can be traced to the line it
comes from rather than argued about as a total.

Nothing here can answer which figure was actually paid. The bank can. This is
the list to take to it.
"""
SOURCE = 'x_to_pay'
EMPLOYEE = 'x_studio_for_employee'
MONTH = 'x_studio_month'
YEAR = 'x_studio_year'
TOLERANCE = 0.01

# our field -> theirs, for the parts as well as the totals
PARTS = [
    ('basic', 'basic_salary', 'x_studio_total_basic_salary_this_month'),
    ('housing', 'house_allowance', 'x_studio_total_housing_allowance_this_month'),
    ('transport', 'transport_allowance', 'x_studio_total_travelling_allowance_this_month'),
    ('other', 'other_allowance', 'x_studio_total_other_allowance_this_month'),
    ('overtime', 'overtime_salary', 'x_studio_total_overtime_salary_of_this_month'),
    ('adjustment', 'salary_adjustment', 'x_studio_salary_adjustment'),
    ('TOTAL', 'total_salary', 'x_studio_total_salary_of_this_month'),
]

cr = env.cr                                                      # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821
Slip = env['ssc.payslip'].sudo().with_context(active_test=False)  # noqa: F821
Employee = env['hr.employee'].sudo()                             # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def _get(record, name):
    if not record or name not in record._fields:
        return 0.0
    return record[name] or 0.0


ours, theirs = {}, {}
for slip in Slip.search([]):
    hr = slip.employee_id.hr_employee_id if slip.employee_id else False
    ours.setdefault((hr.id if hr else 0, str(slip.month or ''),
                     str(slip.year or '')), []).append(slip)
for record in Source.search([]):
    employee = record[EMPLOYEE]
    theirs.setdefault((employee.id if employee else 0,
                       str(record[MONTH] or ''),
                       str(record[YEAR] or '')), []).append(record)

both = set(ours) & set(theirs)
off = []
for key in both:
    mine = sum(s.total_salary or 0.0 for s in ours[key])
    yours = sum(_get(r, 'x_studio_total_salary_of_this_month') for r in theirs[key])
    if abs(mine - yours) > TOLERANCE:
        off.append((key, mine, yours))
off.sort(key=lambda d: d[1] - d[2])


title("1. the size of it")

print("  %s payslip(s) on both sides" % len(both))
print("  %s disagree on the total salary" % len(off))
print("  %s in favour of To Pay" % round(sum(y - m for _k, m, y in off), 2))

by_month = {}
for (employee_id, month, year), mine, yours in off:
    entry = by_month.setdefault('%s %s' % (month, year), [0, 0.0])
    entry[0] += 1
    entry[1] += yours - mine
print("\n  by month:")
for month, (count, amount) in sorted(by_month.items()):
    print("      %-12s %4s payslip(s)   %s" % (month, count, round(amount, 2)))

people = {k[0] for k, _m, _y in off}
print("\n  %s employee(s) involved" % len(people))
repeat = {}
for (employee_id, _m, _y), _mine, _yours in off:
    repeat[employee_id] = repeat.get(employee_id, 0) + 1
many = sorted([(c, e) for e, c in repeat.items()], reverse=True)[:8]
print("  the ones it happens to most:")
for count, employee_id in many:
    print("      %-36s %s month(s)" % (Employee.browse(employee_id).display_name[:36], count))


title("2. each one, part by part")

for (employee_id, month, year), mine, yours in off:
    who = Employee.browse(employee_id).display_name if employee_id else '-'
    print("\n  %s   %s %s   difference %s"
          % (who[:44], month, year, round(yours - mine, 2)))
    slips = ours[(employee_id, month, year)]
    records = theirs[(employee_id, month, year)]
    for label, ours_field, their_field in PARTS:
        a = sum(s[ours_field] or 0.0 for s in slips)
        b = sum(_get(r, their_field) for r in records)
        mark = '  <--' if abs(a - b) > TOLERANCE else ''
        print("      %-12s ours %-12s topay %-12s %s"
              % (label, round(a, 2), round(b, 2), mark))


title("what this list is for")
print("""  Our payslips match x_all_payslips exactly. These are the rows where the two
  Studio models disagree with each other, and our side inherited the lower of
  the two answers because x_all_payslips is the one it mirrors.

  Which figure left the bank is not a question this database can answer. Until
  it is answered, x_to_pay is the only record that the disagreement ever
  existed - so it is the one thing here that must not be deleted yet.""")
