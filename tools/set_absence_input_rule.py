"""A box to type the number of days somebody was absent, and a rule that charges them.

    odoo-bin shell -d <database> --no-http < tools/set_absence_input_rule.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/set_absence_input_rule.py

Office staff do not punch. Twenty four of the thirty five have no attendance at
all in July and the rest have a handful of days, so the clock cannot say who was
absent and the base pays them a full month. ssc_payroll knows - it deducted
twenty two days from one of them - because somebody records office attendance by
hand. Four staff in July, fourteen thousand dirhams between them.

That record cannot be migrated. The daily log disagrees with its own counter on
four of the six people in it, and on one man it marks twenty one days absent
while the payslip paid him in full. Only the count can be trusted, and only
because the payslip was built from it.

So the count is what gets entered. One box on the payslip, the number of days,
and the rule prices them the way everything else here is priced - the gross over
the days in the month.

WHY NOT EDIT THE ATTENDANCE LINE INSTEAD

Because the two numbers are in different units and it would be entered wrong.
The worked days line counts scheduled days, twenty six of them, while absence
here has always been counted against the thirty one days of the month. Somebody
absent twenty two days is entered as four on that line, not twenty two, and
nobody would guess that twice running.

IT WORKS FOR LABOUR TOO

The punch still decides for them, and this sits on top for the day a punch was
missed for a reason a person knows about, or a correction after the fact. It
only ever fires when a number is typed.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'

STRUCTURES = (19, 20, 21, 22, 23, 24, 25)
CODE = 'ABSENCE_DAYS'
RULE = 'ABSENCE'

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

Rule = env['hr.salary.rule'].sudo()
Category = env['hr.salary.rule.category'].sudo()
InputType = env['hr.payslip.input.type'].sudo()

CONDITION = f"""
result = '{CODE}' in inputs and inputs['{CODE}'].amount > 0
"""

AMOUNT = f"""
days = inputs['{CODE}'].amount
days_in_month = (payslip.date_to - payslip.date_from).days + 1
gross = (version.wage + version.l10n_ae_housing_allowance
         + version.l10n_ae_transportation_allowance
         + version.l10n_ae_other_allowances)
result_qty = days
result = -gross / days_in_month if days_in_month else 0.0
"""


def title(text):
    print()
    print("=" * 94)
    print(text)
    print("=" * 94)


deduction = Category.search([('code', '=', 'DED')], limit=1)
if not deduction:
    print("no DED salary rule category - stopping")
    raise SystemExit

# ---------------------------------------------------------------------------
title("1. the input type")

existing_type = InputType.search([('code', '=', CODE)], limit=1)
if existing_type:
    print(f"  {CODE} already exists (id {existing_type.id})")
else:
    print(f"  {CODE} will be created, named 'Absence Days'")
    print("  not tied to any structure, so it can be typed on any payslip")

# ---------------------------------------------------------------------------
title("2. the rule")

print("  condition")
for line in CONDITION.strip().splitlines():
    print(f"      {line}")
print()
print("  amount")
for line in AMOUNT.strip().splitlines():
    print(f"      {line}")
print()
print("  category DED, sequence 59, just ahead of Unpaid Leave")

found = Rule.search([('struct_id', 'in', STRUCTURES), ('code', '=', RULE)])
print()
print(f"  {len(found)} already exist, {len(STRUCTURES) - len(found)} to create")

# ---------------------------------------------------------------------------
title("3. what it does to the four staff it was written for")

print(f"  {'employee':<34} {'absent':>7} {'gross':>10} {'deduction':>12}")
for name, absent, gross in (
        ('Ahmad Mohamad Haleme', 22, 12000.0),
        ('Monu Kiran Dev Sahadevan', 18, 8000.0),
        ('Ebrahim Mohamad Alzenad', 4, 5000.0),
        ('Mohamed Ahmed Moustafa Ibrahim', 1, 9000.0)):
    print(f"  {name:<34} {absent:>7} {gross:>10,.2f} {-absent * gross / 31:>12,.2f}")
print()
print("  Those four figures add up to the whole remaining staff gap for July.")

# ---------------------------------------------------------------------------
if APPLY:
    if not existing_type:
        existing_type = InputType.create({'name': 'Absence Days', 'code': CODE})
        print(f"created input type {existing_type.code} (id {existing_type.id})")

    made, changed = 0, 0
    for struct_id in STRUCTURES:
        vals = {
            'name': 'Absence',
            'code': RULE,
            'sequence': 59,
            'category_id': deduction.id,
            'condition_select': 'python',
            'condition_python': CONDITION,
            'amount_select': 'code',
            'amount_python_compute': AMOUNT,
            'appears_on_payslip': True,
            'active': True,
            'struct_id': struct_id,
        }
        rule = Rule.search([('struct_id', '=', struct_id), ('code', '=', RULE)], limit=1)
        if rule:
            rule.write(vals)
            changed += 1
        else:
            Rule.create(vals)
            made += 1
    env.cr.commit()

    title("APPLIED")
    print(f"  input type ready | rules created {made} | updated {changed}")
    print()
    print("  On a payslip: Salary Inputs tab, add a line, pick Absence Days,")
    print("  and put the number of days in the amount. The deduction appears")
    print("  on Salary Computation after Compute Sheet.")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
