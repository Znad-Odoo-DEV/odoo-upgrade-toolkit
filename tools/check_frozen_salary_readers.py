"""The fourteen money readers: are they holding anything, and does it match?

    odoo-bin shell --no-http --shell-interface=python < tools/check_frozen_salary_readers.py

Reads only. Fourteen related fields across four Studio models read a salary or
an allowance off the employee and are declared float where ssc.employee says
monetary. Odoo will not build a registry where a related field and its source
disagree on type, so they cannot simply be repointed.

But look at what the four models are: to-pay, end of service, resigning request,
request to review. Every one of them is a document about a moment. A payslip
should say what the salary was when it was written, not what it is today, and a
stored related field has been holding exactly that all along - a copy, taken
when the record was made, and not refreshed since the path broke.

So the question is not what type they should be. It is whether they are stored
and full, in which case dropping the related path keeps every figure they hold
and stops them chasing a number that should never have moved. This counts the
rows, and compares what each document holds against what the employee says now,
so the size of the difference is a fact rather than an argument.
"""
SUSPECTS = [
    ('x_requests_to_review', 'x_studio_basic_salary', 'basic_salary'),
    ('x_to_pay', 'x_studio_basic_salary', 'basic_salary'),
    ('x_resigning_requests', 'x_studio_basic_salary', 'basic_salary'),
    ('x_end_of_service', 'x_studio_basic_salary', 'basic_salary'),
    ('x_requests_to_review', 'x_studio_gross_salary', 'gross_salary'),
    ('x_to_pay', 'x_studio_house_allowance', 'house_allowance'),
    ('x_to_pay', 'x_studio_other_allowances', 'other_allowance'),
    ('x_end_of_service', 'x_studio_other_allowances', 'other_allowance'),
    ('x_to_pay', 'x_studio_total_gross_salary', 'gross_salary'),
    ('x_resigning_requests', 'x_studio_total_gross_salary', 'gross_salary'),
    ('x_end_of_service', 'x_studio_total_gross_salary', 'gross_salary'),
    ('x_requests_to_review', 'x_studio_total_salary', 'gross_salary'),
    ('x_to_pay', 'x_studio_travelling_allownce', 'transport_allowance'),
    ('x_end_of_service', 'x_studio_travelling_allownce', 'transport_allowance'),
]

# the field on each document that names the employee
EMPLOYEE_LINK = {
    'x_to_pay': 'x_studio_for_employee',
    'x_end_of_service': 'x_studio_employee',
    'x_resigning_requests': 'x_studio_employee',
    'x_requests_to_review': 'x_studio_requested_for',
}

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


title("1. stored, and holding what")

for model, name, _source in SUSPECTS:
    field = IrField.search([('model', '=', model), ('name', '=', name)], limit=1)
    if not field:
        print("  %-24s %-30s not there any more" % (model, name))
        continue
    if not column_exists(model, name):
        print("  %-24s %-30s NOT STORED - dropping the path loses everything"
              % (model, name))
        continue
    cr.execute('SELECT COUNT(*), COUNT("%s"), COALESCE(SUM("%s"), 0), '
               '       COUNT(*) FILTER (WHERE "%s" > 0) FROM "%s"'
               % (name, name, name, model))
    rows, filled, total, positive = cr.fetchone()
    print("  %-24s %-30s %6s row(s)  %6s filled  %6s above zero  total %s"
          % (model, name, rows, filled, positive, round(total or 0, 2)))


title("2. what the document says against what the employee says now")

for model in sorted(EMPLOYEE_LINK):
    link = EMPLOYEE_LINK[model]
    Model = env.get(model)                                       # noqa: F821
    if Model is None or link not in Model._fields:
        print("\n  %s: no employee link named %s" % (model, link))
        continue
    fields_here = [(n, s) for m, n, s in SUSPECTS
                   if m == model and n in Model._fields]
    if not fields_here:
        print("\n  %s: Odoo has already dropped every one of them from the "
              "model" % model)
        continue
    records = Model.sudo().with_context(active_test=False).search([])
    same, moved, no_employee, empty = 0, 0, 0, 0
    examples = []
    for record in records:
        employee = record[link]
        if not employee:
            no_employee += 1
            continue
        ssc = employee.ssc_employee_id
        if not ssc:
            no_employee += 1
            continue
        for name, source in fields_here:
            held = record[name] or 0.0
            now = ssc[source] or 0.0
            if not held and not now:
                empty += 1
            elif abs(held - now) < 0.01:
                same += 1
            else:
                moved += 1
                if len(examples) < 8:
                    examples.append((record.id, name, held, now))
    print("\n  %s   (%s record(s), %s field(s) each)"
          % (model, len(records), len(fields_here)))
    print("      agree with the employee today : %s" % same)
    print("      differ                        : %s" % moved)
    print("      both empty                    : %s" % empty)
    print("      no employee to compare with   : %s" % no_employee)
    for record_id, name, held, now in examples:
        print("        %-8s %-28s document %-12s employee %s"
              % (record_id, name, round(held, 2), round(now, 2)))


title("what the numbers mean")
print("""  A figure that differs is the document remembering a salary that has since
  changed. Dropping the related path keeps it. Repointing it - which would mean
  making every one of these monetary, and giving four Studio models a currency
  they do not have - would overwrite it with today's.

  A field that is NOT stored above holds nothing of its own and would go empty;
  those, and only those, need the path.""")
