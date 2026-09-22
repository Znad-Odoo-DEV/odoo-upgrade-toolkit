"""Two structures per company - labour and staff - each with its own accounts.

    cd ~/src/user

    # report only, writes nothing - read this first:
    odoo-bin shell -d <database> --no-http < tools/split_labour_staff_payroll.py

    # one company at a time:
    SSC_COMPANY="ROYAL ARROW" SSC_APPLY=1 odoo-bin shell ...

    # everything, once the first has been checked in the interface:
    SSC_APPLY=1 odoo-bin shell ...

    # and only then, put each contract on the labour or staff type:
    SSC_APPLY=1 SSC_ASSIGN=1 SSC_LIMIT=20 odoo-bin shell ...

Why two structures and not one
------------------------------
Site labour is a direct cost (4xxxx) and office staff are an administrative
expense (5xxxx); a profit and loss that mixes them tells the reader nothing
about either. The account sits on the salary RULE, and a rule belongs to one
structure - so a company that wants the two apart needs two structures. There
is no per-employee account in the native model, and nothing here inherits one.

Per company, it makes sure of:

  * a labour structure - the one that already exists, renamed - and a staff
    structure copied from it, both on that company's salary journal;
  * a structure type for each, defaulting to it, so the payslip picks the
    structure from the contract without anybody choosing;
  * the accounts on the rules, found BY NAME inside that company's own chart -
    never by code, because the same number means different things in these
    four charts.

With SSC_ASSIGN=1 it also puts each contract on the right type: an employee
flagged Engineer/Office on ssc.employee is staff, everybody else is labour.
The link between the two worlds is ssc.employee.hr_employee_id, matched by
badge long before this tool.

It never touches a payslip, and never touches ruleset_id.

In the interface
----------------
Every write below is configuration, and each one has a screen behind it:

  * the structure and its name   Payroll > Configuration > Salary Structures
  * the structure type and its
    default structure            Payroll > Configuration > Structure Types
  * account_debit / account_credit
    on a rule                    the rule, inside its structure
  * the structure type on a
    contract                     Employees > the employee > Contract

Nothing here inherits, patches or extends a native model. Anything this tool
does, a functional consultant could do by hand in the interface - it is done
here only because doing it hundreds of times by hand invites a slip.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

APPLY = os.environ.get('SSC_APPLY') == '1'
ASSIGN = os.environ.get('SSC_ASSIGN') == '1'
MASTER = os.environ.get('SSC_STRUCTURE') or 'SSC Monthly Pay'
ONLY_COMPANY = (os.environ.get('SSC_COMPANY') or '').strip().lower()
LIMIT = int(os.environ.get('SSC_LIMIT') or 0)

# What each rule needs, expressed as a ROLE rather than an account code.
#   kind -> rule code -> (debit role, credit role)
ROLES = {
    'labour': {
        'BASIC':      ('basic', None),
        'SSC_OT_REG': ('overtime', None),
        'SSC_OT_OFF': ('overtime', None),
        'NET':        (None, 'payable'),
    },
    'staff': {
        'BASIC':      ('staff_salary', None),
        'SSC_OT_REG': ('staff_salary', None),
        'SSC_OT_OFF': ('staff_salary', None),
        'NET':        (None, 'payable'),
    },
}

# The account playing each role is found BY NAME, inside one company.
#
# Never by code across companies: 400011 is "Salary Additions" in SAUD and
# "Sales Commission" in MALAK and ROYAL WOODEN, and 500003 is "Salaries &
# Allowances" in SAUD and "Management Consultancy Fees" in the other two. A
# shared code map would post overtime into a commission account and never
# raise a thing. Names describe what an account IS; codes only say where it
# sits in one chart.
ROLE_NAMES = {
    'basic': ('Basic Salary',),
    'overtime': ('Over Time Allowance', 'Overtime Allowance', 'Salary Additions',
                 'Salary Additions - Overtime', 'Overtime'),
    'staff_salary': ('Staff Salaries & Allowances', 'Salaries & Allowances',
                     'Staff Salaries'),
    'payable': ('Salary Payable', 'Accrued - Salaries', 'Accrued Salaries'),
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

# Every rule code this tool knows how to map, whatever the company.
RULE_CODES = ('BASIC', 'SSC_OT_REG', 'SSC_OT_OFF', 'NET')

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def short(text, size=44):
    text = text or '-'
    return text if len(text) <= size else text[:size - 1] + '.'


Structure = env['hr.payroll.structure'].sudo() if 'hr.payroll.structure' in env else None
StructType = (env['hr.payroll.structure.type'].sudo()
              if 'hr.payroll.structure.type' in env else None)
Account = env['account.account'].sudo() if 'account.account' in env else None
Rule = env['hr.salary.rule'].sudo() if 'hr.salary.rule' in env else None
Version = env['hr.version'].sudo() if 'hr.version' in env else None
SscEmployee = env['ssc.employee'].sudo() if 'ssc.employee' in env else None
Company = env['res.company'].sudo()

stop = None
if Structure is None or Rule is None or Version is None:
    stop = "hr_payroll is not installed - nothing to configure."
elif Account is None or 'account_debit' not in Rule._fields:
    stop = ("the salary rules carry no accounts on this database "
            "(hr_payroll_account missing), so there is nothing to map.")

master = None
default_field = None
if not stop:
    master = Structure.search([('name', '=', MASTER)], limit=1)
    if not master:
        # This tool renames the master to '<company> Labour Pay' on its first
        # run, so looking it up by the old name fails on the second. Fall back
        # to any structure that carries the rules being mapped.
        carriers = Structure.search([]).filtered(
            lambda s: set(RULE_CODES) <= set(s.rule_ids.mapped('code')))
        master = (carriers.filtered(lambda s: (s.name or '').endswith(' Labour Pay'))[:1]
                  or carriers[:1])
        if master:
            print(f"  (no structure named {MASTER!r}; taking the rules from "
                  f"{master.name!r} instead)")
    default_field = ('default_struct_id'
                     if StructType is not None
                     and 'default_struct_id' in StructType._fields else None)
    if not master:
        stop = f"no structure named {MASTER!r}, and none carrying the mapped rules"
    elif not default_field:
        stop = ("this Odoo has no default structure on the structure type, so a "
                "contract cannot carry the choice - the split would have to be "
                "made by hand on every pay run.")

if stop:
    title("nothing to do")
    print("  " + stop)
else:
    multi = 'company_ids' in Account._fields

    def accounts_pending(slot, company, kind):
        """Would writing the accounts change anything on this structure?

        Without this the summary says "set the accounts" on every run, long
        after they are set, and a report nobody believes is worse than none.
        """
        structure = slot.get('structure')
        if not structure:
            return True
        for rule_code, (debit_role, credit_role) in ROLES[kind].items():
            rule = structure.rule_ids.filtered(lambda r, c=rule_code: r.code == c)[:1]
            if not rule:
                continue
            for field_name, role in (('account_debit', debit_role),
                                     ('account_credit', credit_role)):
                if field_name not in Rule._fields:
                    continue
                account = by_role(role, company) if role else Account.browse()
                if rule[field_name] != account:
                    return True
        return False

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

    def by_role(role, company):
        """The account playing that role INSIDE that company, by name AND kind.

        The kind is not decoration: ROYAL ARROW has a "Basic Salary" and a
        "Salary Additions" that are not expense accounts at all, sitting beside
        the real ones in its payroll group, and a name-only match took them.

        with_company matters as well: `code` is company-dependent in 19.0 -
        computed from `code_store`, stored per company - so anything read off
        an account from the wrong company's context comes back empty.
        """
        for name in ROLE_NAMES[role]:
            found = Account.with_company(company).search(
                scope(company) + [('name', '=ilike', name),
                                  ('active', '=', True),
                                  ('account_type', 'like', ROLE_TYPES[role])])
            # No code in this company's context means it is not in this
            # company's chart, whatever the domain matched.
            found = found.filtered(lambda a, c=company: a.with_company(c).code)
            if found:
                return pick(found, company)
        return Account.browse()

    def code_of(account, company):
        return (account.with_company(company).code or '?') if account else '-'

    def abbr(company):
        code = company.ssc_company_abbr if 'ssc_company_abbr' in company._fields else None
        return (code or company.name or '').strip()

    def names(company, kind):
        word = 'Labour' if kind == 'labour' else 'Staff'
        return f"{abbr(company)} {word} Pay", f"{abbr(company)} {word}"

    # ------------------------------------------------------------------
    title("1. who is staff and who is labour")

    staff_versions = Version.browse()
    if SscEmployee is None:
        print("  ssc.employee is not installed, so nobody can be told apart -")
        print("  every contract counts as labour.")
    else:
        flagged = SscEmployee.search([('is_engineer_office', '=', True)])
        linked = flagged.filtered(lambda e: e.hr_employee_id)
        staff_versions = Version.search(
            [('employee_id', 'in', linked.hr_employee_id.ids)]) if linked else Version.browse()
        print(f"  {len(flagged)} employee(s) flagged Engineer/Office, "
              f"{len(linked)} of them linked to an hr.employee")
        if len(flagged) != len(linked):
            print(f"  !! {len(flagged) - len(linked)} have no hr.employee, so their "
                  f"contracts cannot be told apart - they would count as labour")
        per_company = defaultdict(int)
        for version in staff_versions:
            per_company[version.company_id.name or '-'] += 1
        for name, count in sorted(per_company.items(), key=lambda kv: -kv[1]):
            print(f"    {short(name)}  {count:>5} staff contract version(s)")

    # ------------------------------------------------------------------
    title("2. what each company has, and what it needs")

    companies = Company.search([])
    if ONLY_COMPANY:
        companies = companies.filtered(lambda c: ONLY_COMPANY in (c.name or '').lower())
        print(f"  restricted to companies matching {ONLY_COMPANY!r}\n")

    plan = []
    for company in companies:
        versions = Version.search([('company_id', '=', company.id)])
        if not versions:
            continue
        mine = staff_versions & versions
        # The structure this company's contracts land on today is its labour
        # one. Identity is what the contracts point at, NOT what shares the
        # journal: the localisation's own Regular Pay / Worker Pay sit on the
        # same journal, and renaming one of those would be a mess.
        current = versions.structure_type_id.default_struct_id.filtered(
            lambda s, c=company: s.journal_id.company_id == c
            and not (s.name or '').endswith(' Staff Pay'))
        entry = {'company': company, 'versions': versions, 'staff_versions': mine,
                 'journal': current[:1].journal_id, 'current': current[:1], 'kinds': {}}

        print(f"\n  {short(company.name)}  {len(versions)} version(s), "
              f"{len(mine)} staff")
        if not entry['journal']:
            print("      !! no structure with a journal for this company yet - run")
            print("         tools/setup_company_payroll_structures.py first")
            continue

        for kind in ('labour', 'staff'):
            struct_name, type_name = names(company, kind)
            structure = Structure.search([('name', '=', struct_name)], limit=1)
            if not structure and kind == 'labour':
                # Whatever it is called today, the structure the contracts
                # already land on is this company's labour one.
                structure = entry['current']
            stype = StructType.search([('name', '=', type_name)], limit=1)
            needed = kind == 'labour' or mine
            entry['kinds'][kind] = {'structure': structure, 'type': stype,
                                    'name': struct_name, 'type_name': type_name,
                                    'needed': bool(needed)}
            if not needed:
                print(f"      {kind:<7} not needed - no staff contract in this company")
                continue
            print(f"      {kind:<7} structure: "
                  + (f"[{structure.id}] {structure.name}" if structure
                     else f"MISSING -> copy of the master as {struct_name!r}")
                  + ("" if not structure or structure.name == struct_name
                     else f"  -> renamed {struct_name!r}"))
            print(f"              type:      "
                  + (stype.name if stype else f"MISSING -> {type_name!r}"))
        plan.append(entry)

    if not plan:
        print("\n  no company is ready - nothing to do.")

    # ------------------------------------------------------------------
    title("3. do the accounts exist in each chart?")

    missing_any = False
    for entry in plan:
        company = entry['company']
        for kind in ('labour', 'staff'):
            if not entry['kinds'].get(kind, {}).get('needed'):
                continue
            gaps, found = [], []
            for role in {r for pair in ROLES[kind].values() for r in pair if r}:
                account = by_role(role, company)
                if account:
                    found.append(f"{role:<13} {code_of(account, company):<8} "
                                 f"{account.name[:30]}")
                else:
                    gaps.append(role)
            missing_any = missing_any or bool(gaps)
            print(f"  {short(company.name, 34):<34} {kind:<7} "
                  + ("!! no account plays: " + ', '.join(sorted(gaps))
                     if gaps else "every role resolves"))
            for line in sorted(found):
                print(f"      {line}")
    if missing_any:
        print("\n  A role with no account is left empty on the rule rather than")
        print("  pointed at something that merely shares a number in another")
        print("  chart. tools/create_payroll_accounts.py creates the two that")
        print("  the sister companies are missing.")

    # ------------------------------------------------------------------
    title("4. contracts that would move")

    move = {}
    for entry in plan:
        company = entry['company']
        for kind in ('labour', 'staff'):
            slot = entry['kinds'].get(kind, {})
            if not slot.get('needed'):
                continue
            wanted = (entry['staff_versions'] if kind == 'staff'
                      else entry['versions'] - entry['staff_versions'])
            wrong = wanted.filtered(
                lambda v, n=slot['type_name']: (v.structure_type_id.name or '') != n)
            if LIMIT and len(wrong) > LIMIT:
                print(f"  SSC_LIMIT={LIMIT}: {len(wrong)} in "
                      f"{short(company.name, 26)} {kind}, only the first {LIMIT}")
                wrong = wrong[:LIMIT]
            if wrong:
                move[(company.id, kind)] = wrong
                print(f"  {short(company.name, 34):<34} {kind:<7} {len(wrong):>5} "
                      f"version(s) -> {slot['type_name']}")
    if not move:
        print("  every contract already carries the type it should.")
    elif not ASSIGN:
        print("\n  SSC_ASSIGN is not set, so the contracts are left alone.")

    # ------------------------------------------------------------------
    title("summary")

    for entry in plan:
        bits = []
        for kind in ('labour', 'staff'):
            slot = entry['kinds'].get(kind, {})
            if not slot.get('needed'):
                continue
            if not slot['structure']:
                bits.append(f"create the {kind} structure")
            elif slot['structure'].name != slot['name']:
                bits.append(f"rename the {kind} structure")
            if not slot['type']:
                bits.append(f"create the {kind} type")
            if accounts_pending(slot, entry['company'], kind):
                bits.append(f"set the {kind} accounts")
            if ASSIGN and move.get((entry['company'].id, kind)):
                bits.append(f"move {len(move[(entry['company'].id, kind)])} "
                            f"{kind} version(s)")
        print(f"  {short(entry['company'].name)}  " + ("; ".join(bits) or "nothing to do"))

    if not APPLY:
        env.cr.rollback()
        print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write,")
        print("one company at a time with SSC_COMPANY=... while you watch it.")
    else:
        written = []
        for entry in plan:
            company, journal = entry['company'], entry['journal']
            for kind in ('labour', 'staff'):
                slot = entry['kinds'][kind]
                if not slot['needed']:
                    continue

                structure = slot['structure']
                if not structure:
                    structure = master.copy({'name': slot['name'],
                                             'journal_id': journal.id})
                    # copy() renames to '<name> (copy)' and ignores what it is
                    # given, so the name is written again.
                    structure.write({'name': slot['name'], 'journal_id': journal.id})
                    written.append(f"{short(company.name, 26)}: {kind} structure "
                                   f"{structure.name} ({len(structure.rule_ids)} rules)")
                elif structure.name != slot['name']:
                    was = structure.name
                    structure.write({'name': slot['name'], 'journal_id': journal.id})
                    written.append(f"{short(company.name, 26)}: {was} renamed "
                                   f"{structure.name}")
                slot['structure'] = structure

                # The accounts, found by role inside this company's own chart.
                # A role with no account leaves the field empty - it is never
                # filled with something that merely shares a number elsewhere.
                fixed = missing = 0
                for rule_code, (debit_role, credit_role) in ROLES[kind].items():
                    rule = structure.rule_ids.filtered(
                        lambda r, c=rule_code: r.code == c)[:1]
                    if not rule:
                        continue
                    vals = {}
                    for field_name, role in (('account_debit', debit_role),
                                             ('account_credit', credit_role)):
                        if field_name not in Rule._fields:
                            continue
                        account = by_role(role, company) if role else Account.browse()
                        if role and not account:
                            missing += 1
                        if rule[field_name] != account:
                            vals[field_name] = account.id if account else False
                            fixed += bool(account)
                    if vals:
                        rule.write(vals)
                if fixed or missing:
                    written.append(f"{short(company.name, 26)}: {kind} accounts - "
                                   f"{fixed} set, {missing} role(s) with no account")

                stype = slot['type']
                if not stype:
                    vals = {'name': slot['type_name'], default_field: structure.id}
                    for name in ('country_id', 'wage_type', 'default_schedule_pay',
                                 'default_resource_calendar_id',
                                 'default_work_entry_type_id'):
                        if name not in StructType._fields:
                            continue
                        value = master.type_id[name]
                        if not value:
                            continue
                        vals[name] = value.id if hasattr(value, 'id') else value
                    stype = StructType.create(vals)
                    written.append(f"{short(company.name, 26)}: {kind} type {stype.name}")
                elif stype[default_field] != structure:
                    stype.write({default_field: structure.id})
                    written.append(f"{short(company.name, 26)}: {stype.name} defaults "
                                   f"to {structure.name}")
                slot['type'] = stype

        if ASSIGN:
            for entry in plan:
                for kind in ('labour', 'staff'):
                    versions = move.get((entry['company'].id, kind))
                    stype = entry['kinds'].get(kind, {}).get('type')
                    if versions and stype:
                        versions.write({'structure_type_id': stype.id})
                        written.append(f"{short(entry['company'].name, 26)}: "
                                       f"{len(versions)} {kind} version(s) -> "
                                       f"{stype.name}")

        env.cr.commit()
        print("\nwritten:")
        for line in written or ['(nothing)']:
            print(f"  . {line}")
        print("\nnext: make one payslip for a labour employee and one for a staff")
        print("employee in the same company, validate them, and read the two")
        print("journal entries against section 3 above - the labour one debits")
        print("that company's basic and overtime accounts, the staff one its")
        print("administrative salary account, and both credit its payable, in")
        print("its own journal. Section 3 is the answer key: the codes differ")
        print("per company and no two of these charts agree on a number.")
