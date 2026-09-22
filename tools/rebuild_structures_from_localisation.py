"""Rebuild each company's structures on the UAE localisation's own rules.

    cd ~/src/user

    # report only, writes nothing - read this first:
    odoo-bin shell -d <database> --no-http < tools/rebuild_structures_from_localisation.py

    # one company at a time:
    SSC_COMPANY="ROYAL ARROW" SSC_APPLY=1 odoo-bin shell ...

    # everything, once the first has been read on screen:
    SSC_APPLY=1 odoo-bin shell ...

Why this exists
---------------
The seven structures in use descend from a hand-written one and carry ten
rules. "United Arab Emirates: Monthly Pay" carries thirty-eight, and among them
is everything still on this project's list of missing pieces:

    EOSP    end of service provision - 21 days a year to five years, a month
            after, which is the UAE law written out
    ALP     annual leave provision
    ADVREC  advance recovery
    SL50    sick leave at 50%          SL0    sick leave at 0%
    AEPAID  paid leave                 AEUNPAID   unpaid leave
    OT      overtime                   GROSS / NET / NETCOST

Rewriting those by hand is rewriting Odoo. This copies them instead.

What it does, per company and per population:

  * copies the localisation structure, names it as the structure it replaces,
    points it at that company's salary journal and at its own structure type;
  * moves the type's default onto the copy, so every contract on that type
    follows without being touched - the contracts are attached to the TYPE,
    never to the structure;
  * corrects the copied unpaid list: the localisation lists SICKLEAVE0, and
    this database's sick leave now maps to AESICKLEAVE0, which is what the
    SL0 rule reads;
  * deletes the structure it replaced - and refuses to, naming it instead, if
    a single payslip was ever built on it.

What it does NOT do

  * it writes no accounts. The copied rules arrive with none, and the account
    mapping is its own step, on its own report;
  * it does not touch the localisation structure itself. That record is Odoo's,
    and every company here gets a copy of it rather than a share in it;
  * it does not touch a contract, a payslip, or an overtime ruleset.

In the interface
----------------
  * the structure and its rules   Payroll > Configuration > Salary Structures
  * the type's default            Payroll > Configuration > Structure Types
  * the unpaid list               the structure, Unpaid Work Entry Types

Nothing here inherits, patches or extends a native model.

Reads only unless SSC_APPLY=1.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'
ONLY_COMPANY = (os.environ.get('SSC_COMPANY') or '').strip().lower()
SOURCE = os.environ.get('SSC_SOURCE') or 'United Arab Emirates: Monthly Pay'

# What the copied unpaid list should say on this database, now that sick leave
# maps to the localisation's own codes.
UNPAID_CODES = ('LEAVE90', 'OUT', 'AESICKLEAVE0')

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
WorkEntryType = (env['hr.work.entry.type'].sudo()
                 if 'hr.work.entry.type' in env else None)
Payslip = env['hr.payslip'].sudo() if 'hr.payslip' in env else None
Version = env['hr.version'].sudo() if 'hr.version' in env else None

stop = None
source = None
default_field = None
if Structure is None or StructType is None:
    stop = "hr_payroll is not installed - nothing to rebuild."
else:
    source = Structure.search([('name', '=', SOURCE)], limit=1)
    default_field = ('default_struct_id'
                     if 'default_struct_id' in StructType._fields else None)
    if not source:
        stop = f"no structure named {SOURCE!r} to copy"
    elif not default_field:
        stop = "the structure type carries no default structure on this Odoo"

if stop:
    title("nothing to do")
    print("  " + stop)
else:
    title("1. what is being copied")

    print(f"  [{source.id}] {source.name}")
    print(f"  rules: {len(source.rule_ids)}")
    print(f"  unpaid list: {', '.join(sorted(source.unpaid_work_entry_type_ids.mapped('code'))) or '(none)'}")
    # `or []` would turn an empty recordset into a plain list, and a list has
    # no .mapped - which is exactly how this fell over the first time.
    wanted_unpaid = (WorkEntryType.search([('code', 'in', list(UNPAID_CODES))])
                     if WorkEntryType is not None else None)
    found_codes = set(wanted_unpaid.mapped('code')) if wanted_unpaid is not None else set()
    missing = set(UNPAID_CODES) - found_codes
    print(f"  it will be set to: {', '.join(sorted(UNPAID_CODES))}"
          + (f"   !! not on this database: {', '.join(sorted(missing))}" if missing else ""))

    # ------------------------------------------------------------------
    title("2. the structures being replaced")

    # One structure at a time, NOT one type at a time. Several types point at
    # the same structure here - the per-company "Employee Structure" from the
    # first pass and the Labour/Staff pair from the second - so walking the
    # types would copy one structure three times and then delete it three
    # times.
    by_structure = {}
    for stype in StructType.search([]):
        current = stype[default_field]
        if not current or current == source:
            continue
        name = current.name or ''
        # Only the structures this project made. Regular Pay and Worker Pay
        # are Odoo's own, and rebuilding them is not this tool's business.
        if not (name.endswith(' Labour Pay') or name.endswith(' Staff Pay')):
            continue
        company = current.journal_id.company_id
        if not company:
            continue
        if ONLY_COMPANY and ONLY_COMPANY not in (company.name or '').lower():
            continue
        item = by_structure.setdefault(current.id, {
            'old': current, 'company': company, 'types': StructType.browse()})
        item['types'] |= stype

    plan = []
    for item in by_structure.values():
        old, company, types = item['old'], item['company'], item['types']
        # `if Version` on an empty recordset is False - which is how the first
        # run reported nought contracts on every type, and would have deleted
        # a structure carrying payslips believing it carried none.
        versions = (Version.search_count([('structure_type_id', 'in', types.ids)])
                    if Version is not None else 0)
        slips = (Payslip.search_count([('struct_id', '=', old.id)])
                 if Payslip is not None else 0)
        item.update({'versions': versions, 'slips': slips})
        plan.append(item)
        print(f"\n  {short(company.name)}")
        print(f"      structure [{old.id}] {old.name}  "
              f"({len(old.rule_ids)} rules -> {len(source.rule_ids)})")
        print(f"      journal   {old.journal_id.display_name or '(none)'}")
        print("      type(s)   " + ' | '.join(types.mapped('name')))
        print(f"      contracts {versions} on those types - they do not move")
        if slips:
            print(f"      !! {slips} payslip(s) were built on it, so it will be kept")

    if not plan:
        print("  no Labour Pay or Staff Pay structure to rebuild here.")

    # ------------------------------------------------------------------
    title("3. what the copies bring that the originals lack")

    have = set()
    for item in plan:
        have |= set(item['old'].rule_ids.mapped('code'))
    coming = set(source.rule_ids.mapped('code'))
    gained = sorted(coming - have)
    lost = sorted(have - coming)
    print(f"  gained ({len(gained)}): {', '.join(gained)}")
    print(f"\n  LOST  ({len(lost)}): {', '.join(lost) or '(none)'}")
    if lost:
        print("\n  Those are this project's own rules. The overtime pair is rebuilt on")
        print("  the localisation's terms in a later step; anything else in that list")
        print("  has to be looked at before the old structure is deleted.")

    # ------------------------------------------------------------------
    title("summary")

    for entry in plan:
        if entry['slips']:
            print(f"  {short(entry['old'].name)}  kept - it carries "
                  f"{entry['slips']} payslip(s)")
        else:
            print(f"  {short(entry['old'].name)}  rebuilt, and its "
                  f"{len(entry['types'])} type(s) moved onto the copy")

    if not APPLY:
        env.cr.rollback()
        print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write,")
        print("one company at a time with SSC_COMPANY=... while you watch it.")
    else:
        written = []
        for entry in plan:
            if entry['slips']:
                written.append(f"{short(entry['company'].name, 30)}: kept "
                               f"{entry['old'].name} - {entry['slips']} payslip(s)")
                continue
            old = entry['old']
            name = old.name
            journal = old.journal_id

            new = source.copy({'name': name})
            # copy() forces '<name> (copy)' and ignores the name it is given.
            vals = {'name': name, 'journal_id': journal.id,
                    'type_id': entry['types'][:1].id}
            if wanted_unpaid is not None and 'unpaid_work_entry_type_ids' in new._fields:
                vals['unpaid_work_entry_type_ids'] = [(6, 0, wanted_unpaid.ids)]
            new.write(vals)
            # EVERY type that pointed at the old one follows it, or a contract
            # on a forgotten type keeps landing on a structure being deleted.
            entry['types'].write({default_field: new.id})
            written.append(f"{short(entry['company'].name, 26)}: [{new.id}] {new.name} "
                           f"({len(new.rule_ids)} rules), now the default of "
                           f"{len(entry['types'])} type(s)")

            try:
                with env.cr.savepoint():
                    old.unlink()
                written.append(f"{short(entry['company'].name, 30)}: removed the old "
                               f"[{old.id}] {name}")
            except Exception as error:                               # noqa: BLE001
                if 'active' in old._fields:
                    old.active = False
                    written.append(f"{short(entry['company'].name, 30)}: archived the "
                                   f"old [{old.id}] {name} - still referenced ({error})")
                else:
                    written.append(f"{short(entry['company'].name, 30)}: could NOT "
                                   f"remove [{old.id}] {name} ({error})")

        env.cr.commit()
        print("\nwritten:")
        for line in written or ['(nothing)']:
            print(f"  . {line}")
        print("\nnext: the copied rules carry no accounts, so a payslip validated now")
        print("would post nothing. The account mapping is the next step, and after it")
        print("the two overtime rules and the labour side of AEPAID.")
