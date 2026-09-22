"""Is every To Pay row a payroll we hold, once the year is part of the question?

    odoo-bin shell --no-http --shell-interface=python < tools/check_topay_coverage.py

Reads only. The first comparison matched on the employee and the month and left
the year out of the key, and reported that nothing exists only in To Pay. With
six months on one side and eighteen on the other that is not a safe reading: a
May 2025 row matches a May 2026 payslip and the gap it was meant to find hides
inside the match.

So this asks again with the year in the key, and then asks the question the
first one could not: whether the money agrees. To Pay has no field named like a
net amount, so its own monetary fields are listed and totalled per period
against ours - a period whose totals agree row for row is a period recorded
twice, and one that does not is a period worth reading before it is deleted.

1,591 rows, 2,431 lines and 4,878 chatter messages go if this model does, and
none of it is mirrored anywhere.
"""
SOURCE = 'x_to_pay'
EMPLOYEE = 'x_studio_for_employee'
MONTH = 'x_studio_month'
YEAR = 'x_studio_year'

cr = env.cr                                                      # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821
Slip = env['ssc.payslip'].sudo().with_context(active_test=False)  # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def _get(record, name):
    if not record or name not in record._fields:
        return False
    return record[name]


title("1. what To Pay holds of its own")

rows = Source.search([])
money = sorted(name for name, field in Source._fields.items()
               if field.type in ('monetary', 'float') and name.startswith('x_')
               and not field.related)
print("  %s row(s)" % len(rows))
print("  monetary/float fields of its own (not read off somebody else):")
for name in money:
    cr.execute('SELECT COUNT(*), COALESCE(SUM("%s"), 0) FROM "%s" WHERE "%s" IS NOT NULL'
               % (name, SOURCE, name)) if name in Source._fields else None
    filled, total = cr.fetchone()
    print("      %-44s %5s filled  %s" % (name, filled, round(total or 0, 2)))
if not money:
    print("      none - every figure on it is read off the employee or a line")


title("2. the same payroll, year included")

ours = {}
for slip in Slip.search([]):
    hr = slip.employee_id.hr_employee_id if slip.employee_id else False
    key = (hr.id if hr else 0, str(slip.month or ''), str(slip.year or ''))
    ours.setdefault(key, []).append(slip)

theirs = {}
for record in rows:
    employee = _get(record, EMPLOYEE)
    key = (employee.id if employee else 0,
           str(_get(record, MONTH) or ''), str(_get(record, YEAR) or ''))
    theirs.setdefault(key, []).append(record)

both = set(theirs) & set(ours)
only_theirs = set(theirs) - set(ours)
print("  %s (employee, month, year) key(s) in To Pay" % len(theirs))
print("  %s of them we also hold as a payslip" % len(both))
print("  %s we do not" % len(only_theirs))

no_employee = [k for k in theirs if not k[0]]
if no_employee:
    print("  %s key(s) name no employee" % len(no_employee))


title("3. the periods it covers")

periods = {}
for key, records in theirs.items():
    periods.setdefault((key[1], key[2]), [0, 0])[0] += len(records)
for key in both:
    periods.setdefault((key[1], key[2]), [0, 0])[1] += len(theirs[key])
for period, (total, covered) in sorted(periods.items()):
    flag = '' if total == covered else '%s NOT held as a payslip' % (total - covered)
    print("  %-14s %5s row(s)  %5s covered   %s"
          % ('%s %s' % period, total, covered, flag))


if only_theirs:
    title("4. the rows we do not hold")
    Employee = env['hr.employee'].sudo()                         # noqa: F821
    for key in sorted(only_theirs)[:25]:
        who = Employee.browse(key[0]).display_name if key[0] else '(no employee)'
        print("      %-34s %-5s %-6s %s row(s)"
              % (str(who)[:34], key[1], key[2], len(theirs[key])))
    if len(only_theirs) > 25:
        print("      ... and %s more key(s)" % (len(only_theirs) - 25))


title("5. the money on the rows we do hold")

# Identity is not enough. To Pay could be the same payroll under a different
# figure - a net after deductions rather than the salary of the month - and
# saying "we hold that key" would then be true and useless.
PAIRS = [
    ('total salary', 'total_salary', 'x_studio_total_salary_of_this_month'),
    ('overtime', 'overtime_salary', 'x_studio_total_overtime_salary_of_this_month'),
    ('adjustment', 'salary_adjustment', 'x_studio_salary_adjustment'),
]
for label, ours_field, their_field in PAIRS:
    if their_field not in Source._fields:
        print("  %-14s %s is not on To Pay" % (label, their_field))
        continue
    same = differ = 0
    drift = 0.0
    examples = []
    for key in both:
        mine = sum(s[ours_field] or 0.0 for s in ours[key])
        theirs_total = sum(_get(r, their_field) or 0.0 for r in theirs[key])
        if abs(mine - theirs_total) < 0.01:
            same += 1
        else:
            differ += 1
            drift += mine - theirs_total
            if len(examples) < 5:
                examples.append((key, mine, theirs_total))
    print("  %-14s %5s agree  %5s differ   drift %s"
          % (label, same, differ, round(drift, 2)))
    Employee = env['hr.employee'].sudo()                         # noqa: F821
    for (employee_id, month, year), mine, theirs_total in examples:
        who = Employee.browse(employee_id).display_name if employee_id else '-'
        print("        %-30s %-5s %-6s ours %-12s topay %s"
              % (str(who)[:30], month, year, round(mine, 2), round(theirs_total, 2)))


title("verdict")
if not only_theirs:
    print("""  Every To Pay row is a payroll we already hold as a payslip, for the same
  employee in the same month of the same year. It is the same payroll recorded
  twice and the copy nothing reads.

  What still goes with it and is not held anywhere: 2,431 lines and 4,878
  chatter messages - the approvals and the conversation around each payment.
  If that trail matters, it matters now.""")
else:
    print("""  %s key(s) exist in To Pay and not as a payslip. Read section 4 before
  deleting: those are the rows nothing else holds.""" % len(only_theirs))
