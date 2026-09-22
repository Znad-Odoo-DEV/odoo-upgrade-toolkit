"""Pay overtime off the basic hourly wage, at two rates, from the entries that exist.

    odoo-bin shell -d <database> --no-http < tools/set_overtime_rules.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/set_overtime_rules.py

The overtime rule the localisation ships reads a work entry code this company
does not produce:

    result = worked_days['OVERTIME'].number_of_hours
             * payslip.l10n_ae_hourly_wage
             * payslip._rule_parameter('l10n_ae_overtime')

There are forty eight OVERTIME entries in the database, all stamped on a single
day in August, and they are left over from a test. The real overtime arrives as
SSC_OT_REG and SSC_OT_OFF - twenty two thousand hours and three thousand hours
since May. So that rule pays nothing at all, and would be wrong twice over if
it did: l10n_ae_hourly_wage divides the gross by the hours actually worked, and
the parameter applies one rate of 150% to every hour.

WHAT THIS COMPANY ACTUALLY PAYS

    hourly = basic salary / 240          thirty days of eight hours
    working day  125% of it
    off day      150% of it

Which is Article 19 of the UAE labour law, and what ssc_payroll has been paying
all along. The 240 is a convention, not a measurement: it does not change in
February and it does not move when somebody works a short month.

WHERE THE RATES LIVE

On the work entry types, where they already sit - SSC_OT_REG carries 1.25 and
SSC_OT_OFF carries 1.5. The rules read `amount_rate` off the line rather than
naming a number, so changing what an overtime hour is worth is a change to one
configuration record and no rule is touched.

TWO RULES, NOT ONE

Because ssc_payroll reports the two separately and the payslips have to be
reconciled against it line by line. Each rule reports the hours as the quantity
and the hourly figure as the amount, so a payslip shows what was paid for and
at what price instead of one total nobody can check.

The rule that shipped is archived rather than deleted, and only if no other
rule refers to it.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'

# our structures, not the localisation's own
STRUCTURES = (19, 20, 21, 22, 23, 24, 25)
MONTHLY_HOURS = 240

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

Rule = env['hr.salary.rule'].sudo()
Structure = env['hr.payroll.structure'].sudo()
Category = env['hr.salary.rule.category'].sudo()
WorkEntry = env['hr.work.entry.type'].sudo()
Version = env['hr.version'].sudo()


def title(text):
    print()
    print("=" * 94)
    print(text)
    print("=" * 94)


def python_for(code):
    return (
        "\n"
        "lines = [l for l in payslip.worked_days_line_ids\n"
        f"         if l.work_entry_type_id.code == '{code}']\n"
        "hours = sum(l.number_of_hours for l in lines)\n"
        "rate = lines[0].work_entry_type_id.amount_rate if lines else 0.0\n"
        f"hourly = (payslip.version_id.wage or 0.0) / {MONTHLY_HOURS}.0\n"
        "result_qty = hours\n"
        "result = hourly * rate\n"
    )


PLAN = [
    ('OT_REG', 'Overtime - Working Days', 'SSC_OT_REG', 63),
    ('OT_OFF', 'Overtime - Off Days', 'SSC_OT_OFF', 64),
]

allowance = Category.search([('code', '=', 'ALW')], limit=1)
if not allowance:
    print("no ALW salary rule category - stopping")
    raise SystemExit

# ---------------------------------------------------------------------------
title("1. the work entry types the rules will read")

for _code, _name, entry_code, _seq in PLAN:
    entry = WorkEntry.search([('code', '=', entry_code)], limit=1)
    if not entry:
        print(f"  {entry_code:<12} MISSING - stopping")
        raise SystemExit
    print(f"  {entry_code:<12} {entry.name:<30} rate={entry.amount_rate}  "
          f"is_leave={entry.is_leave}")

# ---------------------------------------------------------------------------
title("2. who uses which structure")

# A contract points at a structure *type*, not a structure; the payslip picks
# the structure out of the type. So counting who a rule will reach means
# counting the contracts on its structure's type.
for struct in Structure.browse(STRUCTURES).exists():
    users = Version.search_count([('structure_type_id', '=', struct.type_id.id)])         if struct.type_id else 0
    print(f"  {struct.id:<4} {struct.name[:46]:<46} "
          f"type={(struct.type_id.name or '-')[:30]:<30} contracts={users}")

# ---------------------------------------------------------------------------
title("3. is anything else referring to the rule being retired")

old = Rule.search([('struct_id', 'in', STRUCTURES), ('code', '=', 'OT'),
                   ('active', '=', True)])
referring = Rule.search([('struct_id', 'in', STRUCTURES), ('active', '=', True),
                         ('code', '!=', 'OT'),
                         ('amount_python_compute', 'ilike', 'OT')])
suspects = [r for r in referring
            if any(token in (r.amount_python_compute or '')
                   for token in ("['OT']", '["OT"]', 'categories[\'OT\']', ' OT ', '= OT'))]
print(f"  rules named OT to retire : {len(old)}")
print(f"  rules that mention OT    : {len(suspects)}")
for rule in suspects:
    print(f"      struct {rule.struct_id.id:<4} {rule.code}")
if suspects:
    print()
    print("  Something reads the rule that is about to be archived. Nothing is")
    print("  written. Read those rules first.")
    raise SystemExit

# ---------------------------------------------------------------------------
title("4. what changes")

creating, updating = [], []
for struct_id in STRUCTURES:
    if not Structure.browse(struct_id).exists():
        continue
    for code, name, entry_code, sequence in PLAN:
        existing = Rule.search([('struct_id', '=', struct_id), ('code', '=', code)],
                               limit=1)
        (updating if existing else creating).append((struct_id, code, entry_code))

print(f"  rules to create : {len(creating)}")
print(f"  rules to update : {len(updating)}")
print(f"  rules to archive: {len(old)}")
print()
print("  the expression, identical on every structure except the code it reads:")
for line in python_for('SSC_OT_REG').strip().splitlines():
    print(f"      {line}")

# ---------------------------------------------------------------------------
if APPLY:
    made, changed = 0, 0
    for struct_id in STRUCTURES:
        if not Structure.browse(struct_id).exists():
            continue
        for code, name, entry_code, sequence in PLAN:
            vals = {
                'name': name,
                'code': code,
                'sequence': sequence,
                'category_id': allowance.id,
                'condition_select': 'none',
                'amount_select': 'code',
                'amount_python_compute': python_for(entry_code),
                'appears_on_payslip': True,
                'active': True,
                'struct_id': struct_id,
            }
            existing = Rule.search([('struct_id', '=', struct_id),
                                    ('code', '=', code)], limit=1)
            if existing:
                existing.write(vals)
                changed += 1
            else:
                Rule.create(vals)
                made += 1
    old.write({'active': False})
    env.cr.commit()

    title("APPLIED")
    print(f"  created {made} | updated {changed} | archived {len(old)}")
    print()
    live = Rule.search([('struct_id', 'in', STRUCTURES), ('active', '=', True),
                        ('code', 'in', ('OT', 'OT_REG', 'OT_OFF'))])
    for rule in live.sorted(lambda r: (r.struct_id.id, r.sequence)):
        print(f"  struct {rule.struct_id.id:<4} {rule.code:<8} {rule.name}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
