"""Pay a leave before it is taken, a gratuity when somebody leaves, and each day once.

    odoo-bin shell -d <database> --no-http < tools/set_leave_and_eos_rules.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/set_leave_and_eos_rules.py

Four things, and they belong together because the first one is a hole the
others fall into.

EACH DAY ONCE

The BASIC rule now pays every day a work entry covers, leave days included. The
localisation was not built that way - its BASIC paid worked hours and AEPAID
added the paid leave hours on top - so with our BASIC in place AEPAID pays the
same leave day a second time, and AESPAID50 turns a half paid sick day into a
day and a half. Both are additions to a base that already added them.

So they go, and the deductions take over. That is the shape the rest of the
structure already has: AEUNPAID claws back an unpaid day in full, SL50 claws
back half a sick day, SL0 claws back all of one. The base pays everything
covered and the deductions take back what is not owed.

SL50 and SL0 were switched off in a way nobody would notice: their condition
requires `work_entry_source == "calendar"` and these contracts are on
attendance, so a fifty percent sick day has been paying a hundred percent and
an unpaid one the same. The condition drops that clause, and both move from a
flat thirty to the days in the month, so they divide the way BASIC does.

A LEAVE IS PAID BEFORE IT IS TAKEN

Which is the custom here and in the country - a labourer flying home for six
weeks is paid before boarding, not on return. So the annual leave provision,
which quietly accrued a twelfth of a month every month, is replaced by a rule
that pays the leave itself on the last payslip before it starts: it looks a
month ahead in Time Off, finds the approved annual leave, and pays a thirtieth
of gross for each calendar day of it. Thirty days of leave, one month's pay.

Calendar days, not working days, because the entitlement the law grants is
thirty days a year counted on the calendar, and a leave that spans a month
should pay a month.

THE GRATUITY NEEDS NOTHING

End of Service was archived by mistake. Its condition already reads

    not employee.active and employee.departure_reason_id

which is exactly the last payslip after somebody is cancelled, and its
arithmetic is Article 51: twenty one days a year for the first five, thirty
after. It computes on `version.wage`, so it only became correct today - before
the basic was separated from the allowances it would have priced a gratuity on
the gross and overpaid every settlement by sixty percent.

Its monthly companion EOSP stays archived. A provision is a liability the
accounts carry, not a line on somebody's payslip.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'

STRUCTURES = (19, 20, 21, 22, 23, 24, 25)
ANNUAL_LEAVE = 'Annual Leave'

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

Rule = env['hr.salary.rule'].sudo()
Category = env['hr.salary.rule.category'].sudo()
LeaveType = env['hr.leave.type'].sudo()


def title(text):
    print()
    print("=" * 96)
    print(text)
    print("=" * 96)


annual = LeaveType.search([('name', '=', ANNUAL_LEAVE), ('active', '=', True)], limit=1)
if not annual:
    print(f"leave type {ANNUAL_LEAVE!r} does not exist - stopping")
    raise SystemExit
allowance = Category.search([('code', '=', 'ALW')], limit=1)

# The leave that is about to start: approved, annual, beginning after this
# payslip closes and within the month that follows - so exactly one payslip
# ever catches it, the last one before departure.
FIND_LEAVE = f"""
horizon = payslip.date_to + relativedelta(months=1)
leaves = payslip.env['hr.leave'].sudo().search([
    ('employee_id', '=', employee.id),
    ('state', '=', 'validate'),
    ('holiday_status_id', '=', {annual.id}),
    ('request_date_from', '>', payslip.date_to),
    ('request_date_from', '<=', horizon),
])
"""

LEAVE_SALARY_CONDITION = FIND_LEAVE + "result = bool(leaves)\n"

LEAVE_SALARY_AMOUNT = FIND_LEAVE + """
days = sum((l.request_date_to - l.request_date_from).days + 1 for l in leaves)
gross = (version.wage + version.l10n_ae_housing_allowance
         + version.l10n_ae_transportation_allowance
         + version.l10n_ae_other_allowances)
result_qty = days
result = gross / 30.0
"""

SICK = """
days_in_month = (payslip.date_to - payslip.date_from).days + 1
gross = (version.wage + version.l10n_ae_housing_allowance
         + version.l10n_ae_transportation_allowance
         + version.l10n_ae_other_allowances)
result = -worked_days['%(code)s'].number_of_days * gross / days_in_month * %(share)s
"""

SICK_CONDITION = "result = employee.active and '%(code)s' in worked_days\n"

REWRITE = {
    'SL50': {
        'condition_python': SICK_CONDITION % {'code': 'AESICKLEAVE50'},
        'amount_python_compute': SICK % {'code': 'AESICKLEAVE50', 'share': '0.5'},
    },
    'SL0': {
        'condition_python': SICK_CONDITION % {'code': 'AESICKLEAVE0'},
        'amount_python_compute': SICK % {'code': 'AESICKLEAVE0', 'share': '1.0'},
    },
}

# AEPAID and AESPAID50 pay a day the base already paid. EOSP and ALP are the
# monthly provisions - a liability the accounts carry, not a line on somebody's
# payslip, and ALP is replaced below by the leave itself paid before it starts.
RETIRE = ('AEPAID', 'AESPAID50', 'EOSP', 'ALP')
RESTORE = ('EOS',)

# ---------------------------------------------------------------------------
title("1. rules to archive - double payments and monthly provisions")

retiring = Rule.search([('struct_id', 'in', STRUCTURES), ('code', 'in', RETIRE),
                        ('active', '=', True)])
print(f"  {len(retiring)} rule(s) to archive")
for rule in retiring.sorted(lambda r: (r.code, r.struct_id.id)):
    print(f"      struct {rule.struct_id.id:<4} {rule.code:<12} {rule.name}")

# ---------------------------------------------------------------------------
title("2. deductions that never fired")

for code, vals in REWRITE.items():
    current = Rule.search([('struct_id', '=', 19), ('code', '=', code)], limit=1)
    print(f"  {code}")
    print(f"      now : {(current.condition_python or '').strip()[:88]}")
    print(f"      next: {vals['condition_python'].strip()}")
    print()

# ---------------------------------------------------------------------------
title("3. the gratuity, put back as it was")

restoring = Rule.search([('struct_id', 'in', STRUCTURES), ('code', 'in', RESTORE),
                         ('active', '=', False)])
print(f"  {len(restoring)} rule(s) to reactivate")
sample = Rule.search([('struct_id', '=', 19), ('code', '=', 'EOS')], limit=1)
if sample:
    print(f"      condition: {(sample.condition_python or '').strip()}")

# ---------------------------------------------------------------------------
title("4. the leave, paid before it starts")

print(f"  leave type: {annual.name} (id {annual.id})")
print()
print("  condition")
for line in LEAVE_SALARY_CONDITION.strip().splitlines():
    print(f"      {line}")
print()
print("  amount")
for line in LEAVE_SALARY_AMOUNT.strip().splitlines():
    print(f"      {line}")

existing = Rule.search([('struct_id', 'in', STRUCTURES), ('code', '=', 'LEAVESAL')])
print()
print(f"  {len(existing)} already exist, {len(STRUCTURES) - len(existing)} to create")

# ---------------------------------------------------------------------------
if APPLY:
    retiring.write({'active': False})
    restoring.write({'active': True})
    for code, vals in REWRITE.items():
        Rule.search([('struct_id', 'in', STRUCTURES), ('code', '=', code)]).write(vals)

    made = 0
    for struct_id in STRUCTURES:
        vals = {
            'name': 'Annual Leave Salary',
            'code': 'LEAVESAL',
            'sequence': 72,
            'category_id': allowance.id,
            'condition_select': 'python',
            'condition_python': LEAVE_SALARY_CONDITION,
            'amount_select': 'code',
            'amount_python_compute': LEAVE_SALARY_AMOUNT,
            'appears_on_payslip': True,
            'active': True,
            'struct_id': struct_id,
        }
        found = Rule.search([('struct_id', '=', struct_id), ('code', '=', 'LEAVESAL')],
                            limit=1)
        if found:
            found.write(vals)
        else:
            Rule.create(vals)
            made += 1
    env.cr.commit()

    title("APPLIED")
    print(f"  archived {len(retiring)} | reactivated {len(restoring)} | "
          f"rewritten {2 * len(STRUCTURES)} | created {made}")
    print()
    live = Rule.search([('struct_id', '=', 19), ('active', '=', True)])
    print("  structure 19 now pays and deducts, in order:")
    for rule in live.sorted('sequence'):
        print(f"      {rule.sequence:>4} {rule.code:<18} "
              f"{rule.category_id.code:<6} {rule.name[:44]}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
