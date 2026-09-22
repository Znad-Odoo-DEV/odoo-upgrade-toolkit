"""Put each localisation rule on the account its own company's chart calls for.

    cd ~/src/user

    # report only, writes nothing - read this first:
    odoo-bin shell -d <database> --no-http < tools/map_localisation_accounts.py

    # one company at a time:
    SSC_COMPANY="ROYAL ARROW" SSC_APPLY=1 odoo-bin shell ...

    # everything, once the first has been read on screen:
    SSC_APPLY=1 odoo-bin shell ...

Why by name, and never by code
------------------------------
These four companies do not share a chart. 400011 is "Salary Additions" in SAUD
and "Sales Commission" in MALAK and ROYAL WOODEN; 500003 is administrative
salary in SAUD and "Management Consultancy Fees" elsewhere; ROYAL ARROW keeps
payroll in a 410xxxx group of its own. A shared code map would post overtime
into a commission account and never raise a thing.

So every account is found by NAME and TYPE inside one company, and a candidate
with no code in that company's context - the proof it belongs to another
chart - is dropped. Where two accounts answer to the same name, the one
carrying journal entries wins: that is what the books mean by it.

What lands where

    BASIC                        Dr  basic salary
    HOUALLOW TRAALLOW OTALLOW    Dr  each allowance's own account, or the
                                     general one where the chart has no separate
    OT                           Dr  overtime
    AEPAID AESPAID50             Dr  leave salary
    AEUNPAID SL50 SL0 OOC        Cr  salary deduction
    ADVREC                       Cr  advance salary        (recovering the asset)
    NET                          Cr  salary payable
    EOSP                         Dr  end of service        Cr  its provision
    ALP                          Dr  leave provision       Cr  its provision

GROSS and NETCOST are deliberately left bare: they are totals of other rules,
and giving them accounts would post the same money twice.

A rule whose account cannot be found keeps an empty field and is named in the
report. An empty field simply produces no line - it never invents one.

In the interface
----------------
  * the accounts on a rule   the rule, inside its structure
  * the chart                Accounting > Configuration > Chart of Accounts

Nothing here inherits, patches or extends a native model.

Reads only unless SSC_APPLY=1.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'
ONLY_COMPANY = (os.environ.get('SSC_COMPANY') or '').strip().lower()

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92

# rule code -> (debit role, credit role)
RULE_ROLES = {
    'BASIC':     ('basic', None),
    'HOUALLOW':  ('housing', None),
    'TRAALLOW':  ('transport', None),
    'OTALLOW':   ('other_allowance', None),
    'OT':        ('overtime', None),
    'AEPAID':    ('leave_salary', None),
    'AESPAID50': ('leave_salary', None),
    'AEUNPAID':  (None, 'deduction'),
    'SL50':      (None, 'deduction'),
    'SL0':       (None, 'deduction'),
    'OOC':       (None, 'deduction'),
    'ADVREC':    (None, 'advance'),
    'NET':       (None, 'payable'),
    'EOSP':      ('eos_expense', 'eos_provision'),
    'ALP':       ('leave_provision_expense', 'leave_provision'),
}

# The names an account may go by, in order of preference, and the kind it must
# be. A chart without a separate housing or transport account falls back to its
# general allowance account through the last names in each list.
ROLE_NAMES = {
    'basic': ('Basic Salary',),
    'housing': ('House Allowance', 'Housing Allowance', 'Salary Additions'),
    'transport': ('Transportation Allowance', 'Transportation & Other Allowance',
                  'Salary Additions'),
    # 'Transportation & Other Allowance' is ROYAL ARROW's, and it is one
    # account on purpose: that chart does not separate transport from the
    # other allowances. So OTALLOW and TRAALLOW both land on 4101004 there,
    # which is what its books already do.
    'other_allowance': ('Staff Other Allowances', 'Other Allowances',
                        'Transportation & Other Allowance', 'Salary Additions'),
    'overtime': ('Over Time Allowance', 'Overtime Allowance', 'Salary Additions'),
    'leave_salary': ('Leave Salary', 'Annual Leave Salary'),
    'deduction': ('Salary Deduction',),
    'advance': ('Advance Salary',),
    'payable': ('Salary Payable', 'Accrued - Salaries', 'Accrued Salaries'),
    'eos_expense': ('End of Service Expense', 'End of Service Benefits',
                    'Gratuity Expense'),
    'eos_provision': ('Provision - End of Service', 'End of Service Provision',
                      'Provision - Gratuity'),
    'leave_provision_expense': ('Leave Salary', 'Annual Leave Salary'),
    'leave_provision': ('Provision - Leave Salaries', 'Provision - Leave Salary'),
}

ROLE_TYPES = {
    'basic': 'expense', 'housing': 'expense', 'transport': 'expense',
    'other_allowance': 'expense', 'overtime': 'expense', 'leave_salary': 'expense',
    'deduction': 'income_other', 'advance': 'asset', 'payable': 'liability',
    'eos_expense': 'expense', 'eos_provision': 'liability',
    'leave_provision_expense': 'expense', 'leave_provision': 'liability',
}


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def short(text, size=40):
    text = text or '-'
    return text if len(text) <= size else text[:size - 1] + '.'


Structure = env['hr.payroll.structure'].sudo() if 'hr.payroll.structure' in env else None
Account = env['account.account'].sudo() if 'account.account' in env else None
Rule = env['hr.salary.rule'].sudo() if 'hr.salary.rule' in env else None
Line = env['account.move.line'].sudo() if 'account.move.line' in env else None

if Structure is None or Account is None or Rule is None:
    title("nothing to do")
    print("  payroll or accounting is not installed on this database.")
elif 'account_debit' not in Rule._fields:
    title("nothing to do")
    print("  the salary rules carry no accounts (hr_payroll_account missing).")
else:
    multi = 'company_ids' in Account._fields

    def scope(company):
        return ([('company_ids', 'in', company.id)] if multi
                else [('company_id', '=', company.id)])

    def code_of(account, company):
        return (account.with_company(company).code or '') if account else ''

    def by_role(role, company):
        """The account playing that role inside this company, by name and kind.

        Deductions are the one role read loosely: a chart may call the account
        an expense, an other income or a contra - what matters is its name.
        """
        kind = ROLE_TYPES[role]
        for name in ROLE_NAMES[role]:
            # ('active', '=', True) is not redundant: these tools run with
            # active_test off, and an ARCHIVED account is exactly what leaked
            # SAUD-style codes into ROYAL ARROW's roles - old duplicates with
            # no entries on them. An archived account must never end up on a
            # salary rule.
            domain = scope(company) + [('name', '=ilike', name),
                                       ('active', '=', True)]
            if role != 'deduction':
                domain += [('account_type', 'like', kind)]
            found = Account.with_company(company).search(domain)
            # No code in this company's context means another company's chart.
            found = found.filtered(lambda a, c=company: code_of(a, c))
            if not found:
                continue
            if len(found) == 1:
                return found
            scored = [(Line.search_count([('account_id', '=', a.id)]) if Line is not None
                       else 0, code_of(a, company), a) for a in found]
            scored.sort(key=lambda row: (-row[0], row[1]))
            return scored[0][2]
        return Account.browse()

    # ------------------------------------------------------------------
    title("1. what each chart offers for each role")

    structures = Structure.search([]).filtered(
        lambda s: (s.name or '').endswith(' Labour Pay')
        or (s.name or '').endswith(' Staff Pay'))
    if ONLY_COMPANY:
        structures = structures.filtered(
            lambda s: ONLY_COMPANY in (s.journal_id.company_id.name or '').lower())

    companies = structures.journal_id.company_id
    resolved = {}
    for company in companies:
        print(f"\n  {company.name}")
        for role in sorted(ROLE_NAMES):
            account = by_role(role, company)
            resolved[(company.id, role)] = account
            print(f"      {role:<24} "
                  + (f"{code_of(account, company):<9} {account.name[:34]}" if account
                     else "MISSING"))

    # ------------------------------------------------------------------
    title("2. what would be written on each structure")

    plan = []
    for structure in structures:
        company = structure.journal_id.company_id
        changes, gaps = [], []
        for code, (debit_role, credit_role) in RULE_ROLES.items():
            rule = structure.rule_ids.filtered(lambda r, c=code: r.code == c)[:1]
            if not rule:
                continue
            for field_name, role in (('account_debit', debit_role),
                                     ('account_credit', credit_role)):
                if not role:
                    continue
                account = resolved.get((company.id, role), Account.browse())
                if not account:
                    gaps.append(f"{code}.{field_name[8:]}={role}")
                    continue
                if rule[field_name] != account:
                    changes.append((rule, field_name, account, code, role))
        plan.append({'structure': structure, 'company': company,
                     'changes': changes, 'gaps': gaps})
        print(f"\n  {short(structure.name, 48)}")
        print(f"      {len(changes)} field(s) to set")
        if gaps:
            print(f"      !! no account for: {', '.join(sorted(set(gaps)))}")

    # ------------------------------------------------------------------
    title("summary")

    for entry in plan:
        print(f"  {short(entry['structure'].name, 48):<48} "
              f"{len(entry['changes']):>3} set"
              + (f", {len(set(entry['gaps']))} left empty" if entry['gaps'] else ""))

    if not APPLY:
        env.cr.rollback()
        print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write,")
        print("one company at a time with SSC_COMPANY=... while you watch it.")
    else:
        written = []
        for entry in plan:
            for rule, field_name, account, code, role in entry['changes']:
                rule.write({field_name: account.id})
            if entry['changes']:
                written.append(f"{short(entry['structure'].name, 44)}: "
                               f"{len(entry['changes'])} field(s)")
            if entry['gaps']:
                written.append(f"{short(entry['structure'].name, 44)}: left empty - "
                               f"{', '.join(sorted(set(entry['gaps'])))}")
        env.cr.commit()
        print("\nwritten:")
        for line in written or ['(nothing)']:
            print(f"  . {line}")
        print("\nnext: the two overtime rules, and AEPAID on the labour side, which")
        print("pays leave at the gross hourly rate until it is told to pay the basic.")
