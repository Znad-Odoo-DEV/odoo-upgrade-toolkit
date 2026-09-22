"""The Salary Adjustment model, as this database actually defines it.

    odoo-bin shell -d <database> --no-http < tools/probe_salary_adjustment.py

Read only. Nothing is written, ever.

phone_bill_allowance and agreed_monthly_allowance are to stop being columns on
the employee and become Salary Adjustment records instead - one per person,
running to the end of 2026. Eight employees carry an amount and seven carry the
flag, which is a small enough number to get exactly right and no excuse for
getting it wrong.

The model belongs to enterprise hr_payroll, so its field names cannot be read
from a community checkout. Guessing them writes eight records into somebody's
payroll on names that only look plausible. So this prints the model as the
registry has it - every field, its type, whether it is required, and the
selection values behind Duration - along with the input types available for
Type, and the eight employees with what each is owed a month.
"""
from collections import defaultdict

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

IrField = env['ir.model.fields']
Ssc = env['ssc.employee']


def title(text):
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


MODEL = 'hr.salary.attachment'
Adjustment = env.get(MODEL)
if Adjustment is None:
    raise SystemExit("%s is not installed on this database." % MODEL)

# ----------------------------------------------------------------------
title("1. %s - EVERY FIELD" % MODEL)
# ----------------------------------------------------------------------
fields_ = IrField.search([('model', '=', MODEL)], order='name')
print("%s field(s)\n" % len(fields_))
print("%-34s %-12s %-9s %-9s %s"
      % ("NAME", "TYPE", "REQUIRED", "READONLY", "LABEL"))
print("-" * 100)
for rec in fields_:
    if rec.name.startswith(('activity_', 'message_', 'rating_', 'website_message_',
                            'my_activity_', 'has_message', 'access_')):
        continue
    if rec.name in ('create_uid', 'create_date', 'write_uid', 'write_date',
                    '__last_update', 'display_name', 'id'):
        continue
    field = Adjustment._fields.get(rec.name)
    print("%-34s %-12s %-9s %-9s %s"
          % (rec.name, rec.ttype,
             'yes' if (field is not None and field.required) else '',
             'yes' if (field is not None and field.readonly) else '',
             (rec.field_description or '')[:34]))

# ----------------------------------------------------------------------
title("2. THE SELECTIONS - what Duration and the rest actually accept")
# ----------------------------------------------------------------------
for name, field in sorted(Adjustment._fields.items()):
    if field.type != 'selection':
        continue
    try:
        options = field.selection
        if callable(options):
            options = options(Adjustment)
    except Exception:
        options = '(computed)'
    print("%-24s %s" % (name, options))

print()
print("Relational fields and what they point at:")
for name, field in sorted(Adjustment._fields.items()):
    if field.type in ('many2one', 'many2many', 'one2many'):
        print("%-24s %-12s -> %s" % (name, field.type, field.comodel_name))

# ----------------------------------------------------------------------
title("3. THE TYPE - which input types exist")
# ----------------------------------------------------------------------
# Type on the form is an input type. One of them has to mean a phone bill,
# or one has to be made.
InputType = env.get('hr.payslip.input.type')
if InputType is None:
    print("hr.payslip.input.type is not installed.")
else:
    types = InputType.search([])
    print("%s input type(s):\n" % len(types))
    print("%-40s %-22s %s" % ("NAME", "CODE", "COMPANIES"))
    print("-" * 90)
    for input_type in types:
        companies = ", ".join(input_type.company_id.mapped('name')) \
            if 'company_id' in input_type._fields else ''
        print("%-40s %-22s %s"
              % ((input_type.name or '')[:40], input_type.code or '-',
                 companies[:34] or 'all'))
    hits = types.filtered(
        lambda t: 'phone' in (t.name or '').lower()
        or 'mobile' in (t.name or '').lower()
        or 'telephone' in (t.name or '').lower())
    print()
    print("Looks like a phone allowance: %s"
          % (", ".join("%s [%s]" % (t.name, t.code) for t in hits) or "none"))

# ----------------------------------------------------------------------
title("4. WHAT ALREADY EXISTS - adjustments on this database")
# ----------------------------------------------------------------------
existing = Adjustment.with_context(active_test=False).search([])
print("%s salary adjustment(s) already recorded." % len(existing))
by_type = defaultdict(int)
for adjustment in existing:
    label = adjustment.other_input_type_id.name \
        if 'other_input_type_id' in adjustment._fields else '?'
    by_type[label] += 1
for label, count in sorted(by_type.items(), key=lambda kv: -kv[1]):
    print("    %-44s %s" % (label, count))
if existing:
    sample = existing[0]
    print()
    print("One of them, field by field, as a template to copy:")
    for name, field in sorted(sample._fields.items()):
        if field.type in ('one2many', 'many2many') or name.startswith(
                ('activity_', 'message_', 'my_activity_', 'has_message')):
            continue
        try:
            value = sample[name]
        except Exception:
            continue
        if hasattr(value, 'display_name'):
            value = value.display_name
        if value not in (False, '', 0, None):
            print("    %-28s %s" % (name, value))

# ----------------------------------------------------------------------
title("5. THE PEOPLE - who is owed a phone allowance")
# ----------------------------------------------------------------------
owed = Ssc.with_context(active_test=False).search(
    ['|', ('phone_bill_allowance', '=', True),
     ('agreed_monthly_allowance', '!=', 0)])
print("%s employee(s)\n" % len(owed))
print("%-38s %-13s %-7s %-11s %-9s %-7s %s"
      % ("NAME", "BADGE", "FLAG", "MONTHLY", "ACTIVE", "HR?", "COMPANY"))
print("-" * 100)
for employee in owed:
    print("%-38s %-13s %-7s %-11s %-9s %-7s %s"
          % (employee.name[:38],
             employee.employee_code or '-',
             'yes' if employee.phone_bill_allowance else 'no',
             employee.agreed_monthly_allowance or 0,
             'yes' if employee.active else 'no',
             'yes' if employee.hr_employee_id else 'NO',
             (employee.company_id.name or '')[:26]))

flagged_no_amount = owed.filtered(
    lambda e: e.phone_bill_allowance and not e.agreed_monthly_allowance)
amount_no_flag = owed.filtered(
    lambda e: e.agreed_monthly_allowance and not e.phone_bill_allowance)
print()
print("Flagged but no amount : %s  %s"
      % (len(flagged_no_amount), ", ".join(flagged_no_amount.mapped('name'))))
print("Amount but not flagged: %s  %s"
      % (len(amount_no_flag), ", ".join(amount_no_flag.mapped('name'))))
print()
print("The first group would produce an adjustment worth nothing; the second is")
print("money somebody entered without ticking the box that pays it. Neither can")
print("be carried across blind.")

print("\nDone. Read only - nothing was written.")
