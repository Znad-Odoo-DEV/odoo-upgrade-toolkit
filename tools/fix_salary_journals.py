"""Every payslip of every company gets its company's salary journal, whoever is looking.

    cd ~/src/user
    # report, and prove it in a savepoint:
    odoo-bin shell -d <database> --no-http < tools/fix_salary_journals.py 2>&1 | grep -v " INFO "
    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/fix_salary_journals.py 2>&1 | grep -v " INFO "

WHAT WAS WRONG

hr.payroll.structure.journal_id is company-dependent: one field, one value
per company, keyed by whichever company is ACTIVE when it is read. The payslip
copies it once, at creation, into its own stored journal_id - read in the
context of whoever created the payslip. Royal Arrow's structure holds Royal
Arrow's journal under Royal Arrow's key and nothing under Saud Shehatha's, so
a Royal Arrow payslip made while Saud Shehatha was the active company - which
is how every batch has been made - copies an empty journal and keeps it. It
cannot be validated and its entry has nowhere to go. Haitham Adnan Shela,
payslip 1694, is one of them.

THE FIX, WITHOUT TOUCHING CODE

A structure only ever serves its own company's employees (every contract is on
its own company's structure - tools/fix_structure_types.py, zero exceptions).
So the structure's own journal is the right answer under EVERY company's key,
and that is what is written: Royal Arrow's journal under Saud's key, Malak's
key and Royal Wooden's key too, on Royal Arrow's structures. Whoever creates
the payslip, the copy is right. The earlier fix cleared the foreign keys on
purpose; that reading was too strict and this is why.

Then every payslip not yet validated is given its company's journal, because
the copy already taken cannot be un-taken.

The company's journal comes from res.company.ssc_salary_journal_id - the same
journal the ssc salary batch posts to - and, if that is empty, the company's
own general journal with the code SLR. Nothing is guessed from a name.

PROVED BEFORE WRITING

Inside a savepoint, one draft payslip per company is re-created with a
DIFFERENT company active, and its journal is read back. All four must come
out as their own company's journal. Then the savepoint is dropped.

Reads only unless SSC_APPLY=1. Validated and paid payslips are listed, never
changed.
"""
import os

WIDTH = 120
APPLY = os.environ.get('SSC_APPLY') == '1'
SUFFIXES = ('Labour Pay', 'Staff Pay')
JOURNAL_CODE = 'SLR'

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


Company = env['res.company'].sudo()
Journal = env['account.journal'].sudo()
Structure = env['hr.payroll.structure'].sudo()
Payslip = env['hr.payslip'].sudo()

companies = Company.search([], order='id')
structures = Structure.search([]).filtered(
    lambda s: (s.name or '').endswith(SUFFIXES)).sorted('id')


def company_of(structure):
    """The company whose name the structure's name starts with - the WHOLE
    name, because ROYAL ARROW and ROYAL WOODEN share a first word."""
    name = (structure.name or '').strip().upper()
    hits = [c for c in companies if name.startswith((c.name or '').strip().upper())]
    if len(hits) != 1:
        return None
    return hits[0]


def journal_of(company):
    if company.ssc_salary_journal_id:
        return company.ssc_salary_journal_id
    return Journal.with_company(company).search([
        ('company_id', '=', company.id), ('code', '=', JOURNAL_CODE),
        ('type', '=', 'general')], limit=1)


# ------------------------------------------------------------ 1. the journals
title("1. each company's salary journal")
journals = {}
for company in companies:
    journal = journal_of(company)
    journals[company] = journal
    print("  [%s] %-44s -> %s" % (company.id, (company.name or '?')[:44],
                                   journal.display_name if journal else "!! NONE"))
if not all(journals.values()):
    print("\n  a company has no salary journal - set res.company.ssc_salary_journal_id "
          "(or make an SLR general journal) and run again. Nothing is written.")
    raise SystemExit

# ------------------------------------------- 2. the structures, every key
title("2. what each structure answers under each company's key")
plan = []
for structure in structures:
    owner = company_of(structure)
    if owner is None:
        print("  !! %s: cannot tell which company owns it - left alone" % structure.name)
        continue
    own = journals[owner]
    print("\n  [%s] %s   (owner: %s -> %s)"
          % (structure.id, structure.name, owner.name[:30], own.display_name))
    for company in companies:
        read = structure.with_company(company).journal_id
        fix = read != own
        if fix:
            plan.append((structure, company, own))
        print("      under %-40s %-36s %s"
              % ((company.name or '?')[:40],
                 read.display_name if read else "(empty)",
                 "-> " + own.display_name if fix else "ok"))
print("\n  %s key(s) to write on %s structure(s)"
      % (len(plan), len({s.id for s, _c, _j in plan})))

# ------------------------------------------------------- 3. the payslips
title("3. payslips carrying no journal, or another company's")
to_fix, locked = [], []
for slip in Payslip.search([]):
    own = journals.get(slip.company_id)
    if not own:
        continue
    if slip.journal_id == own:
        continue
    if slip.state in ('draft', 'verify'):
        to_fix.append((slip, own))
    else:
        locked.append((slip, own))
by_company = {}
for slip, own in to_fix:
    by_company.setdefault(slip.company_id, [0, 0])
    by_company[slip.company_id][0 if not slip.journal_id else 1] += 1
for company, (empty, wrong) in sorted(by_company.items(), key=lambda kv: kv[0].id):
    print("  %-44s %4s empty   %4s another company's" % ((company.name or '?')[:44], empty, wrong))
print("  %s payslip(s) to give their journal" % len(to_fix))
if locked:
    print("  !! %s validated/paid payslip(s) hold no journal or the wrong one and are "
          "left alone:" % len(locked))
    for slip, own in locked[:10]:
        print("      %-40s %-10s %s" % ((slip.employee_id.name or '?')[:40], slip.state,
                                         slip.journal_id.display_name or "(empty)"))

# ------------------------------------------------------------- 4. the proof
title("4. the proof: a payslip made with the WRONG company active")
proved, failed = [], []


class _Proved(Exception):
    pass


try:
    with env.cr.savepoint():
        for structure, company, own in plan:
            structure.with_company(company).journal_id = own
        for company in companies:
            other = next((c for c in companies if c != company), company)
            sample = Payslip.search([('company_id', '=', company.id),
                                     ('state', '=', 'draft')], limit=1)
            if not sample:
                print("  %-44s no draft payslip to copy - not proved" % (company.name or '?')[:44])
                continue
            made = Payslip.with_company(other).create({
                'name': "journal proof", 'employee_id': sample.employee_id.id,
                'struct_id': sample.struct_id.id,
                'date_from': sample.date_from, 'date_to': sample.date_to,
            })
            got = made.journal_id
            ok = got == journals[company]
            (proved if ok else failed).append(company)
            print("  %-44s made under %-24s journal %-28s %s"
                  % ((company.name or '?')[:44], (other.name or '?')[:24],
                     got.display_name if got else "(empty)", "ok" if ok else "!! WRONG"))
        raise _Proved()
except _Proved:
    pass

# ------------------------------------------------------------------ 5. write
title("5. summary")
if failed:
    print("  the proof failed for %s - nothing is written" % ", ".join(c.name for c in failed))
    raise SystemExit
if not APPLY:
    print("  report only - nothing written. Re-run with SSC_APPLY=1.")
    raise SystemExit

for structure, company, own in plan:
    structure.with_company(company).journal_id = own
for slip, own in to_fix:
    slip.journal_id = own
env.cr.commit()
title("APPLIED")
print("  %s structure key(s) written, %s payslip(s) given their journal"
      % (len(plan), len(to_fix)))
