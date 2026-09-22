"""Link each employee to the analytic account that stands for them.

    odoo-bin shell -d <database> --no-http < tools/link_employee_analytic.py

Dry run by default. Prefix the command with APPLY=1 to write:

    APPLY=1 odoo-bin shell -d <database> --no-http < tools/link_employee_analytic.py

An environment variable rather than a line to edit, because the Odoo.sh
worktree is read only and there is nowhere to change a flag.

There are 346 analytic accounts in the 'Salaries & Wages' plan, one per
employee. The Studio rule found them by searching for the employee's name on
every run, which works until two people share a name and then charges one
person's salary to the other, quietly and for as long as nobody looks.

Matching is on the WHOLE code, never on the digits inside it. The prefix is
part of the identity: this database carries 222 accounts coded SSCLLC-N and 73
coded plain N, so [122] is Arunkumar Ganesan while [SSCLLC-122] is Abdul
Ghaffar Muhammad Yar. A first attempt stripped the prefix and paired those two,
which would have charged one man's salary to the other's account - the exact
error this whole change exists to remove.

And a code match is not enough on its own. Before any link is written the two
names must share at least one meaningful word. On this database that refuses
exactly one pair out of 323, which is one pair of salaries that would otherwise
have gone to the wrong person for as long as nobody reconciled it.

Set NAME_MATCH=1 to additionally link accounts that carry NO code at all, by an
unambiguous full-name match. Off by default: a name is not an identity.
"""
import os
import re
from collections import defaultdict

APPLY = os.environ.get('APPLY') == '1'
NAME_MATCH = os.environ.get('NAME_MATCH') == '1'

# The root plan holding the per-employee accounts.
PLAN_NAME = 'Salaries & Wages'

# Words too common here to prove two names are the same person. Without these
# removed, "Mohammad Yousuf Ali" and "Mohammad Allauddin" look related.
COMMON = {
    'mohammad', 'mohamed', 'muhammad', 'mohd', 'md', 'ahmed', 'ahmad',
    'abdul', 'abd', 'abdel', 'ali', 'khan', 'singh', 'kumar', 'sayed',
    'sayyed', 'syed', 'bin', 'ibn', 'the', 'and',
}

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

Plan = env['account.analytic.plan']
Analytic = env['account.analytic.account']
SscEmployee = env['ssc.employee']
HrEmployee = env['hr.employee']
Payslip = env['ssc.payslip']

plan = Plan.search([('name', '=', PLAN_NAME), ('parent_id', '=', False)], limit=1)
if not plan:
    raise SystemExit("No root analytic plan named %r." % PLAN_NAME)

accounts = Analytic.search([('root_plan_id', '=', plan.id)])
employees = SscEmployee.search([])
print("%s account(s) in %r, %s employee(s)" % (len(accounts), plan.name, len(employees)))


def norm(code):
    """A code compared as a whole: SSCLLC-122 is not 122."""
    return (code or '').strip().upper().replace(' ', '')


def words(name):
    return {w for w in re.findall(r"[a-z]+", (name or '').lower())
            if len(w) > 2 and w not in COMMON}


def names_agree(left, right):
    """True when two names share a word specific enough to mean one person."""
    return bool(words(left) & words(right))


by_code = defaultdict(list)
by_name = defaultdict(list)
for employee in employees:
    if employee.employee_code:
        by_code[norm(employee.employee_code)].append(employee)
    key = " ".join(sorted(words(employee.name)))
    if key:
        by_name[key].append(employee)

to_link = {}          # hr.employee -> account
refused_name = []
ambiguous = []
no_match = []
no_hr = []
conflict = []
already = 0
claimed = {}          # hr.employee id -> the account that claimed it

for account in accounts:
    key = norm(account.code)
    candidates = by_code.get(key) or [] if key else []
    how = "code"
    if not candidates and NAME_MATCH and not key:
        candidates = by_name.get(" ".join(sorted(words(account.name)))) or []
        how = "name"
    if not candidates:
        no_match.append("%-18s %s" % (account.code or '(no code)', account.name))
        continue
    if len(candidates) > 1:
        ambiguous.append("%-18s %s -> %s"
                         % (account.code or '(no code)', account.name,
                            ", ".join(e.display_name for e in candidates)))
        continue
    employee = candidates[0]
    # The check that was missing, and that refuses one real mismatch here.
    if how == "code" and not names_agree(account.name, employee.name):
        refused_name.append("%-18s %-42s vs employee %s"
                            % (account.code, account.name[:42], employee.name))
        continue
    hr_employee = employee.hr_employee_id
    if not hr_employee:
        no_hr.append("%s -> %s" % (account.display_name, employee.display_name))
        continue
    current = hr_employee.ssc_analytic_account_id
    if current == account:
        already += 1
        continue
    if current:
        conflict.append("%s already points at %s, not %s"
                        % (hr_employee.display_name, current.display_name,
                           account.display_name))
        continue
    # Two accounts must never claim one employee. Exact-code matching does not
    # produce this on today's data; asserting it keeps that true tomorrow.
    if hr_employee.id in claimed:
        ambiguous.append("%s and %s both claim %s"
                         % (claimed[hr_employee.id].code, account.code,
                            hr_employee.display_name))
        to_link.pop(hr_employee, None)
        continue
    claimed[hr_employee.id] = account
    to_link[hr_employee] = account

for hr_employee, account in sorted(to_link.items(), key=lambda kv: kv[0].name or ''):
    print("  %-46s -> %s" % (hr_employee.name, account.display_name))
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
print("%s link(s) %s, %s already correct."
      % (len(to_link), "written" if APPLY else "to write", already))
report("REFUSED - the code matches but the names have nothing in common",
       refused_name)
report("More than one employee claims this account - NOT written", ambiguous)
report("Employees with no hr.employee behind them - NOT written", no_hr)
report("Already pointing somewhere else - NOT overwritten", conflict)
report("Accounts reaching no employee", no_match, limit=10)
if not NAME_MATCH:
    codeless = len([a for a in accounts if not norm(a.code)])
    if codeless:
        print()
        print("%s account(s) carry no code at all and were not matched. Re-run "
              "with NAME_MATCH=1 to" % codeless)
        print("link those by an unambiguous full name.")

# The only number that decides anything: not how many employees exist, but how
# many of the people actually being paid now carry a dimension.
print()
print("=" * 100)
print("WHAT THIS MEANS FOR A SALARY ENTRY")
print("=" * 100)
paid = Payslip.search([], order='id desc', limit=2000).mapped('employee_id')
linked_ids = {hr.id for hr in to_link} | {
    e.hr_employee_id.id for e in paid
    if e.hr_employee_id and e.hr_employee_id.ssc_analytic_account_id}
reached = [e for e in paid if e.hr_employee_id and e.hr_employee_id.id in linked_ids]
print("%s employee(s) on the last 2000 payslips" % len(paid))
print("%s of them carry an analytic account %s"
      % (len(reached), "" if APPLY else "once this is applied"))
missing = [e for e in paid if e not in reached]
print("%s do not: their share of an entry carries the project but not the "
      "employee," % len(missing))
print("and the batch's chatter names the amount rather than losing it.")
report("Paid employees still with no analytic account",
       ["%s [%s]" % (e.name, e.employee_code or 'no code') for e in missing],
       limit=15)

if APPLY:
    env.cr.commit()
    print("\nCommitted.")
else:
    env.cr.rollback()
    print("\nDRY RUN - nothing was written. Re-run with APPLY=1 to apply.")
