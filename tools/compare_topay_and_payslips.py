"""Is To Pay the same payroll as All Payslips, or a second one?

    odoo-bin shell --no-http --shell-interface=python < tools/compare_topay_and_payslips.py

Reads only, and it exists because of one fact worth being sure about before
anything is deleted: ssc.payslip mirrors x_all_payslips. It has never heard of
x_to_pay. So the 1,591 rows in To Pay have no copy in the native module, and
deleting the model deletes them.

That may be perfectly fine. If To Pay is the same payroll seen a second way -
the same employees, the same months, the same money - then everything it holds
is in All Payslips already and it is a duplicate on its way out. If it is a
different set of periods or a different set of people, it is a record of its own
and deleting it loses a year of payroll history.

The two models are not asked to agree on field names. They are compared on what
a payslip is: an employee and a month, and the money against it.
"""
LEFT = 'x_to_pay'
RIGHT = 'x_all_payslips'

# candidate field names, tried in order, on each side
EMPLOYEE = ('x_studio_for_employee', 'x_studio_employee', 'x_studio_employee_1')
PERIOD = ('x_studio_month', 'x_studio_period', 'x_studio_salary_month',
          'x_studio_date', 'x_studio_from', 'x_studio_period_from')
AMOUNT = ('x_studio_net_amount', 'x_studio_net_salary', 'x_studio_total_amount',
          'x_studio_total_salary', 'x_studio_amount_to_pay', 'x_studio_total')

cr = env.cr                                                      # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def pick(Model, candidates):
    for name in candidates:
        if name in Model._fields:
            return name
    return None


def describe(model_name):
    Model = env.get(model_name)                                  # noqa: F821
    if Model is None:
        print("  %s is not in this database" % model_name)
        return None
    Model = Model.sudo().with_context(active_test=False)
    employee = pick(Model, EMPLOYEE)
    period = pick(Model, PERIOD)
    amount = pick(Model, AMOUNT)
    records = Model.search([])
    print("\n  %s" % model_name)
    print("      rows      %s" % len(records))
    print("      employee  %s" % (employee or 'no field found'))
    print("      period    %s" % (period or 'no field found'))
    print("      amount    %s" % (amount or 'no field found'))
    if not employee:
        # show what it does have, so the guess above can be corrected
        money = sorted(n for n, f in Model._fields.items()
                       if f.type in ('monetary', 'float') and n.startswith('x_'))
        links = sorted(n for n, f in Model._fields.items()
                       if f.type == 'many2one' and n.startswith('x_'))
        print("      links     %s" % ', '.join(links[:10]))
        print("      money     %s" % ', '.join(money[:10]))
    return {'model': Model, 'employee': employee, 'period': period,
            'amount': amount, 'records': records}


title("1. what each one is")

left = describe(LEFT)
right = describe(RIGHT)
if not left or not right or not left['employee'] or not right['employee']:
    print("\n  Cannot compare without an employee field on both sides.")
    print("  The names above are what each model actually has; tell me which")
    print("  one is the employee and which is the month and I will redo this.")
    raise SystemExit()


title("2. the same people?")


def key_of(record, spec):
    employee = record[spec['employee']]
    period = record[spec['period']] if spec['period'] else None
    return (employee.id if employee else 0, str(period or ''))


left_keys, right_keys = {}, {}
for record in left['records']:
    left_keys.setdefault(key_of(record, left), []).append(record)
for record in right['records']:
    right_keys.setdefault(key_of(record, right), []).append(record)

left_people = {k[0] for k in left_keys if k[0]}
right_people = {k[0] for k in right_keys if k[0]}
print("  employees in %-18s %s" % (LEFT, len(left_people)))
print("  employees in %-18s %s" % (RIGHT, len(right_people)))
print("  in both                        %s" % len(left_people & right_people))
print("  only in %-22s %s" % (LEFT, len(left_people - right_people)))
print("  only in %-22s %s" % (RIGHT, len(right_people - left_people)))


title("3. the same months?")

left_periods = sorted({k[1] for k in left_keys if k[1]})
right_periods = sorted({k[1] for k in right_keys if k[1]})
print("  %s periods in %s: %s" % (len(left_periods), LEFT, ', '.join(left_periods[:12])))
print("  %s periods in %s: %s" % (len(right_periods), RIGHT, ', '.join(right_periods[:12])))
shared = set(left_periods) & set(right_periods)
print("  %s period(s) in both" % len(shared))


title("4. the same rows?")

both = set(left_keys) & set(right_keys)
print("  %s (employee, period) pair(s) on both sides" % len(both))
print("  %s only in %s" % (len(set(left_keys) - set(right_keys)), LEFT))
print("  %s only in %s" % (len(set(right_keys) - set(left_keys)), RIGHT))

if left['amount'] and right['amount'] and both:
    agree, differ, examples = 0, 0, []
    for key in both:
        a = sum(r[left['amount']] or 0.0 for r in left_keys[key])
        b = sum(r[right['amount']] or 0.0 for r in right_keys[key])
        if abs(a - b) < 0.01:
            agree += 1
        else:
            differ += 1
            if len(examples) < 10:
                examples.append((key, a, b))
    print("\n  of the pairs on both sides, comparing %s against %s:"
          % (left['amount'], right['amount']))
    print("      same amount   %s" % agree)
    print("      different     %s" % differ)
    Employee = env['hr.employee'].sudo()                         # noqa: F821
    for (employee_id, period), a, b in examples:
        who = Employee.browse(employee_id).display_name if employee_id else '-'
        print("        %-32s %-10s %-12s %s" % (who[:32], period, round(a, 2), round(b, 2)))


title("what this means")
print("""  Rows that appear on both sides with the same money are the same payroll
  recorded twice, and %s is the copy nothing reads any more.

  Rows only in %s are a record with nowhere else to go. Deleting the model
  deletes them, and ssc.payslip will not have them: it mirrors %s and has
  never been told about %s.""" % (LEFT, LEFT, RIGHT, LEFT))
