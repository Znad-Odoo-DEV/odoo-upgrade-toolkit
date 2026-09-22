"""Give every employee who is being paid an analytic account of their own.

    odoo-bin shell -d <database> --no-http < tools/create_employee_analytic.py

Dry run by default. Prefix the command with APPLY=1 to write:

    APPLY=1 odoo-bin shell -d <database> --no-http < tools/create_employee_analytic.py

Run this AFTER tools/link_employee_analytic.py, which links the accounts that
already exist. What is left over after that is not a matching problem: those
people simply have no account. Most were hired recently - the badges run
SSCLLC-378 and upwards - and nobody made one for them; the rest carry no badge
on ssc.employee at all, which is an HR gap and not an accounting one.

Both are fixed the same way, and the way avoids the trap the linking tool fell
into. **Nothing here is matched.** The account is created FOR one employee and
linked in the same breath, so its identity is not deduced from a code or a name
- it is decided at the moment of creation and can never be wrong. That is also
why an employee with no badge is no harder than one with a badge: after this,
the link on hr.employee is what identifies the account, and the code is only a
label for people to read.

The one thing that could go wrong is making a second account for somebody who
already has one under a name or a code we failed to match. So before creating
anything, an account with the same code, or with the same name, is looked for -
and if one exists it is reported and NOTHING is created. A duplicate analytic
account splits one person's cost across two lines in every report thereafter,
quietly, and is far harder to undo than to avoid.
"""
import os
import re
from collections import defaultdict

APPLY = os.environ.get('APPLY') == '1'

# The root plan the per-employee accounts live in.
PLAN_NAME = 'Salaries & Wages'
# How far back to look for who is actually being paid. Somebody who left years
# ago needs no analytic account: the entries that mentioned them are posted.
PAYSLIP_DEPTH = int(os.environ.get('DEPTH') or 2000)

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

Plan = env['account.analytic.plan']
Analytic = env['account.analytic.account']
HrEmployee = env['hr.employee']
Payslip = env['ssc.payslip']

plan = Plan.search([('name', '=', PLAN_NAME), ('parent_id', '=', False)], limit=1)
if not plan:
    raise SystemExit("No root analytic plan named %r." % PLAN_NAME)

accounts = Analytic.search([('root_plan_id', '=', plan.id)])


def norm_code(code):
    """A code compared whole: SSCLLC-122 is not 122. The prefix is part of the
    identity - two series here carry the same numbers."""
    return (code or '').strip().upper().replace(' ', '')


def norm_name(name):
    """A name flattened enough that spacing and case cannot hide a duplicate."""
    return re.sub(r'\s+', ' ', (name or '').strip()).lower()


existing_by_code = defaultdict(list)
existing_by_name = defaultdict(list)
for account in accounts:
    if norm_code(account.code):
        existing_by_code[norm_code(account.code)].append(account)
    existing_by_name[norm_name(account.name)].append(account)

paid = Payslip.search([], order='id desc', limit=PAYSLIP_DEPTH).mapped('employee_id')
print("%s account(s) in %r" % (len(accounts), plan.name))
print("%s employee(s) on the last %s payslip(s)" % (len(paid), PAYSLIP_DEPTH))

to_create = []
to_adopt = []
already = 0
collides = []
no_hr = []

for employee in paid:
    hr_employee = employee.hr_employee_id
    if not hr_employee:
        no_hr.append("%s [%s]" % (employee.name, employee.employee_code or 'no code'))
        continue
    if hr_employee.ssc_analytic_account_id:
        already += 1
        continue
    # The only real risk: a second account for somebody who already has one we
    # failed to match. Refuse rather than duplicate.
    clashes = Analytic.browse()
    if norm_code(employee.employee_code):
        for account in existing_by_code.get(norm_code(employee.employee_code), []):
            clashes |= account
    for account in existing_by_name.get(norm_name(employee.name), []):
        clashes |= account
    if clashes:
        # One account, and its name is this employee's name exactly: that IS
        # their account, and the code merely disagrees - the badge was changed
        # on one side and not the other, or the account was made before the
        # badge existed. Adopting it is right, and making a second one beside
        # it would be the duplicate this check exists to prevent. Anything
        # less certain than exactly one exact namesake is left for a person.
        exact = clashes.filtered(
            lambda a: norm_name(a.name) == norm_name(employee.name))
        taken = HrEmployee.search_count(
            [('ssc_analytic_account_id', '=', exact.id)]) if len(exact) == 1 else 0
        if len(clashes) == 1 and len(exact) == 1 and not taken:
            to_adopt.append((employee, hr_employee, exact))
            continue
        collides.append(
            "%-44s [%-12s] already has %s"
            % (employee.name[:44], employee.employee_code or 'no code',
               ", ".join("%s %r" % (a.code or '(no code)', a.name) for a in clashes)))
        continue
    to_create.append((employee, hr_employee))

print()
for employee, hr_employee in sorted(to_create, key=lambda pair: pair[0].name or ''):
    print("  %-46s [%-12s] %s"
          % (employee.name[:46], employee.employee_code or 'no code',
             employee.company_id.name))
    if APPLY:
        account = Analytic.create({
            'name': employee.name,
            # The badge when there is one. When there is not, the account still
            # works: after this the link on hr.employee is the identity, and
            # the code is only there for a person reading a report.
            'code': employee.employee_code or False,
            'plan_id': plan.id,
            'company_id': employee.company_id.id,
        })
        hr_employee.ssc_analytic_account_id = account

for employee, hr_employee, account in sorted(to_adopt,
                                             key=lambda row: row[0].name or ''):
    print("  %-46s [%-12s] adopts existing %s %r"
          % (employee.name[:46], employee.employee_code or 'no code',
             account.code or '(no code)', account.name))
    if APPLY:
        hr_employee.ssc_analytic_account_id = account


def report(title, items, limit=25):
    if not items:
        return
    print()
    print("%s (%s):" % (title, len(items)))
    for item in items[:limit]:
        print("   ", item)
    if len(items) > limit:
        print("    ... and %s more" % (len(items) - limit))


print()
print("=" * 100)
print("%s account(s) %s, %s existing account(s) %s, %s employee(s) already had one."
      % (len(to_create), "created" if APPLY else "to create",
         len(to_adopt), "adopted" if APPLY else "to adopt", already))
report("NOT created and NOT adopted - more than one account could be theirs, "
       "or the one that could is not an exact namesake. These are duplicate "
       "accounts to merge, and a person has to say which survives", collides)
report("No hr.employee behind them, so there is nowhere to store the link. "
       "This is the HR gap, and it has to be closed on the employee first",
       no_hr)

print()
print("=" * 100)
print("After this: %s of %s paid employee(s) carry an analytic account."
      % (already + len(to_create) + len(to_adopt), len(paid)))
print("The rest carry the project on a salary entry but not themselves, and the")
print("batch names the amount in its chatter rather than losing it.")

if APPLY:
    env.cr.commit()
    print("\nCommitted.")
else:
    env.cr.rollback()
    print("\nDRY RUN - nothing was written. Re-run with APPLY=1 to apply.")
