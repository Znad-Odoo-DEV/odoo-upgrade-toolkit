"""Six staff payslips, every figure they hold, so the map is drawn from evidence.

    odoo-bin shell --no-http --shell-interface=python < tools/sample_staff_payslips.py

Reads only. Two fields on x_staff_payslips have names that could mean several
things - x_studio_value and x_studio_total_salary_of_this_month - and a bridge
written from a guess about either would carry the wrong number into a payslip.

The arithmetic tells you which is which. A net is a gross less the deductions; a
month total is a rate over the days attended. So six rows are printed with every
figure they hold side by side, and the relationships are visible rather than
assumed.

The month and the year are printed raw as well: they are x_studio_mon and
x_studio_yea here, not the names the other payslip model uses, and ssc.payslip
wants JAN and 2026 in particular.
"""
SOURCE = 'x_staff_payslips'

cr = env.cr                                                      # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821

FIGURES = [
    'x_studio_basic_salary',
    'x_studio_housing_allowance',
    'x_studio_travelling_allownce',
    'x_studio_other_allowances',
    'x_studio_total_gross_salary',
    'x_studio_rate_per_day',
    'x_studio_days',
    'x_studio_total_attended_days_this_month',
    'x_studio_total_salary_of_this_month',
    'x_studio_salary_adjusments',
    'x_studio_value',
]


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def g(record, name):
    if name not in record._fields:
        return None
    return record[name]


title("1. six of them, figure by figure")

rows = Source.search([], order='id desc', limit=6)
for record in rows:
    employee = g(record, 'x_studio_employee')
    print("\n  id %s   %s" % (record.id, (g(record, 'x_name') or '')[:50]))
    print("      employee   %-34s (%s)"
          % ((employee.display_name or '')[:34] if employee else '-',
             employee._name if employee else '-'))
    print("      month      %r      year %r"
          % (g(record, 'x_studio_mon'), g(record, 'x_studio_yea')))
    for name in FIGURES:
        value = g(record, name)
        if value is None:
            continue
        print("      %-42s %s" % (name, value))


title("2. does the arithmetic name them")

same_gross = same_month = same_net = 0
checked = 0
for record in Source.search([]):
    basic = g(record, 'x_studio_basic_salary') or 0.0
    house = g(record, 'x_studio_housing_allowance') or 0.0
    transport = g(record, 'x_studio_travelling_allownce') or 0.0
    other = g(record, 'x_studio_other_allowances') or 0.0
    gross = g(record, 'x_studio_total_gross_salary') or 0.0
    days = g(record, 'x_studio_days') or 0
    attended = g(record, 'x_studio_total_attended_days_this_month') or 0
    month_total = g(record, 'x_studio_total_salary_of_this_month') or 0.0
    adjust = g(record, 'x_studio_salary_adjusments') or 0.0
    value = g(record, 'x_studio_value') or 0.0
    checked += 1
    if abs((basic + house + transport + other) - gross) < 0.02:
        same_gross += 1
    if days and abs(gross * attended / days - month_total) < 0.05:
        same_month += 1
    if abs((month_total + adjust) - value) < 0.02:
        same_net += 1

print("  of %s row(s):" % checked)
print("    basic + housing + transport + other  ==  total_gross_salary      %s" % same_gross)
print("    total_gross * attended / days        ==  total_salary_of_month   %s" % same_month)
print("    total_salary_of_month + adjustments  ==  value                   %s" % same_net)


title("3. the months and years it uses")

pairs = {}
for record in Source.search([]):
    key = (g(record, 'x_studio_mon'), g(record, 'x_studio_yea'))
    pairs[key] = pairs.get(key, 0) + 1
for pair, count in sorted(pairs.items(), key=lambda kv: str(kv[0])):
    print("  %-20s %s row(s)" % (str(pair), count))

Slip = env['ssc.payslip']                                        # noqa: F821
print("\n  ssc.payslip accepts these months: %s"
      % ', '.join(dict(Slip._fields['month'].selection)))


title("what this settles")
print("""  A relationship that holds on every row is what that field is. One that holds
  on none is a name that means something else, and the bridge must not carry it
  into the figure it looks like.""")
