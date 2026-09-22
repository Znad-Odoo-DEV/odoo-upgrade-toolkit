"""What shape are the badges, really - on the employee and on the analytic account.

    odoo-bin shell -d <database> --no-http < tools/probe_employee_codes.py

Read only. Nothing is written, ever.

The first attempt at linking employees to their analytic accounts matched on the
digits at the end of the analytic code, and paired people who have nothing to do
with each other: [122] is Arunkumar Ganesan and [SSCLLC-122] is Abdul Ghaffar
Muhammad Yar. The prefix is not decoration - it is part of the identity, and two
series carry the same number.

So before writing any link: print both sides as they actually are, and count how
far an exact match gets before anything clever is tried.
"""
import re
from collections import Counter, defaultdict

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

Plan = env['account.analytic.plan']
Analytic = env['account.analytic.account']
SscEmployee = env['ssc.employee']
HrEmployee = env['hr.employee']

PLAN_NAME = 'Salaries & Wages'


def title(text):
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


plan = Plan.search([('name', '=', PLAN_NAME), ('parent_id', '=', False)], limit=1)
accounts = Analytic.search([('root_plan_id', '=', plan.id)])
employees = SscEmployee.search([])

# ----------------------------------------------------------------------
title("1. THE SHAPE OF THE CODES ON EACH SIDE")
# ----------------------------------------------------------------------


def shape(code):
    """A code with its digits collapsed, so the families show up: SSCLLC-122
    and SSCLLC-9 are both 'SSCLLC-N'."""
    return re.sub(r'\d+', 'N', (code or '').strip()) or '(empty)'


print("analytic account codes in %r (%s accounts):" % (plan.name, len(accounts)))
for form, count in Counter(shape(a.code) for a in accounts).most_common():
    print("    %-24s %s" % (form, count))

print()
print("ssc.employee.employee_code (%s employees):" % len(employees))
for form, count in Counter(shape(e.employee_code) for e in employees).most_common():
    print("    %-24s %s" % (form, count))

print()
print("Examples side by side:")
for acc in accounts[:6]:
    print("    analytic %-16r %s" % (acc.code, acc.name))
for emp in employees[:6]:
    print("    employee %-16r %s  [company %s]"
          % (emp.employee_code, emp.name, emp.company_id.name))

# ----------------------------------------------------------------------
title("2. HOW FAR DOES AN EXACT CODE MATCH GET")
# ----------------------------------------------------------------------


def norm(code):
    return (code or '').strip().upper().replace(' ', '')


by_code = defaultdict(list)
for emp in employees:
    if emp.employee_code:
        by_code[norm(emp.employee_code)].append(emp)

exact = collide = miss = 0
for acc in accounts:
    key = norm(acc.code)
    if not key:
        continue
    found = by_code.get(key) or []
    if len(found) == 1:
        exact += 1
    elif len(found) > 1:
        collide += 1
    else:
        miss += 1
print("exact, one employee : %s" % exact)
print("exact, several      : %s" % collide)
print("no exact match      : %s" % miss)

# ----------------------------------------------------------------------
title("3. DO THE NAMES AGREE WHEN THE CODE DOES")
# ----------------------------------------------------------------------
# A code match whose names share no word is not a match at all. This is the
# check the account tool has and the employee tool did not.
STOP = {'mohammad', 'mohamed', 'md', 'muhammad', 'abdul', 'abd', 'ali', 'ahmed',
        'ahmad', 'khan', 'singh', 'al', 'bin', 'ibn'}


def tokens(name):
    return {w for w in re.findall(r"[a-z]+", (name or '').lower())
            if len(w) > 2 and w not in STOP}


agree = disagree = 0
samples = []
for acc in accounts:
    key = norm(acc.code)
    found = by_code.get(key) or []
    if len(found) != 1:
        continue
    shared = tokens(acc.name) & tokens(found[0].name)
    if shared:
        agree += 1
    else:
        disagree += 1
        if len(samples) < 20:
            samples.append("%-18r %-40s  vs employee  %s"
                           % (acc.code, acc.name[:40], found[0].name))
print("code matches where the names share a word : %s" % agree)
print("code matches where they share NOTHING     : %s" % disagree)
for line in samples:
    print("    ", line)

# ----------------------------------------------------------------------
title("4. NAME MATCHING ON ITS OWN, FOR THE ONES THE CODE CANNOT REACH")
# ----------------------------------------------------------------------
by_name = defaultdict(list)
for emp in employees:
    key = " ".join(sorted(tokens(emp.name)))
    if key:
        by_name[key].append(emp)

reachable = ambiguous = unreachable = 0
for acc in accounts:
    if by_code.get(norm(acc.code)):
        continue
    key = " ".join(sorted(tokens(acc.name)))
    found = by_name.get(key) or []
    if len(found) == 1:
        reachable += 1
    elif len(found) > 1:
        ambiguous += 1
    else:
        unreachable += 1
print("no code match, but exactly one employee of that name : %s" % reachable)
print("no code match, several employees of that name        : %s" % ambiguous)
print("no code match and no name match                      : %s" % unreachable)

# ----------------------------------------------------------------------
title("5. WHO ACTUALLY GETS PAID")
# ----------------------------------------------------------------------
# 346 accounts and 493 hr.employee records is not the question. The question is
# how many of the people on a recent payslip can be reached.
Payslip = env['ssc.payslip']
recent = Payslip.search([], order='id desc', limit=2000)
paid_employees = recent.mapped('employee_id')
print("%s payslip(s) read, %s distinct employee(s) on them"
      % (len(recent), len(paid_employees)))

reached = 0
no_code = []
no_account = []
no_hr = []
for emp in paid_employees:
    if not emp.hr_employee_id:
        no_hr.append(emp.display_name)
        continue
    if not emp.employee_code:
        no_code.append(emp.display_name)
        continue
    found = [a for a in accounts if norm(a.code) == norm(emp.employee_code)]
    if len(found) == 1 and (tokens(found[0].name) & tokens(emp.name)):
        reached += 1
    else:
        no_account.append("%s [%s]" % (emp.display_name, emp.employee_code))

print()
print("of those, reachable by exact code AND agreeing name : %s" % reached)
print("with no hr.employee                                 : %s" % len(no_hr))
print("with no employee code                               : %s" % len(no_code))
print("with no analytic account that agrees                : %s" % len(no_account))
for item in no_account[:20]:
    print("    ", item)
if len(no_account) > 20:
    print("     ... and %s more" % (len(no_account) - 20))

print("\nDone. Read only - nothing was written.")
