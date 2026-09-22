"""The provision and deduction accounts the localisation rules ask for.

    cd ~/src/user

    # report only, writes nothing - read this first:
    odoo-bin shell -d <database> --no-http < tools/create_localisation_accounts.py

    # one company at a time:
    SSC_COMPANY="ROYAL ARROW" SSC_APPLY=1 odoo-bin shell ...

    # all of them, once the first has been read on screen:
    SSC_APPLY=1 odoo-bin shell ...

tools/map_localisation_accounts.py names the roles no chart could answer for.
Four of them are worth an account; two are not, and this tool says so out loud
rather than inventing them.

    deduction         MALAK, ROYAL WOODEN     AEUNPAID, SL50, SL0 and OOC all
                                              credit it. Without it four rules
                                              cut the net pay and leave no
                                              trace in the ledger.
    leave_provision   ROYAL ARROW, MALAK,     ALP accrues annual leave every
                      ROYAL WOODEN            month; the credit side is the
                                              liability it accrues into.
    eos_provision     SAUD, ROYAL ARROW       end of service is a legal debt
    eos_expense       all four                from the first day worked, and
                                              EOSP accrues it monthly - 21 days
                                              a year up to five years, a month
                                              after. With no accounts the
                                              balance sheet hides a real and
                                              growing liability.

    advance           ROYAL ARROW, MALAK,     deliberately NOT created: no
                      ROYAL WOODEN            salary advance has ever gone
                                              through Odoo in those three, and
                                              there is no asset account to
                                              number a new one against. ADVREC
                                              keeps an empty field, and an
                                              empty field produces no line.

    other_allowance   ROYAL ARROW             deliberately NOT created: that
                                              chart merges it into 4101004
                                              "Transportation & Other
                                              Allowance" on purpose. The name
                                              was added to the role's
                                              alternatives in
                                              tools/map_localisation_accounts.py
                                              instead.

Names, codes, types
-------------------
The names are the ones tools/map_localisation_accounts.py already looks for, so
what is created here is exactly what that tool finds on the next run. A name of
my own choosing would buy nothing and would have to be taught to the mapping.

Codes come from each company's own chart and never from another's - 400011 is
"Salary Additions" in SAUD and "Sales Commission" in MALAK. An expense is
numbered from the company's own basic salary account; a provision from a
provision that chart already keeps, and only from its salary payable if it
keeps none. The first free number after the seed wins, keeping the seed's
shape, so ROYAL ARROW gets a 7-digit code and MALAK a 6-digit one without being
told which.

The account TYPE is the one thing read across charts, because a type carries no
number: it cannot be misread the way 400011 can. An account is given the same
type its namesake already has in a sister company - MALAK's own "End of Service
Provision" has already settled what an end of service provision is here - and
falls back to a default only if no sister keeps one.

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

# The same vocabulary tools/map_localisation_accounts.py resolves by. Anything
# created here has to answer to one of these names, or the mapping will not
# see it on the next run.
ROLE_NAMES = {
    'basic': ('Basic Salary',),
    'payable': ('Salary Payable', 'Accrued - Salaries', 'Accrued Salaries'),
    'deduction': ('Salary Deduction',),
    'leave_provision': ('Provision - Leave Salaries', 'Provision - Leave Salary'),
    'eos_provision': ('Provision - End of Service', 'End of Service Provision',
                      'Provision - Gratuity'),
    'eos_expense': ('End of Service Expense', 'End of Service Benefits',
                    'Gratuity Expense'),
}

# The kind each role must be when one is looked up. Deduction is the single
# role read loosely: a chart may call it an expense, an other income or a
# contra - what matters is its name.
ROLE_TYPES = {
    'basic': 'expense',
    'payable': 'liability',
    'deduction': None,
    'leave_provision': 'liability',
    'eos_provision': 'liability',
    'eos_expense': 'expense',
}

# role -> (name to create, where to number it from, type if no sister has one)
CREATE = {
    'deduction': ('Salary Deduction', 'salary', 'income_other'),
    'leave_provision': ('Provision - Leave Salaries', 'provision', 'liability_current'),
    'eos_provision': ('End of Service Provision', 'provision', 'liability_current'),
    'eos_expense': ('End of Service Expense', 'salary', 'expense'),
}
ORDER = ('deduction', 'leave_provision', 'eos_provision', 'eos_expense')

# Named in the report, never created. See the docstring.
DECLINED = (
    ('advance', "no advance has gone through Odoo in these three, and no asset "
                "account to number one against"),
    ('other_allowance', "ROYAL ARROW merges it into Transportation & Other "
                        "Allowance on purpose"),
)


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def short(text, size=40):
    text = text or '-'
    return text if len(text) <= size else text[:size - 1] + '.'


Structure = env['hr.payroll.structure'].sudo() if 'hr.payroll.structure' in env else None
Account = env['account.account'].sudo() if 'account.account' in env else None
Line = env['account.move.line'].sudo() if 'account.move.line' in env else None

if Structure is None or Account is None:
    title("nothing to do")
    print("  payroll or accounting is not installed on this database.")
else:
    multi = 'company_ids' in Account._fields

    def scope(company):
        return ([('company_ids', 'in', company.id)] if multi
                else [('company_id', '=', company.id)])

    def code_of(account, company):
        return (account.with_company(company).code or '') if account else ''

    def entries(account):
        if Line is None:
            return 0
        return Line.search_count([('account_id', '=', account.id)])

    def by_role(role, company):
        """The account playing that role inside this company, by name and kind.

        The same three conditions as the mapping tool, and the third is the one
        that matters: `code` is company-dependent in 19.0, so an account
        belonging to another chart reads back with NO code here. Archived
        accounts are excluded - these tools run with active_test off, and an
        old archived duplicate is exactly what leaked SAUD's codes into ROYAL
        ARROW's roles once already.
        """
        kind = ROLE_TYPES[role]
        for name in ROLE_NAMES[role]:
            domain = scope(company) + [('name', '=ilike', name),
                                       ('active', '=', True)]
            if kind:
                domain += [('account_type', 'like', kind)]
            found = Account.with_company(company).search(domain)
            found = found.filtered(lambda a, c=company: code_of(a, c))
            if not found:
                continue
            if len(found) == 1:
                return found
            scored = [(entries(a), code_of(a, company), a) for a in found]
            scored.sort(key=lambda row: (-row[0], row[1]))
            return scored[0][2]
        return Account.browse()

    def type_from_sisters(role):
        """What kind of account the other charts already say this is.

        Where a sister company already keeps an "End of Service Provision", it
        has answered the question, and the namesake carrying journal entries
        answers it best. Returns (entries, type, account) or None.
        """
        best = None
        for name in ROLE_NAMES[role]:
            for account in Account.search([('name', '=ilike', name),
                                           ('active', '=', True)]):
                score = entries(account)
                if best is None or score > best[0]:
                    best = (score, account.account_type, account)
        return best

    def by_code(code, company):
        return Account.with_company(company).search(
            scope(company) + [('code', '=', code)], limit=1)

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

    def seed_for(role, company, roles):
        """Which account this one is numbered from, and why.

        A provision belongs beside the provisions, not beside the payable it
        will one day settle into - so a chart already keeping one provision
        gets the new one next to it, and only a chart keeping none falls back
        to its salary payable.
        """
        if CREATE[role][1] == 'salary':
            return roles['basic'], "beside its own basic salary"
        for other in ('eos_provision', 'leave_provision'):
            if other != role and roles.get(other):
                return roles[other], (f"beside {code_of(roles[other], company)} "
                                      f"{roles[other].name}")
        return roles['payable'], "beside its own salary payable"

    # ------------------------------------------------------------------
    title("1. what each chart has for these roles today")

    structures = Structure.search([]).filtered(
        lambda s: (s.name or '').endswith(' Labour Pay')
        or (s.name or '').endswith(' Staff Pay'))
    companies = structures.journal_id.company_id
    if ONLY_COMPANY:
        companies = companies.filtered(
            lambda c: ONLY_COMPANY in (c.name or '').lower())
        print(f"  restricted to companies matching {ONLY_COMPANY!r}")

    resolved = {}
    for company in companies:
        print(f"\n  {company.name}")
        for role in ('basic', 'payable') + ORDER:
            account = by_role(role, company)
            resolved[(company.id, role)] = account
            print(f"      {role:<18} "
                  + (f"{code_of(account, company):<9} {account.name[:34]}" if account
                     else "MISSING"))

    # ------------------------------------------------------------------
    title("2. the kind of account each new one will be")

    kinds = {}
    for role in ORDER:
        name, _seed, fallback = CREATE[role]
        found = type_from_sisters(role)
        if found:
            kinds[role] = found[1]
            print(f"  {name:<30} {found[1]:<18} as in {short(found[2].name, 34)} "
                  f"({found[0]} entries)")
        else:
            kinds[role] = fallback
            print(f"  {name:<30} {fallback:<18} no sister chart keeps one - default")

    # ------------------------------------------------------------------
    title("3. what would be created")

    plan = []
    for company in companies:
        roles = {role: resolved[(company.id, role)]
                 for role in ('basic', 'payable') + ORDER}
        print(f"\n  {company.name}")
        if not roles['basic'] or not roles['payable']:
            print("      !! no basic salary or no salary payable under a name this")
            print("         tool knows - it will not number anything against a")
            print("         guess. Add those two by hand first.")
            continue
        wanted = []
        for role in ORDER:
            if roles[role]:
                continue
            seed, why = seed_for(role, company, roles)
            wanted.append((role, next_free(code_of(seed, company), company), why))
        plan.append({'company': company, 'wanted': wanted})
        if not wanted:
            print("      nothing to create")
        for role, code, why in wanted:
            print(f"      {code or '(no free code)':<9} {CREATE[role][0]:<30} "
                  f"{kinds[role]:<18} {why}")

    # ------------------------------------------------------------------
    title("summary")

    total = sum(len(entry['wanted']) for entry in plan)
    for entry in plan:
        print(f"  {short(entry['company'].name, 44):<44} "
              f"{len(entry['wanted']):>2} to create")
    print(f"\n  {total} account(s) in total.")
    for role, reason in DECLINED:
        print(f"  {role} is left alone: {reason}.")

    # ------------------------------------------------------------------
    if not APPLY:
        env.cr.rollback()
        print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to create,")
        print("one company at a time with SSC_COMPANY=... while you watch it.")
    else:
        written = []
        for entry in plan:
            company = entry['company']
            for role, code, _why in entry['wanted']:
                name = CREATE[role][0]
                if not code:
                    written.append(f"{short(company.name, 30)}: no free code near its "
                                   f"own accounts for {name!r} - skipped")
                    continue
                vals = {'name': name, 'code': code, 'account_type': kinds[role]}
                if multi:
                    vals['company_ids'] = [(6, 0, [company.id])]
                else:
                    vals['company_id'] = company.id
                account = Account.with_company(company).create(vals)
                written.append(f"{short(company.name, 30)}: {code} {account.name} "
                               f"({account.account_type})")
        env.cr.commit()
        print("\nwritten:")
        for line in written or ['(nothing)']:
            print(f"  . {line}")
        print("\nnext: tools/map_localisation_accounts.py now finds these by name and")
        print("puts them on EOSP, ALP and the four deduction rules - report first,")
        print("then SSC_APPLY=1.")
