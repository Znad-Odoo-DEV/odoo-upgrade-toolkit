"""What the staff payslips are, and what carrying them would run into.

    odoo-bin shell --no-http --shell-interface=python < tools/survey_staff_payslips.py

Reads only. x_staff_payslips has no bridge to ssc.payslip - it is not in the
list of eleven the module mirrors, and not one of its rows has crossed. Before
writing that bridge there are four things to know, and guessing at any of them
is how the last three faults happened.

 1. what it holds, and how much of it
 2. whether its ids collide with the ones already in studio_ref_id. That column
    was written from x_all_payslips, and an integer says nothing about which
    model it came from: id 3888 could be both. Two payslips answering to one
    reference is not something to find out afterwards.
 3. whether the same employee-month already has a payslip here, which would make
    an import a duplication rather than a migration
 4. which of its fields have a home on ssc.payslip already, and which do not
"""
SOURCE = 'x_staff_payslips'
TARGET = 'ssc.payslip'

cr = env.cr                                                      # noqa: F821
Slip = env[TARGET].sudo().with_context(active_test=False)        # noqa: F821
Source = env.get(SOURCE)                                         # noqa: F821

if Source is None:
    raise SystemExit("%s is not in this database." % SOURCE)
Source = Source.sudo().with_context(active_test=False)


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def g(record, name):
    if not record or name not in record._fields:
        return False
    return record[name]


# --- 1 ------------------------------------------------------------------------

title("1. what it holds")

rows = Source.search([], order='id')
print("  %s row(s)" % len(rows))
if rows:
    print("  ids %s .. %s" % (rows[0].id, rows[-1].id))
print("  %s field(s)" % len(Source._fields))

money = sorted(n for n, f in Source._fields.items()
               if f.type in ('monetary', 'float') and n.startswith('x_')
               and not f.related)
print("\n  money it keeps of its own:")
for name in money[:14]:
    cr.execute('SELECT COUNT(*), COALESCE(SUM("%s"), 0) FROM "%s" WHERE "%s" IS NOT NULL'
               % (name, SOURCE, name))
    filled, total = cr.fetchone()
    print("      %-44s %5s filled  %s" % (name, filled, round(total or 0, 2)))
if len(money) > 14:
    print("      ... and %s more" % (len(money) - 14))


# --- 2 ------------------------------------------------------------------------

title("2. would the references collide")

taken = set(Slip.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
clash = sorted(set(rows.ids) & taken)
print("  %s payslip(s) here already carry a studio_ref_id" % len(taken))
print("  %s of this model's ids are among them" % len(clash))
if clash:
    print("\n  the first of them, and what each reference currently means:")
    for ref in clash[:10]:
        slip = Slip.search([('studio_ref_id', '=', ref)], limit=1)
        theirs = Source.browse(ref)
        print("      %-8s ours: %-34s theirs: %s"
              % (ref, (slip.name or '')[:34],
                 (g(theirs, 'x_name') or '')[:34]))
    print("\n  An integer says nothing about which model it came from. Carrying")
    print("  these as they are would give two payslips one reference.")
else:
    print("  No overlap: these ids are free in studio_ref_id.")


# --- 3 ------------------------------------------------------------------------

title("3. is the same payroll already here")

EMPLOYEE = ('x_studio_employee', 'x_studio_for_employee', 'x_studio_employee_1')
MONTH = ('x_studio_month', 'x_studio_salary_month')
YEAR = ('x_studio_year',)


def pick(candidates):
    for name in candidates:
        if name in Source._fields:
            return name
    return None


employee_field, month_field, year_field = pick(EMPLOYEE), pick(MONTH), pick(YEAR)
print("  employee=%s  month=%s  year=%s"
      % (employee_field, month_field, year_field))

if employee_field:
    ours = {}
    for slip in Slip.search([]):
        hr = slip.employee_id.hr_employee_id if slip.employee_id else False
        ours.setdefault((hr.id if hr else 0, str(slip.month or ''),
                         str(slip.year or '')), []).append(slip)
    both, only_theirs, periods = 0, 0, {}
    examples = []
    for record in rows:
        employee = g(record, employee_field)
        key = (employee.id if employee else 0,
               str(g(record, month_field) or '') if month_field else '',
               str(g(record, year_field) or '') if year_field else '')
        periods[(key[1], key[2])] = periods.get((key[1], key[2]), 0) + 1
        if key[0] and key in ours:
            both += 1
            if len(examples) < 8:
                examples.append((record, ours[key][0]))
        else:
            only_theirs += 1
    print("\n  %s already here as a payslip for the same employee and month" % both)
    print("  %s are not" % only_theirs)
    print("\n  periods it covers:")
    for period, count in sorted(periods.items()):
        print("      %-14s %s row(s)" % ('%s %s' % period, count))
    for record, slip in examples:
        print("      studio %-8s -> ours %-8s %s"
              % (record.id, slip.id, (slip.name or '')[:40]))


# --- 4 ------------------------------------------------------------------------

title("4. what has a home on ssc.payslip and what does not")

native = set(Slip._fields)
LIKELY = {
    'x_studio_basic_salary': 'basic_salary',
    'x_studio_house_allowance': 'house_allowance',
    'x_studio_travelling_allownce': 'transport_allowance',
    'x_studio_other_allowances': 'other_allowance',
    'x_studio_total_gross_salary': 'gross_salary',
    'x_studio_days': 'days',
    'x_studio_month': 'month',
    'x_studio_year': 'year',
    'x_studio_designation': 'designation',
    'x_studio_net_amount': 'studio_net_amount',
    'x_studio_salary_adjustment': 'studio_salary_adjustment',
}
matched, unmatched = [], []
for name, field in sorted(Source._fields.items()):
    if not name.startswith('x_studio') or field.related:
        continue
    home = LIKELY.get(name)
    (matched if home and home in native else unmatched).append((name, field, home))

print("  %s field(s) map onto something ssc.payslip already has:" % len(matched))
for name, field, home in matched:
    print("      %-44s -> %s" % (name, home))

print("\n  %s field(s) do not:" % len(unmatched))
for name, field, _home in unmatched[:20]:
    print("      %-44s %s" % (name, field.type))
if len(unmatched) > 20:
    print("      ... and %s more" % (len(unmatched) - 20))

title("what this decides")
print("""  A collision in section 2 means the bridge cannot key on studio_ref_id alone,
  and the reference needs to say which model it came from.

  A large "already here" in section 3 means importing would duplicate rather
  than carry, and the match has to be on the employee and the month first.

  Section 4 is the field list the bridge would be written from - and the ones
  with no home are the same decision as before: they either find one, or they go
  with the model.""")
