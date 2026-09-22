"""Put every contract on its own company's structure, and give Malak Al Reem a Staff one.

    odoo-bin shell -d <database> --no-http < tools/fix_structure_types.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/fix_structure_types.py

Sixty two people belong to one company and are paid by another's structure -
fifty six Royal Arrow labourers computing on Saud Shehatha's, four of its staff
on Saud Shehatha's staff structure, two of Malak Al Reem's on Saud Shehatha's.
The payslip is computed by the wrong company's rules and the entry posts to the
wrong company's journal. It is also why an employee cannot be found in the
payslip form: the list is filtered by the active company and they are filed
under another.

Sixteen more - the records created this morning from the ministry lists - sit
on the generic Employee type, whose structures carry Odoo's default rules and
none of ours. A payslip for them would have four lines and no allowances, no
overtime and no deductions.

WHAT IS NOT DONE

Nobody is moved between companies. The company on the record stays exactly
where it is; only the structure type is corrected to match it. The rules are
identical across all seven structures, so no amount changes - what changes is
which company computes and books it.

MALAK AL REEM HAD NOWHERE TO PUT AN OFFICE WORKER

It has a Labour type and no Staff one, and twelve of its new records are
office staff. So a Staff type and a Staff structure are created for it, copied
from the structure the other three companies already share, and the office
records go there with `work_entry_source = 'calendar'` because office staff do
not punch.

LABOUR OR STAFF

For the new records, by the job printed on the permit. A carpenter, a labourer,
a cleaner or a security guard is labour; an accountant, a manager, a clerk or a
sales officer is staff. Every one is printed with the side it was put on.
"""
import os
from collections import Counter

APPLY = os.environ.get('SSC_APPLY') == '1'

# the job words that mean somebody works with their hands
LABOUR_WORDS = ('labourer', 'carpenter', 'cleaner', 'guard', 'mason', 'fixer',
                'plumber', 'electric', 'painter', 'driver', 'turner', 'welder',
                'fitter', 'mechanic', 'wood', 'printer', 'carver', 'assistant')

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

Employee = env['hr.employee'].sudo()
Structure = env['hr.payroll.structure'].sudo()
StructureType = env['hr.payroll.structure.type'].sudo()
Rule = env['hr.salary.rule'].sudo()

MALAK = 'MALAK AL REEM'
malak_company = env['res.company'].sudo().search(
    [('name', 'like', 'MALAK AL REEM%')], limit=1)
ssc_company = env['res.company'].sudo().search(
    [('name', 'like', 'SAUD SHEHATHA%')], limit=1)


def title(text):
    print()
    print("=" * 96)
    print(text)
    print("=" * 96)


# ROYAL ARROW and ROYAL WOODEN share their first word, and keying companies on
# it put sixty three Royal Arrow contracts onto Royal Wooden's structure - the
# payslip then found no journal, because the journal is company-dependent and
# the structure belonged to the wrong company. Match the whole company name
# against the start of the structure type name instead.
COMPANIES = env['res.company'].sudo().search([])


def company_of(type_name):
    name = (type_name or '').strip()
    for company in COMPANIES:
        if name.upper().startswith((company.name or '').strip().upper()):
            return company
    return None


def same_company(type_name, company):
    owner = company_of(type_name)
    return bool(owner) and owner == company


# type per company and kind, keyed on the first word of the company name
types = {}
for stype in StructureType.search([]):
    name = (stype.name or '').strip()
    kind = 'staff' if name.endswith('Staff') else (
        'labour' if name.endswith('Labour') else None)
    owner = company_of(name)
    if kind and owner:
        types[(owner.id, kind)] = stype

# ---------------------------------------------------------------------------
title("1. contracts computing on another company's structure")

active = Employee.with_context(active_test=True).search([])
wrong, generic, fine = [], [], 0
for person in active:
    version = person.current_version_id
    stype = version.structure_type_id
    if not stype or stype.name == 'Employee':
        generic.append(person)
        continue
    if same_company(stype.name, person.company_id):
        fine += 1
        continue
    kind = 'staff' if (stype.name or '').strip().endswith('Staff') else 'labour'
    wrong.append((person, stype, kind))

print(f"  already on their own company's type : {fine}")
print(f"  on another company's type           : {len(wrong)}")
print(f"  on the generic Employee type        : {len(generic)}")
print()
for (company, was, kind), number in Counter(
        (p.company_id.name[:30], s.name[:34], k) for p, s, k in wrong).most_common():
    print(f"  {company:<30} {was:<34} {kind:<7} {number:>4}")

# ---------------------------------------------------------------------------
title("2. Malak Al Reem needs a Staff type and structure")

malak_staff = next((v for (cid, k), v in types.items()
                    if k == 'staff' and cid == malak_company.id), None)
malak_labour = next((v for (cid, k), v in types.items()
                     if k == 'labour' and cid == malak_company.id), None)
model = Structure.search([('type_id', '=', next(v for (cid, k), v in types.items()
                        if k == 'staff' and cid == ssc_company.id).id)], limit=1)
if malak_staff:
    print(f"  already exists: {malak_staff.name}")
else:
    company = malak_labour.country_id and None  # noqa: F841 - readability
    print(f"  will create type      : {MALAK} Properties Development. Staff")
    print(f"  will create structure : {MALAK} Properties Development. Staff Pay")
    print(f"  copied from           : {model.name} ({len(model.rule_ids)} rules)")

# ---------------------------------------------------------------------------
title("3. the sixteen new records, by the job on their permit")


def kind_for(person):
    job = (person.job_title or '').lower()
    return 'labour' if any(word in job for word in LABOUR_WORDS) else 'staff'


placing = [(person, kind_for(person)) for person in generic]
for kind, number in Counter(k for _p, k in placing).most_common():
    print(f"  {kind:<8} {number}")
print()
for person, kind in sorted(placing, key=lambda r: (r[1], r[0].name)):
    print(f"  {kind:<8} {person.name[:40]:<40} {person.company_id.name[:26]:<26} "
          f"{person.job_title or '-'}")

# ---------------------------------------------------------------------------
title("4. what will be written")
print(f"  structure type corrected on {len(wrong)} contract(s)")
print(f"  structure type set on {len(placing)} new contract(s)")
print("  the rules are the same on every structure, so no amount changes -")
print("  what changes is which company computes the payslip and books it")

# ---------------------------------------------------------------------------
if APPLY:
    if not malak_staff:
        malak_labour_struct = Structure.search(
            [('type_id', '=', malak_labour.id)], limit=1)
        malak_staff = StructureType.create({
            'name': f'{MALAK} Properties Development. Staff',
            'country_id': malak_labour.country_id.id or False,
        })
        copy = model.copy({
            'name': f'{MALAK} Properties Development. Staff Pay',
            'type_id': malak_staff.id,
        })
        if malak_labour_struct and malak_labour_struct.journal_id:
            copy.journal_id = malak_labour_struct.journal_id.id

        # The source carries nineteen archived rules along with the thirty five
        # live ones - the provisions and the double payments retired earlier
        # today. A copy that woke them up would rebuild the fault it took a
        # morning to find, so each copied rule is set to whatever its original
        # is now.
        was_active = {rule.code: rule.active for rule in model.rule_ids}
        revived = copy.rule_ids.filtered(
            lambda r: r.active and not was_active.get(r.code, True))
        if revived:
            print(f"  archiving {len(revived)} copied rule(s) that are retired "
                  f"on the original: {sorted(set(revived.mapped('code')))}")
            revived.write({'active': False})
        types[(malak_company.id, 'staff')] = malak_staff
        print(f"created {malak_staff.name} and {copy.name} "
              f"with {len(copy.rule_ids)} rules")

    moved, failed = 0, []
    for person, _was, kind in wrong:
        want = types.get((person.company_id.id, kind))
        if not want:
            failed.append((person.name, f"no {kind} type for that company"))
            continue
        try:
            with env.cr.savepoint():
                person.current_version_id.structure_type_id = want.id
            moved += 1
        except Exception as error:
            failed.append((person.name, str(error).splitlines()[0][:60]))

    placed = 0
    for person, kind in placing:
        want = types.get((person.company_id.id, kind))
        if not want:
            failed.append((person.name, f"no {kind} type for that company"))
            continue
        vals = {'structure_type_id': want.id}
        if kind == 'staff':
            vals['work_entry_source'] = 'calendar'
        try:
            with env.cr.savepoint():
                person.current_version_id.write(vals)
            placed += 1
        except Exception as error:
            failed.append((person.name, str(error).splitlines()[0][:60]))
    env.cr.commit()

    title("APPLIED")
    print(f"  corrected {moved} | placed {placed} | refused {len(failed)}")
    for name, message in failed:
        print(f"      {name[:34]:<34} {message}")
    print()
    left = 0
    for person in Employee.with_context(active_test=True).search([]):
        stype = person.current_version_id.structure_type_id
        if not stype or stype.name == 'Employee' or \
                not same_company(stype.name, person.company_id):
            left += 1
    print(f"  contracts still not on their own company's structure: {left}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
