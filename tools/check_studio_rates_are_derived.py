"""Are the Studio rates and month totals facts, or arithmetic we already hold?

    odoo-bin shell --no-http --shell-interface=python < tools/check_studio_rates_are_derived.py

Reads only. Four rates and four month totals on the Studio payslip have no field
of their own on ssc.payslip, and the question is whether that matters. It does
not if they are the same numbers decomposed - a rate being the salary over the
days, a month total being the rate over the days worked - because then nothing
is lost by not storing them and they can be shown from what is already there.

It matters a great deal if they are not, because then eight figures per payslip
go with the model.

So each is tested against the arithmetic it looks like, on all 4,584 rows, and
the answer is a count rather than an opinion. A formula that holds on every row
is a formula; one that holds on most is a coincidence with exceptions worth
reading.

rate_per_day is tested too, separately: that field does exist on ssc.payslip,
computed as the gross over the days. Whether the computed value equals the one
Studio recorded is a different question from whether the field is there, and it
was worth being clearer about the first time.
"""
SOURCE = 'x_all_payslips'
TOLERANCE = 0.02

cr = env.cr                                                      # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821
Slip = env['ssc.payslip'].sudo().with_context(active_test=False)  # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def g(record, name):
    if not record or name not in record._fields:
        return 0.0
    return record[name] or 0.0


rows = Source.search([])
print("  %s Studio payslip(s)" % len(rows))


def test(label, actual_field, formula):
    """Check one figure against the arithmetic it looks like."""
    same = differ = skipped = 0
    drift = 0.0
    examples = []
    for record in rows:
        want = formula(record)
        if want is None:
            skipped += 1
            continue
        have = g(record, actual_field)
        if abs(have - want) <= TOLERANCE:
            same += 1
        else:
            differ += 1
            drift += have - want
            if len(examples) < 4:
                examples.append((record, have, want))
    total = same + differ
    print("\n  %s" % label)
    print("      holds on %s of %s row(s)%s"
          % (same, total, '   (%s skipped)' % skipped if skipped else ''))
    if differ:
        print("      fails on %s, drift %s" % (differ, round(drift, 2)))
        for record, have, want in examples:
            print("        id %-8s recorded %-12s formula %-12s"
                  % (record.id, round(have, 2), round(want, 2)))


title("1. is a rate the salary over the days?")

for label, rate_field, salary_field in (
        ('basic', 'x_studio_basic_salary_rate', 'x_studio_basic_salary'),
        ('housing', 'x_studio_house_allowance_rate', 'x_studio_house_allowance'),
        ('transport', 'x_studio_travelling_allowance_rate', 'x_studio_travelling_allownce'),
        ('other', 'x_studio_other_allowances_rate', 'x_studio_other_allowances')):
    test('%s rate  =  %s / days' % (label, salary_field),
         rate_field,
         lambda r, s=salary_field: (g(r, s) / g(r, 'x_studio_days')
                                    if g(r, 'x_studio_days') else None))


title("2. is a month total the rate over the days worked?")

ATT = 'x_studio_total_attendance_for_this_month_1'
for label, total_field, rate_field in (
        ('basic', 'x_studio_total_basic_salary_this_month', 'x_studio_basic_salary_rate'),
        ('housing', 'x_studio_total_housing_allowance_this_month', 'x_studio_house_allowance_rate'),
        ('transport', 'x_studio_total_travelling_allowance_this_month',
         'x_studio_travelling_allowance_rate'),
        ('other', 'x_studio_total_other_allowance_this_month', 'x_studio_other_allowances_rate')):
    test('%s this month  =  %s * attendance' % (label, rate_field),
         total_field,
         lambda r, f=rate_field: g(r, f) * g(r, ATT))


title("2b. the same, without rounding the rate first")

# The rate is stored to two decimals. Multiplying it by thirty days multiplies
# the rounding by thirty too, which is the whole of the "failure" above: 36.66
# spread over 3,618 rows is a hundredth of a dirham each. Asked without the
# intermediate rounding - salary times attendance over days - it either holds
# everywhere or it does not, and that is the answer worth having.
for label, total_field, salary_field in (
        ('basic', 'x_studio_total_basic_salary_this_month', 'x_studio_basic_salary'),
        ('housing', 'x_studio_total_housing_allowance_this_month', 'x_studio_house_allowance'),
        ('transport', 'x_studio_total_travelling_allowance_this_month',
         'x_studio_travelling_allownce'),
        ('other', 'x_studio_total_other_allowance_this_month', 'x_studio_other_allowances')):
    test('%s this month  =  %s * attendance / days' % (label, salary_field),
         total_field,
         lambda r, s=salary_field: (g(r, s) * g(r, ATT) / g(r, 'x_studio_days')
                                    if g(r, 'x_studio_days') else None))


title("3. and rate_per_day, which we do have")

test('rate per day  =  gross / days',
     'x_studio_rate_per_day',
     lambda r: (g(r, 'x_studio_total_gross_salary') / g(r, 'x_studio_days')
                if g(r, 'x_studio_days') else None))

# The same question asked of our own record rather than of Studio's: does the
# value our compute produces equal the one Studio wrote down?
slips = Slip.search([('studio_ref_id', '!=', False)])
by_ref = {r.id: r for r in rows}
same = differ = 0
drift = 0.0
examples = []
for slip in slips:
    src = by_ref.get(slip.studio_ref_id)
    if not src:
        continue
    theirs = g(src, 'x_studio_rate_per_day')
    if abs((slip.rate_per_day or 0.0) - theirs) <= TOLERANCE:
        same += 1
    else:
        differ += 1
        drift += (slip.rate_per_day or 0.0) - theirs
        if len(examples) < 6:
            examples.append((slip, slip.rate_per_day or 0.0, theirs))
print("\n  our computed rate_per_day against the Studio one")
print("      agree on %s of %s payslip(s)" % (same, same + differ))
if differ:
    print("      differ on %s, drift %s" % (differ, round(drift, 2)))
    for slip, mine, theirs in examples:
        print("        %-8s %-28s ours %-11s studio %s"
              % (slip.id, (slip.employee_id.name or '')[:28],
                 round(mine, 2), round(theirs, 2)))


title("what this settles")
print("""  A figure that holds on every row is arithmetic, and arithmetic does not
  need storing: it can be shown from the salary, the days and the attendance,
  all three of which ssc.payslip already keeps.

  A figure that fails is a number somebody entered or a rule nobody has written
  down, and that one does go with the model unless it is carried.""")
