"""Push the repo's rule bodies into EVERY structure that already runs them.

    cd ~/src/user

    # report only, writes nothing:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/apply_salary_rules_everywhere.py

    # same again, this time writing:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http 2>/dev/null < tools/apply_salary_rules_everywhere.py

tools/apply_salary_rules.py does one structure, named by SSC_STRUCTURE. There
are eleven, one per company and population, and a change to how a day is priced
belongs in all of them at once - a rule fixed in six structures and missed in
five is worse than one fixed in none, because the disagreement is invisible
until two employees of different companies are paid differently for the same
month.

So this walks the rules instead of the structures. For every code the repo
defines it finds every hr.salary.rule carrying that code, anywhere, and updates
the Python where it differs from the file.

WHAT IT WILL NOT DO

It never creates a rule and never changes a structure's shape - no sequence, no
category, no condition. A structure that is missing a rule entirely is reported
and left alone: adding one is a decision about that structure, and
apply_salary_rules.py is the tool that makes it, one structure at a time and
with the marker block to say what the rule should be.

SCOPE IS REQUIRED, AND THAT IS THE POINT

Matching on the rule code alone is not a scope. BASIC and NET are the most
generic codes in Odoo payroll - Default Structure Rules Set, Regular Pay,
Worker Pay and the localisation's own structures all have one - and a run
keyed on the code alone writes the SSC bodies into every one of them. That
happened on production on 2026-08-27 and is why this now refuses to run
without being told which structures it may touch.

    SSC_STRUCTURES="SAUD SHEHATHA CONSTRUCTION L.L.C Labour Pay,..."

or, for the usual case, the suffix every structure this company built ends in:

    SSC_STRUCTURE_LIKE="Labour Pay,Staff Pay"

Nothing outside that scope is read or written, whatever code it carries.

Reads only unless SSC_APPLY=1.
"""
import os
import sys

APPLY = os.environ.get('SSC_APPLY') == '1'
RULES_DIR = os.path.abspath(os.environ.get('SSC_RULES_DIR') or 'payroll_rules')
NAMES = [n.strip() for n in
         (os.environ.get('SSC_STRUCTURES') or '').split(',') if n.strip()]
SUFFIXES = [n.strip() for n in
            (os.environ.get('SSC_STRUCTURE_LIKE') or '').split(',') if n.strip()]
WIDTH = 92

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

sys.path.insert(0, RULES_DIR)
try:
    import rule_files
except Exception as error:  # noqa: BLE001
    rule_files = None
    IMPORT_ERROR = str(error)


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


title("1. the rules in the repo")
print(f"  {RULES_DIR}")
if rule_files is None:
    print(f"  !! cannot import rule_files: {IMPORT_ERROR}")
    print("  Run from the repo root, or set SSC_RULES_DIR.")
    repo, problem = {}, IMPORT_ERROR
else:
    repo, problem = rule_files.read(RULES_DIR)
    if problem:
        print(f"  !! {problem}")
for code, entry in sorted(repo.items()):
    print(f"  {code:<12} {os.path.basename(entry['file'])}")
if not repo:
    print("  (nothing found)")


title("2. where those rules live")

Rule = env['hr.salary.rule'].sudo() if 'hr.salary.rule' in env else None
if Rule is None:
    print("  hr_payroll is not installed on this database")
    repo = {}

if not (NAMES or SUFFIXES):
    print("  !! no scope given. Set SSC_STRUCTURES to exact names, or "
          "SSC_STRUCTURE_LIKE to name endings.")
    print("  Refusing to run: BASIC and NET exist in every structure Odoo "
          "ships, and a run without a scope writes into all of them.")
    repo = {}


def in_scope(structure):
    name = structure.name or ''
    return name in NAMES or any(name.endswith(s) for s in SUFFIXES)


rules_by_code = {}
if repo and Rule is not None:
    for rule in Rule.search([('code', 'in', list(repo))], order='struct_id, sequence, id'):
        if in_scope(rule.struct_id):
            rules_by_code.setdefault(rule.code, []).append(rule)

structures = set()
for code, rules in rules_by_code.items():
    structures.update(rule.struct_id for rule in rules)
print(f"  {sum(len(v) for v in rules_by_code.values())} rule(s) across "
      f"{len(structures)} structure(s)")
for structure in sorted(structures, key=lambda s: s.name or ''):
    codes = sorted(
        code for code, rules in rules_by_code.items()
        if any(rule.struct_id == structure for rule in rules))
    missing = sorted(set(repo) - set(codes))
    note = f"   missing: {', '.join(missing)}" if missing else ""
    print(f"  [{structure.id:>3}] {structure.name}   {', '.join(codes)}{note}")

if repo and not structures:
    print("  !! no structure carries any of these rules. Use "
          "tools/apply_salary_rules.py to put them in one first.")


title("3. what this run would do")

planned = []
for code, rules in sorted(rules_by_code.items()):
    body = rule_files.body_of(repo[code])
    for rule in rules:
        changes = {}
        # Compared on the lines that actually run, so a difference in
        # commentary is not reported as a difference in pay.
        if rule_files.executable(rule.amount_python_compute) !=                 rule_files.executable(body):
            changes['amount_python_compute'] = body
        if rule.amount_select != 'code':
            changes['amount_select'] = 'code'
        if not changes:
            continue
        planned.append((code, rule, changes))
        where = rule.struct_id.name or f"structure {rule.struct_id.id}"
        what = "python" if 'amount_python_compute' in changes else ""
        if 'amount_select' in changes:
            what = (what + " + amount type").strip(" +")
        print(f"  {code:<12} {where:<52} {what}")

if not planned:
    print("  every rule matches the repo already")


title("summary")

if problem:
    print("  the repo rules could not be read, so nothing was compared")
elif not planned:
    print("  nothing to write")
else:
    by_code = {}
    for code, rule, _changes in planned:
        by_code.setdefault(code, set()).add(rule.struct_id.id)
    for code, struct_ids in sorted(by_code.items()):
        count = sum(1 for c, _r, _ch in planned if c == code)
        print(f"  . {code}: {count} rule(s) across "
              f"{len(struct_ids)} structure(s)")

if not APPLY:
    env.cr.rollback()
    print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write.")
else:
    for _code, rule, changes in planned:
        rule.write(changes)
    env.cr.commit()
    print(f"\nwritten: {len(planned)} rule(s) updated.")
    print("Re-run tools/check_salary_rules.py per structure to confirm, then "
          "recompute any payslip already built on one of them - a rule change "
          "does not reach a payslip that is already computed.")
