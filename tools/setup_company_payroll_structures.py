"""One salary structure per company, each on that company's own salary journal.

    cd ~/src/user

    # report only, writes nothing - read this first:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/setup_company_payroll_structures.py

    # one company at a time, which is the sane way to do it:
    SSC_COMPANY="ROYAL ARROW" SSC_APPLY=1 odoo-bin shell ...

    # everything, once the first company has been checked in the interface:
    SSC_APPLY=1 odoo-bin shell ...

    # and only then, point the contracts at their company's structure type:
    SSC_APPLY=1 SSC_ASSIGN=1 SSC_LIMIT=20 odoo-bin shell ...

    # clear duplicate structures left by an earlier run (one that carries a
    # payslip is never removed):
    SSC_APPLY=1 SSC_TIDY=1 odoo-bin shell ...

Why this exists
---------------
A payslip takes its journal from its structure and from nowhere else - the
field is ``related='struct_id.journal_id'``, readonly and not stored. A journal
belongs to exactly one company. So one structure shared by four companies means
four companies posting into one company's ledger: salary expense inflated in
one entity, missing in another, and an intercompany balance nobody booked.

Hence one journal per company, one structure per company on it, and - where
this Odoo supports it - one structure type per company, so the right structure
is picked without anybody choosing it by hand every month.

What it does, per company that has contracts:

  * finds or creates a general journal for salaries;
  * finds or creates a structure, copied from the master so the rules start
    identical, pointed at that journal;
  * re-points the copied rules' debit/credit accounts at the same account code
    inside that company's chart, and names the rules it could not resolve
    instead of leaving a foreign account on them;
  * finds or creates a structure type whose default is that structure, when
    this Odoo has such a default at all;
  * with SSC_ASSIGN=1, puts each contract on its own company's structure type.

What it deliberately does NOT do:

  * it never touches ``ruleset_id`` - overtime rulesets belong to
    tools/assign_payroll_config.py;
  * it never edits a payslip. Payslips already made against the master are
    counted per company and state and left alone: changing the structure under
    a payslip changes the money on it;
  * it never rewrites the master's own rules. The master stays whole and keeps
    serving the company whose journal it already carries, so the payslips made
    against it stay valid.

Afterwards keep the rules in one place: edit the master only, then push it to
each copy with tools/apply_salary_rules.py (SSC_STRUCTURE names the structure)
and compare with tools/check_salary_rules.py. Four structures edited by hand on
four screens is how they drift apart.

In the interface
----------------
Every write below is configuration, and each one has a screen behind it:

  * the salary journal        Accounting > Configuration > Journals
  * the structure, its name
    and its journal           Payroll > Configuration > Salary Structures
  * the structure type and
    its default structure     Payroll > Configuration > Structure Types
  * the accounts on a rule    the rule, inside its structure

Nothing here inherits, patches or extends a native model. Anything this tool
does, a functional consultant could do by hand in the interface - it is done
here only because doing it four hundred times by hand invites a slip.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

APPLY = os.environ.get('SSC_APPLY') == '1'
ASSIGN = os.environ.get('SSC_ASSIGN') == '1'
TIDY = os.environ.get('SSC_TIDY') == '1'
MASTER = os.environ.get('SSC_STRUCTURE') or 'SSC Monthly Pay'
ONLY_COMPANY = (os.environ.get('SSC_COMPANY') or '').strip().lower()
JOURNAL_NAME = os.environ.get('SSC_JOURNAL_NAME') or 'Salaries'
JOURNAL_CODE = ((os.environ.get('SSC_JOURNAL_CODE') or 'SAL').strip().upper())[:5]
LIMIT = int(os.environ.get('SSC_LIMIT') or 0)

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
Journal = env['account.journal'].sudo() if 'account.journal' in env else None
Account = env['account.account'].sudo() if 'account.account' in env else None
Rule = env['hr.salary.rule'].sudo() if 'hr.salary.rule' in env else None
Version = env['hr.version'].sudo() if 'hr.version' in env else None
Payslip = env['hr.payslip'].sudo() if 'hr.payslip' in env else None
Company = env['res.company'].sudo()

stop = None
if Structure is None or Version is None or Rule is None:
    stop = "hr_payroll is not installed on this database - nothing to configure."
elif Journal is None:
    stop = ("accounting is not installed, so there is no journal to point a "
            "structure at. Install Accounting first, or keep the single "
            "structure and do not post payroll from Odoo at all.")

master = None
if not stop:
    master = Structure.search([('name', '=', MASTER)], limit=1)

    title("1. the master structure")

    if not master:
        print(f"  !! no structure named {MASTER!r}")
        print("  structures that exist: "
              + (', '.join(Structure.search([]).mapped('name')) or '(none)'))
        stop = "no master structure to copy"
    else:
        print(f"  [{master.id}] {master.name}")
        print(f"  type:    {master.type_id.name or '(none)'}")
        print(f"  journal: {master.journal_id.display_name or '(none)'}"
              + (f"   (company: {master.journal_id.company_id.name})"
                 if master.journal_id else ""))
        print(f"  rules:   {len(master.rule_ids)}")
        if not master.type_id:
            print("  !! the master has no structure type, so no contract can be")
            print("     pointed at it. Set its type first.")
            stop = "the master structure has no type"

if stop:
    title("nothing to do")
    print("  " + stop)
else:
    # The company the master already serves keeps it, so its payslips stay
    # valid; only the other companies get a copy.
    home = master.journal_id.company_id
    if home:
        print(f"  -> {home.name} keeps this structure; the others get a copy")
    else:
        home = Company.browse()
        print("  the master carries no journal, so no company owns it yet -")
        print("  every company in scope gets its own copy.")

    default_field = ('default_struct_id'
                     if StructType is not None
                     and 'default_struct_id' in StructType._fields else None)
    if default_field is None:
        print("\n  note: this Odoo has no default structure on the type, so the")
        print("  structure is chosen on the pay run. Make one pay run per company")
        print("  each month and pick that company's structure on it.")

    # ------------------------------------------------------------------
    title("2. what each company has today")

    companies = Company.search([])
    if ONLY_COMPANY:
        companies = companies.filtered(lambda c: ONLY_COMPANY in (c.name or '').lower())
        print(f"  restricted to companies matching {ONLY_COMPANY!r}\n")

    def abbr(company):
        code = company.ssc_company_abbr if 'ssc_company_abbr' in company._fields else None
        return (code or company.name or '').strip()

    def find_journal(company):
        base = [('company_id', '=', company.id), ('type', '=', 'general')]
        return (Journal.search(base + [('name', '=', JOURNAL_NAME)], limit=1)
                or Journal.search(base + [('code', '=', JOURNAL_CODE)], limit=1)
                or Journal.search(base + [('name', 'ilike', 'salar')], limit=1))

    def free_code(company):
        code, suffix = JOURNAL_CODE, 1
        while Journal.search_count([('company_id', '=', company.id),
                                    ('code', '=', code)]):
            suffix += 1
            code = f"{JOURNAL_CODE[:4]}{suffix}"
        return code

    def structure_name(company):
        return f"{abbr(company)} Monthly Pay"

    def type_name(company):
        return f"{abbr(company)} Employee Structure"

    def wanted_type_name(entry):
        return master.type_id.name if entry['home'] else type_name(entry['company'])

    def owned_structures(company, is_home):
        """The structures that already belong to that company.

        Identity is the journal's company, not the name. Odoo forces
        '<name> (copy)' when a structure is duplicated and throws away the name
        it was handed, so matching on the name alone makes every run create yet
        another structure instead of finding the one the run before it made.
        """
        found = Structure.search(['|', ('journal_id.company_id', '=', company.id),
                                  ('name', '=', structure_name(company))])
        return found if is_home else found - master

    def keeper(owned, stype):
        """The one to keep: whatever the type already defaults to, else the
        oldest. Anything else is a duplicate from an earlier run."""
        if not owned:
            return Structure.browse()
        current = stype[default_field] if (default_field and stype) else Structure.browse()
        return current if current and current in owned else owned.sorted('id')[0]

    plan = []
    for company in companies:
        count = Version.search_count([('company_id', '=', company.id)])
        if not count:
            continue
        journal = find_journal(company)
        is_home = bool(home) and company == home
        stype = (master.type_id if is_home else
                 (StructType.search([('name', '=', type_name(company))], limit=1)
                  if StructType is not None else None))
        owned = owned_structures(company, is_home)
        structure = master if is_home else keeper(owned, stype)
        # A journal is only wrong when it belongs to somebody else. Swapping one
        # of the company's own journals for another of its own is not this
        # tool's business.
        foreign = bool(structure) and (not structure.journal_id
                                       or structure.journal_id.company_id != company)
        spare = Structure.browse() if is_home else (owned - structure)
        plan.append({'company': company, 'versions': count, 'journal': journal,
                     'structure': structure, 'type': stype, 'home': is_home,
                     'spare': spare, 'foreign': foreign})

        print(f"  {short(company.name)}  {count:>5} contract version(s)"
              + ("   [keeps the master]" if is_home else ""))
        print("      journal:   " + (journal.display_name if journal
                                     else f"MISSING -> would create {JOURNAL_NAME!r}"))
        print("      structure: " + (f"[{structure.id}] {structure.name}" if structure
                                     else "MISSING -> would copy the master as "
                                          f"{structure_name(company)!r}"))
        if structure and not is_home and structure.name != structure_name(company):
            print(f"                 -> renamed {structure_name(company)!r}")
        if default_field:
            print("      type:      " + (stype.name if stype
                                         else "MISSING -> would create "
                                              f"{type_name(company)!r}"))
        if foreign:
            print("      !! it posts to "
                  f"{structure.journal_id.display_name or '(none)'}, which is not "
                  "this company's")
        for extra in spare:
            print(f"      duplicate: [{extra.id}] {extra.name}"
                  + ("  -> would be removed" if TIDY else "  (SSC_TIDY=1 removes it)"))

    if not plan:
        print("  no company has a single contract - nothing to configure.")

    # ------------------------------------------------------------------
    title("3. the accounts on the rules")

    account_fields = [name for name in ('account_debit', 'account_credit')
                      if name in Rule._fields]
    multi = Account is not None and 'company_ids' in Account._fields

    def usable(account, company):
        """Can this company post to that account?"""
        if not account:
            return True
        if multi:
            return company in account.company_ids
        return account.company_id in (company, Company.browse())

    def same_code(account, company):
        """The account with the same code inside that company's chart."""
        domain = [('code', '=', account.code)]
        domain += ([('company_ids', 'in', company.id)] if multi
                   else [('company_id', '=', company.id)])
        return Account.search(domain, limit=1)

    carried = Rule.browse()
    if not account_fields:
        print("  the salary rules carry no accounts on this database, so the")
        print("  journal alone decides where a payslip posts.")
    elif Account is None:
        print("  no account.account model - skipped.")
    else:
        carried = master.rule_ids.filtered(
            lambda r: any(r[name] for name in account_fields))
        print(f"  {len(carried)} of the master's {len(master.rule_ids)} rules carry "
              f"an account.")
        for entry in plan:
            if entry['home'] or not carried:
                continue
            company = entry['company']
            unresolved = []
            for rule in carried:
                for name in account_fields:
                    account = rule[name]
                    if account and not usable(account, company) \
                            and not same_code(account, company):
                        unresolved.append(f"{rule.code}.{name}={account.code}")
            print(f"  {short(company.name)}  "
                  + ("every account resolves by code" if not unresolved
                     else "!! no match in its chart for: "
                          + ', '.join(unresolved[:6])
                          + (" ..." if len(unresolved) > 6 else "")))
        if not carried:
            print("  nothing to remap.")

    # ------------------------------------------------------------------
    title("4. payslips already made against the master")

    if Payslip is None:
        print("  no hr.payslip model - skipped.")
    else:
        total = Payslip.search_count([('struct_id', '=', master.id)])
        slips = Payslip.browse() if total > 20000 else \
            Payslip.search([('struct_id', '=', master.id)])
        if not total:
            print("  none.")
        elif not slips:
            print(f"  {total} payslips - too many to break down here, and none of")
            print("  them is touched anyway.")
        else:
            by_company = defaultdict(lambda: defaultdict(int))
            for slip in slips:
                by_company[slip.company_id.name or '-'][slip.state] += 1
            for name, states in sorted(by_company.items()):
                detail = ', '.join(f"{count} {state}"
                                   for state, count in sorted(states.items()))
                mark = '' if (home and name == home.name) else '   <- foreign company'
                print(f"  {short(name)}  {detail}{mark}")
            print("\n  Not touched by this tool. A draft one in a foreign company")
            print("  should be deleted and re-made from that company's structure;")
            print("  a validated one is history and stays as it is.")

    # ------------------------------------------------------------------
    title("5. contracts that would move to their company's type")

    move = {}
    if not default_field:
        print("  this Odoo has no default structure on the type, so a contract")
        print("  carries no structure choice - skipped.")
    else:
        for entry in plan:
            company = entry['company']
            versions = Version.search([('company_id', '=', company.id)])
            wanted = wanted_type_name(entry)
            wrong = versions.filtered(
                lambda v, w=wanted: (v.structure_type_id.name or '') != w)
            if LIMIT and len(wrong) > LIMIT:
                print(f"  SSC_LIMIT={LIMIT}: {len(wrong)} version(s) in "
                      f"{short(company.name, 30)}, only the first {LIMIT} this run")
                wrong = wrong[:LIMIT]
            if wrong:
                move[company.id] = wrong
                print(f"  {short(company.name)}  {len(wrong):>5} version(s) -> {wanted}")
        if not move:
            print("  every contract already carries its company's structure type.")
        elif not ASSIGN:
            print("\n  SSC_ASSIGN is not set, so the contracts are left alone.")

    # ------------------------------------------------------------------
    title("summary")

    for entry in plan:
        company, bits = entry['company'], []
        if not entry['journal']:
            bits.append(f"create the journal {JOURNAL_NAME!r}")
        if not entry['structure']:
            bits.append("copy the master structure")
        else:
            if entry['foreign'] and entry['journal']:
                bits.append("point its structure at its own journal")
            if not entry['home'] \
                    and entry['structure'].name != structure_name(company):
                bits.append(f"rename it {structure_name(company)!r}")
        if entry['spare']:
            bits.append(f"{len(entry['spare'])} duplicate structure(s) "
                        + ("removed" if TIDY else "left alone - SSC_TIDY=1 removes them"))
        if default_field and not entry['type']:
            bits.append(f"create the type {type_name(company)!r}")
        if ASSIGN and move.get(company.id):
            bits.append(f"move {len(move[company.id])} contract version(s)")
        print(f"  {short(company.name)}  " + ("; ".join(bits) if bits else "nothing to do"))

    # Two companies sharing an abbreviation would plan the same structure name,
    # and the second would silently take over the first one's structure.
    clash = defaultdict(list)
    for entry in plan:
        if not entry['home']:
            clash[structure_name(entry['company'])].append(entry['company'].name)
    clash = {name: owners for name, owners in clash.items() if len(owners) > 1}
    if clash:
        print("\n  !! these companies would end up on the same structure name:")
        for name, owners in clash.items():
            print(f"     {name!r} <- {', '.join(owners)}")
        print("     Give them distinct abbreviations (Settings -> Companies ->")
        print("     payroll configuration) before writing anything.")

    if not APPLY:
        env.cr.rollback()
        print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write,")
        print("one company at a time with SSC_COMPANY=... while you watch it.")
    elif clash:
        env.cr.rollback()
        print("\nnothing written - resolve the name clash above first.")
    else:
        written = []
        for entry in plan:
            company = entry['company']

            journal = entry['journal']
            if not journal:
                journal = Journal.create({
                    'name': JOURNAL_NAME,
                    'code': free_code(company),
                    'type': 'general',
                    'company_id': company.id,
                })
                entry['journal'] = journal
                written.append(f"{short(company.name, 30)}: journal {journal.name} "
                               f"[{journal.code}]")

            structure = entry['structure']
            if not structure:
                structure = master.copy({'name': structure_name(company),
                                         'journal_id': journal.id})
                # Odoo names a copied structure '<name> (copy)' and ignores the
                # name it was given, so it is written again here. Without this
                # the next run cannot recognise what this one made, and builds
                # another structure on top of it.
                structure.write({'name': structure_name(company),
                                 'journal_id': journal.id})
                entry['structure'] = structure
                # Odoo copies the rules with the structure. If a version ever
                # stops doing that, a structure with no rules pays nobody, so
                # the missing ones are copied across by hand rather than found
                # out on a payslip.
                missing = master.rule_ids.filtered(
                    lambda r, s=structure: r.code not in s.rule_ids.mapped('code'))
                for rule in missing:
                    rule.copy({'struct_id': structure.id})
                written.append(f"{short(company.name, 30)}: structure {structure.name} "
                               f"({len(structure.rule_ids)} rules"
                               + (f", {len(missing)} copied by hand)" if missing else ")"))
                # The copied rules still carry the master company's accounts.
                if carried and Account is not None:
                    fixed = cleared = 0
                    for rule in structure.rule_ids:
                        vals = {}
                        for name in account_fields:
                            account = rule[name]
                            if not account or usable(account, company):
                                continue
                            replacement = same_code(account, company)
                            vals[name] = replacement.id if replacement else False
                            fixed += bool(replacement)
                            cleared += not replacement
                        if vals:
                            rule.write(vals)
                    if fixed or cleared:
                        written.append(f"{short(company.name, 30)}: {fixed} account(s) "
                                       f"remapped, {cleared} cleared for want of one")
            else:
                if entry['foreign']:
                    structure.journal_id = journal.id
                    written.append(f"{short(company.name, 30)}: {structure.name} -> "
                                   f"journal {journal.display_name}")
                if not entry['home'] and structure.name != structure_name(company):
                    was = structure.name
                    structure.name = structure_name(company)
                    written.append(f"{short(company.name, 30)}: {was} renamed "
                                   f"{structure.name}")

            if default_field and StructType is not None:
                stype = entry['type']
                if not stype:
                    vals = {'name': type_name(company), default_field: structure.id}
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
                    entry['type'] = stype
                    written.append(f"{short(company.name, 30)}: type {stype.name}")
                elif stype[default_field] != structure:
                    stype.write({default_field: structure.id})
                    written.append(f"{short(company.name, 30)}: {stype.name} now "
                                   f"defaults to {structure.name}")

        if TIDY:
            for entry in plan:
                for extra in entry['spare']:
                    label = f"[{extra.id}] {extra.name}"
                    used = (Payslip.search_count([('struct_id', '=', extra.id)])
                            if Payslip is not None else 0)
                    if used:
                        written.append(f"{short(entry['company'].name, 30)}: kept "
                                       f"{label} - {used} payslip(s) sit on it")
                        continue
                    # Anything still defaulting to a duplicate has to be moved
                    # off it first, or removing it takes the default with it.
                    if default_field and StructType is not None:
                        pointing = StructType.search([(default_field, '=', extra.id)])
                        if pointing:
                            pointing.write({default_field: entry['structure'].id})
                    try:
                        with env.cr.savepoint():
                            extra.unlink()
                        written.append(f"{short(entry['company'].name, 30)}: removed "
                                       f"duplicate {label}")
                    except Exception as error:                       # noqa: BLE001
                        if 'active' in extra._fields:
                            extra.active = False
                            written.append(f"{short(entry['company'].name, 30)}: "
                                           f"archived duplicate {label} - still "
                                           f"referenced ({error})")
                        else:
                            written.append(f"{short(entry['company'].name, 30)}: could "
                                           f"NOT remove {label} ({error})")

        if ASSIGN:
            for entry in plan:
                versions = move.get(entry['company'].id)
                if versions and entry['type']:
                    versions.write({'structure_type_id': entry['type'].id})
                    written.append(f"{short(entry['company'].name, 30)}: "
                                   f"{len(versions)} contract version(s) -> "
                                   f"{entry['type'].name}")

        env.cr.commit()
        print("\nwritten:")
        for line in written or ['(nothing)']:
            print(f"  . {line}")
        print("\nnext:")
        print("  1. open one payslip per company: Other Info -> Salary Journal")
        print("     must show that company's own journal;")
        print("  2. keep the copies in step with the master -")
        print("     SSC_STRUCTURE='<the copy>' odoo-bin shell ... "
              "< tools/apply_salary_rules.py")
        print("  3. overtime rulesets stay with tools/assign_payroll_config.py.")
