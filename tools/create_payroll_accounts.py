"""The two payroll accounts the sister companies are missing, in their own charts.

    cd ~/src/user

    # report only, writes nothing - read this first:
    odoo-bin shell -d <database> --no-http < tools/create_payroll_accounts.py

    # one company at a time:
    SSC_COMPANY="ROYAL ARROW" SSC_APPLY=1 odoo-bin shell ...

    # all of them:
    SSC_APPLY=1 odoo-bin shell ...

Three of the four companies can already say where a basic salary and a salary
liability go, but none of them has an account for OVERTIME, and two have none
for ADMINISTRATIVE salaries. Without those two, splitting labour from staff
buys nothing: everything lands on basic salary.

Creating them has to happen inside each company's own chart, which is not the
chart the others use. Read the first section before believing anything: it
names the account each role resolves to, its id, and the other companies it is
shared with, because an account shared between companies is legitimate in 19.0
and means there is nothing to create - only something to point at.

Codes cannot be compared between these charts: 400011 is "Salary Additions" in
SAUD and "Sales Commission" in MALAK and ROYAL WOODEN, and 500003 carries
SAUD's administrative salaries but is "Management Consultancy Fees" elsewhere.
So this tool - and the mapping in tools/split_labour_staff_payroll.py - work by
ACCOUNT NAME inside one company, never by code across companies.

What it creates, only where it is missing:

  * "Salary Additions" (expense), for overtime, numbered just after that
    company's own basic salary account;
  * "Salaries & Allowances" (expense), for administrative salaries, placed in
    the company's 5-series if it has one - administrative expense does not
    belong in a 4-series direct cost group - and next to basic salary if not.
    Only for a company that actually has staff.

It never touches an account that already exists, and never touches SAUD, which
has both already.

In the interface
----------------
The only thing this writes is an account:

  * Accounting > Configuration > Chart of Accounts > New

Nothing here inherits, patches or extends a native model. It is the same form
an accountant would fill in, with the code read off that company's own chart
rather than typed from memory.

Reads only unless SSC_APPLY=1.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'
ONLY_COMPANY = (os.environ.get('SSC_COMPANY') or '').strip().lower()

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92

# The name each role goes by. First one is what gets created when missing.
ROLE_NAMES = {
    'basic': ('Basic Salary',),
    'overtime': ('Over Time Allowance', 'Overtime Allowance', 'Salary Additions',
                 'Salary Additions - Overtime', 'Overtime'),
    'staff_salary': ('Staff Salaries & Allowances', 'Salaries & Allowances',
                     'Staff Salaries'),
    'payable': ('Salary Payable', 'Accrued - Salaries', 'Accrued Salaries'),
}

# A company whose administrative expenses live in a group of their own, named
# by the prefix that group starts with. Everything else falls back to sitting
# beside the company's own basic salary account.
ADMIN_GROUP = {
    'royal arrow': '420',
}

# The kind of account each role must be. A name alone is not enough: ROYAL
# ARROW carries a "Basic Salary" and a "Salary Additions" that are NOT expense
# accounts, next to the real ones in its 410xxxx payroll group, and matching on
# the name alone picked the wrong pair without a murmur.
ROLE_TYPES = {
    'basic': 'expense',
    'overtime': 'expense',
    'staff_salary': 'expense',
    'payable': 'liability',
}


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def short(text, size=40):
    text = text or '-'
    return text if len(text) <= size else text[:size - 1] + '.'


Account = env['account.account'].sudo() if 'account.account' in env else None
Version = env['hr.version'].sudo() if 'hr.version' in env else None
SscEmployee = env['ssc.employee'].sudo() if 'ssc.employee' in env else None
Company = env['res.company'].sudo()

if Account is None:
    title("nothing to do")
    print("  accounting is not installed on this database.")
else:
    multi = 'company_ids' in Account._fields

    def scope(company):
        return ([('company_ids', 'in', company.id)] if multi
                else [('company_id', '=', company.id)])

    def pick(candidates, company):
        """Which namesake the books actually use.

        ROYAL ARROW has two expense accounts called "Basic Salary": 4101001,
        in its payroll group beside House Allowance and Over Time Allowance,
        carrying thirteen entries - and another carrying none. An account with
        history is the one the ledger means; a duplicate with no entries is a
        leftover. Ties fall back to the lower code.
        """
        if len(candidates) < 2:
            return candidates[:1]
        Line = env['account.move.line'].sudo()
        with_history = [(Line.search_count([('account_id', '=', a.id)]),
                         a.with_company(company).code or '', a)
                        for a in candidates]
        with_history.sort(key=lambda row: (-row[0], row[1]))
        return with_history[0][2]

    def by_name(name, company, kind):
        # Three conditions, and the third is the one that matters. `code` is
        # company-dependent in 19.0, so an account belonging to another company
        # reads back with NO code here - and that is the proof it is not in
        # this chart. Filtering on company_ids alone let SAUD's "Basic Salary"
        # answer for ROYAL ARROW, whose own is 4101001 and carries 13 entries.
        found = Account.with_company(company).search(
            scope(company) + [('name', '=ilike', name),
                              ('active', '=', True),
                              ('account_type', 'like', kind)])
        found = found.filtered(lambda a, c=company: a.with_company(c).code)
        return pick(found, company)

    def by_role(role, company):
        for name in ROLE_NAMES[role]:
            found = by_name(name, company, ROLE_TYPES[role])
            if found:
                return found
        return Account.browse()

    def by_code(code, company):
        return Account.with_company(company).search(
            scope(company) + [('code', '=', code)], limit=1)

    def code_of(account, company):
        return account.with_company(company).code if account else None

    # Codes planned in this run but not created yet. Without this the second
    # account of a company is offered the same number as the first, because
    # neither exists in the chart while the plan is being drawn up.
    reserved = set()

    def next_free(code, company):
        """The first unused code after this one, keeping its shape."""
        if not code:
            return None
        digits = ''
        while code and code[-1].isdigit():
            digits = code[-1] + digits
            code = code[:-1]
        if not digits:
            return None
        for step in range(1, 500):
            candidate = f"{code}{str(int(digits) + step).zfill(len(digits))}"
            if (company.id, candidate) in reserved:
                continue
            if not by_code(candidate, company):
                reserved.add((company.id, candidate))
                return candidate
        return None

    def admin_seed(company, basic):
        """Where an administrative expense belongs in this chart.

        A chart that keeps its administrative expenses in a group of their own
        gets the new account there - putting an administrative salary in the
        group that carries direct labour is exactly what the split undoes.
        Returns (code to count from, whether the group is an administrative one).
        """
        # Charts that name their administrative group by prefix rather than by
        # a 5-series. ROYAL ARROW keeps employee cost in 4101xxx, direct project
        # cost in 430xxxx, and general administration - bank charges, audit fee,
        # maintenance - in 420xxxx, which is where an office salary belongs.
        for fragment, prefix in ADMIN_GROUP.items():
            if fragment in (company.name or '').lower():
                group = Account.with_company(company).search(
                    scope(company) + [('account_type', 'like', 'expense')])
                group = group.filtered(
                    lambda a, c=company, p=prefix: (code_of(a, c) or '').startswith(p))
                if group:
                    highest = max(group, key=lambda a, c=company: code_of(a, c) or '')
                    return code_of(highest, company), True
        # Not ('account_type', '=', 'expense'): Odoo splits expenses across
        # several types - expense, expense_direct_cost, expense_depreciation -
        # and asking for the bare one hid a whole 5-series that was there all
        # along.
        expenses = Account.with_company(company).search(
            scope(company) + [('account_type', 'like', 'expense')])
        fives = expenses.filtered(
            lambda a, c=company: (code_of(a, c) or '').startswith('5'))
        if fives:
            highest = max(fives, key=lambda a, c=company: code_of(a, c) or '')
            return code_of(highest, company), True
        return code_of(basic, company), False

    # ------------------------------------------------------------------
    title("1. what each company has today")

    companies = Company.search([])
    if ONLY_COMPANY:
        companies = companies.filtered(lambda c: ONLY_COMPANY in (c.name or '').lower())
        print(f"  restricted to companies matching {ONLY_COMPANY!r}\n")

    staff_hr = Version.browse()
    if SscEmployee is not None and Version is not None:
        flagged = SscEmployee.search([('is_engineer_office', '=', True),
                                      ('hr_employee_id', '!=', False)])
        staff_hr = Version.search([('employee_id', 'in', flagged.hr_employee_id.ids)])

    plan = []
    for company in companies:
        if Version is not None and not Version.search_count([('company_id', '=', company.id)]):
            continue
        has_staff = bool(staff_hr.filtered(lambda v, c=company: v.company_id == c))
        roles = {role: by_role(role, company) for role in ROLE_NAMES}
        print(f"\n  {company.name}")
        for role in ('basic', 'overtime', 'staff_salary', 'payable'):
            account = roles[role]
            if role == 'staff_salary' and not has_staff:
                print(f"      {role:<13} not needed - no staff in this company")
                continue
            if not account:
                print(f"      {role:<13} MISSING")
                continue
            # Who else may post to it. An account shared between companies is
            # legitimate in 19.0, and it changes the answer entirely: there is
            # nothing to create, only something to point at.
            owners = account.company_ids if multi else account.company_id
            others = owners - company
            print(f"      {role:<13} [{account.id}] {code_of(account, company)} "
                  f"{account.name}"
                  + (f"   shared with: {', '.join(short(o.name, 26) for o in others)}"
                     if others else ""))
        wanted = []
        if not roles['overtime'] and roles['basic']:
            wanted.append(('overtime',
                           next_free(code_of(roles['basic'], company), company), True))
        if has_staff and not roles['staff_salary']:
            seed, in_admin_range = admin_seed(company, roles['basic'])
            wanted.append(('staff_salary', next_free(seed, company), in_admin_range))
        if not roles['basic'] or not roles['payable']:
            print("      !! no basic salary or no salary liability under a name this")
            print("         tool knows - it will not invent those two. Add them by")
            print("         hand, or tell me the names they go by here.")
            wanted = []
        plan.append({'company': company, 'roles': roles, 'wanted': wanted,
                     'has_staff': has_staff})

    # ------------------------------------------------------------------
    title("2. what would be created")

    anything = False
    for entry in plan:
        company = entry['company']
        if not entry['wanted']:
            print(f"  {short(company.name):<40} nothing to create")
            continue
        anything = True
        for role, code, placed_well in entry['wanted']:
            name = ROLE_NAMES[role][0]
            print(f"  {short(company.name):<40} {code or '(no free code)'} {name} "
                  f"(expense)")
            if role == 'staff_salary' and not placed_well:
                print(f"  {'':<40} !! this chart has no 5-series, so an")
                print(f"  {'':<40}    administrative salary would sit in the")
                print(f"  {'':<40}    direct cost range. Say the code you want.")
    if not anything:
        print("\n  every company already has the accounts the payroll needs.")

    if not APPLY:
        env.cr.rollback()
        print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to create,")
        print("one company at a time with SSC_COMPANY=... while you watch it.")
    else:
        written = []
        for entry in plan:
            company = entry['company']
            for role, code, _placed in entry['wanted']:
                if not code:
                    written.append(f"{short(company.name, 30)}: no free code near its "
                                   f"own accounts for {ROLE_NAMES[role][0]!r} - skipped")
                    continue
                vals = {'name': ROLE_NAMES[role][0], 'code': code,
                        'account_type': 'expense'}
                if multi:
                    vals['company_ids'] = [(6, 0, [company.id])]
                else:
                    vals['company_id'] = company.id
                account = Account.with_company(company).create(vals)
                written.append(f"{short(company.name, 30)}: {code} {account.name}")
        env.cr.commit()
        print("\nwritten:")
        for line in written or ['(nothing)']:
            print(f"  . {line}")
        print("\nnext: tools/split_labour_staff_payroll.py now finds these by name")
        print("and puts them on the rules - report first, then SSC_APPLY=1.")
