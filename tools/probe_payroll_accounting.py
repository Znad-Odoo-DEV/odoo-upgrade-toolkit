"""What the salary journal entry has to be built on, read out of the database.

    odoo-bin shell -d <database> --no-http < tools/probe_payroll_accounting.py

Read only. Nothing is written, ever.

Three questions the Studio button answered by guessing, and that the native
button must answer from configuration:

1. Which analytic plans exist, which are mandatory, and which plan the project
   accounts sit in. Odoo 19 validates analytic_distribution per ROOT plan -
   every mandatory root plan must total exactly 100 - so employee accounts and
   project accounts in the same root plan cannot both be put on one line.
2. Which journal each company posts salaries to.
3. Which GL accounts exist per company for each leg of the entry. Codes are
   company-dependent and no two charts here agree on a number, so every account
   is resolved inside its own company's context and printed with its type.
"""
from collections import defaultdict

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

Plan = env['account.analytic.plan'].sudo()
Analytic = env['account.analytic.account'].sudo()
Account = env['account.account'].sudo()
Journal = env['account.journal'].sudo()
Company = env['res.company'].sudo()
Project = env['project.project'].sudo()
Move = env['account.move'].sudo()


def title(text):
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


companies = Company.search([])

# ----------------------------------------------------------------------
title("1. ANALYTIC PLANS")
# ----------------------------------------------------------------------
plans = Plan.search([])
print(f"{len(plans)} plan(s)\n")
for plan in plans.filtered(lambda p: not p.parent_id):
    n = Analytic.search_count([('root_plan_id', '=', plan.id)])
    print(f"ROOT  {plan.name!r:<40} id={plan.id:<4} "
          f"default_applicability={plan.default_applicability:<10} accounts={n}")
    for rule in plan.applicability_ids:
        print(f"        rule: applicability={rule.applicability} "
              f"business_domain={rule.business_domain} "
              f"account_prefix={rule.account_prefix or '-'} "
              f"product_categ={rule.product_categ_id.display_name or '-'}")
    for child in plans.filtered(lambda p: p.parent_id == plan):
        cn = Analytic.search_count([('plan_id', '=', child.id)])
        print(f"      child {child.name!r:<36} id={child.id:<4} accounts={cn}")

mandatory = plans.filtered(
    lambda p: not p.parent_id and p.default_applicability == 'mandatory')
print(f"\nMANDATORY root plans: "
      f"{[p.name for p in mandatory] or 'none by default'}")
print("A line must total exactly 100% inside EACH mandatory root plan.")

# ----------------------------------------------------------------------
title("2. WHERE PROJECT AND EMPLOYEE ANALYTIC ACCOUNTS LIVE")
# ----------------------------------------------------------------------
projects = Project.search([])
proj_accounts = projects.mapped('account_id')
print(f"{len(projects)} project(s), {len(proj_accounts)} distinct analytic account(s)")
by_plan = defaultdict(list)
for acc in proj_accounts:
    by_plan[(acc.root_plan_id.id, acc.root_plan_id.name)].append(acc.display_name)
for (pid, pname), names in by_plan.items():
    print(f"  root plan {pname!r} (id={pid}): {len(names)} project account(s)")
    for nm in sorted(names)[:8]:
        print(f"      {nm}")
    if len(names) > 8:
        print(f"      ... and {len(names) - 8} more")

print()
no_account = projects.filtered(lambda p: not p.account_id)
print(f"Projects with NO analytic account: {len(no_account)}")
for p in no_account[:15]:
    print(f"      {p.display_name} [{p.company_id.name}]")

print()
# Employee-named analytic accounts: the Studio code searched these by employee
# name, so look for accounts that are not a project's.
non_project = Analytic.search([('id', 'not in', proj_accounts.ids)])
by_plan2 = defaultdict(int)
for acc in non_project:
    by_plan2[(acc.root_plan_id.id, acc.root_plan_id.name)] += 1
print(f"{len(non_project)} analytic account(s) that are NOT a project's:")
for (pid, pname), count in by_plan2.items():
    print(f"  root plan {pname!r} (id={pid}): {count}")
    sample = non_project.filtered(lambda a: a.root_plan_id.id == pid)[:8]
    for acc in sample:
        print(f"      {acc.display_name} [{acc.company_id.name or 'no company'}]")

# ----------------------------------------------------------------------
title("3. JOURNALS PER COMPANY")
# ----------------------------------------------------------------------
for company in companies:
    journals = Journal.with_company(company).search(
        [('company_id', '=', company.id), ('type', '=', 'general')])
    print(f"\n{company.name}  (id={company.id}, currency={company.currency_id.name})")
    for j in journals:
        print(f"      {j.code:<8} {j.name!r:<40} type={j.type} id={j.id}")

# ----------------------------------------------------------------------
title("4. CANDIDATE GL ACCOUNTS PER COMPANY")
# ----------------------------------------------------------------------
# Names, not codes: 400011 is "Salary Additions" in one chart and
# "Sales Commission" in another.
WANTED = [
    'basic', 'salar', 'housing', 'accommodation', 'transport', 'travel',
    'overtime', 'allowance', 'leave', 'advance', 'phone', 'telephone',
    'bonus', 'sick', 'medical', 'ticket', 'penalt', 'fine', 'deduction',
    'gratuity', 'end of service', 'payable', 'wages',
]
for company in companies:
    print(f"\n--- {company.name} ---")
    accounts = Account.with_company(company).search(
        [('company_ids', 'in', company.id)])
    hits = accounts.filtered(
        lambda a: any(w in (a.name or '').lower() for w in WANTED))
    if not hits:
        print("      (no matching account names)")
    for acc in hits.sorted(lambda a: a.code or ''):
        print(f"      {(acc.code or '-'):<10} {acc.name[:52]:<54} "
              f"{acc.account_type}")

# ----------------------------------------------------------------------
title("5. WHAT THE STUDIO BUTTON ACTUALLY PRODUCED")
# ----------------------------------------------------------------------
je = Move.search([('ref', 'like', 'JE-')], limit=10, order='id desc')
je |= Move.search([('name', 'like', 'JE-')], limit=10, order='id desc')
print(f"{len(je)} move(s) whose name/ref looks like the Studio output\n")
for mv in je[:6]:
    print(f"  {mv.name}  ref={mv.ref!r}  type={mv.move_type}  "
          f"journal={mv.journal_id.code}  partner={mv.partner_id.display_name}  "
          f"state={mv.state}  total={mv.amount_total}  [{mv.company_id.name}]")
    for line in mv.line_ids:
        print(f"        {(line.account_id.code or '-'):<10} "
              f"{(line.name or '')[:40]:<42} "
              f"Dr {line.debit:>12,.2f}  Cr {line.credit:>12,.2f}  "
              f"analytic={line.analytic_distribution}")
    print()

print("\nDone. Read only - nothing was written.")
