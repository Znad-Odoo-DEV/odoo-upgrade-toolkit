"""Compare the salary rules on the database against the ones in the repo.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/check_salary_rules.py

    # a differently named structure, or rules kept elsewhere:
    SSC_STRUCTURE="SSC Monthly Pay" SSC_RULES_DIR=payroll_rules odoo-bin shell ...

The rules live in the database, because that is the only place Odoo runs them
from. The copies under payroll_rules/ exist so a change to how people are paid
leaves a trace in git. Nothing keeps the two in step: edit the screen and the
file is stale, edit the file and the screen never hears about it, and neither
side complains.

So this reads both and says exactly where they differ:

  * which expected rules are missing from the structure, and which rules are
    there that the repo knows nothing about;
  * sequence, category, condition and amount type against what the file's
    header says they should be - a rule at the wrong sequence computes with
    figures the rule before it has not produced yet;
  * the Python itself, comments and blank lines ignored, so only a real change
    to what gets computed is reported;
  * every name the DATABASE copy uses, checked against what safe_eval will
    actually provide - because it is the pasted text that runs, not the file.

Reads only. It rolls its transaction back before it exits.

Run it from the repo root, or set SSC_RULES_DIR: a script piped into odoo-bin
shell has no __file__ to find itself with.
"""
import os
import re
import sys

STRUCTURE = os.environ.get('SSC_STRUCTURE') or 'SSC Monthly Pay'
RULES_DIR = os.path.abspath(os.environ.get('SSC_RULES_DIR') or 'payroll_rules')

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92

sys.path.insert(0, RULES_DIR)
try:
    import rule_files
except Exception as error:                                       # noqa: BLE001
    rule_files = None
    LOAD_ERROR = error


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


# --- what the repo holds ------------------------------------------------------

title("1. rules in the repo")

findings = []

if rule_files is None:
    repo, problem = {}, f'cannot load rule_files.py: {LOAD_ERROR}'
else:
    repo, problem = rule_files.read(RULES_DIR)
print(f"  {RULES_DIR}")
if problem:
    # Without the repo copies there is nothing to compare against, and saying
    # "matches" at the end would be a clean bill of health for a check that
    # never ran.
    findings.append(f"the repo rules were not read: {problem}")
    print(f"  !! {problem}")
    print("  Run from the repo root, or set SSC_RULES_DIR to where the rules are.")
for code, entry in repo.items():
    said = rule_files.settings_of(entry)
    print(f"  {code:<14} {entry['file']:<20} "
          f"seq={said.get('sequence', '?'):<4} "
          f"category={said.get('category', '?'):<12} "
          f"{len(rule_files.executable(rule_files.body_of(entry))):>3} line(s) of code")
if not repo and not problem:
    findings.append("no rule bodies found in the repo directory")
    print("  (nothing found - a rule file needs a '### RULE ... Code: XXX' marker)")

# --- what the database holds --------------------------------------------------

title(f"2. rules on the database - structure {STRUCTURE!r}")

if 'hr.payroll.structure' not in env:
    print("  hr_payroll is not installed on this database")
    structure = None
else:
    structure = env['hr.payroll.structure'].sudo().search(
        [('name', '=', STRUCTURE)], limit=1)
    if not structure:
        print(f"  !! no structure named {STRUCTURE!r}")
        names = env['hr.payroll.structure'].sudo().search([]).mapped('name')
        print(f"  structures that do exist: {', '.join(names) or '(none)'}")

db_rules = {}
if structure:
    print(f"  [{structure.id}] {structure.name}   "
          f"type={structure.type_id.name if structure.type_id else '-'}")
    rules = env['hr.salary.rule'].sudo().search(
        [('struct_id', '=', structure.id)], order='sequence, id')
    print(f"  {len(rules)} rule(s):\n")
    for rule in rules:
        db_rules.setdefault(rule.code, []).append(rule)
        category = rule.category_id.code if rule.category_id else '-'
        print(f"  {rule.sequence:>4}  {rule.code:<16} {rule.name[:30]:<30} "
              f"cat={category:<8} {rule.amount_select:<10} "
              f"{'active' if rule.active else 'ARCHIVED'}")

# --- where they disagree ------------------------------------------------------

title("3. repo against database")

for code, entry in repo.items():
    matches = db_rules.get(code) or []
    if not matches:
        findings.append(f"{code}: in the repo, MISSING from the structure")
        print(f"  {code:<14} MISSING from the structure ({entry['file']})")
        continue
    if len(matches) > 1:
        findings.append(f"{code}: {len(matches)} rules share this code")
        print(f"  {code:<14} !! {len(matches)} rules share this code")
    rule = matches[0]
    said = rule_files.settings_of(entry)

    notes = []
    wanted_sequence = said.get('sequence')
    if wanted_sequence and wanted_sequence.isdigit():
        if rule.sequence != int(wanted_sequence):
            notes.append(f"sequence {rule.sequence} (file says {wanted_sequence})")
    wanted_category = (said.get('category') or '').lower()
    actual_category = (rule.category_id.name or '').lower()
    if wanted_category and wanted_category not in actual_category:
        notes.append(f"category {rule.category_id.name!r} "
                     f"(file says {said['category']!r})")
    if rule.amount_select != 'code':
        notes.append(f"amount type {rule.amount_select!r}, not Python Code")
    if not rule.active:
        notes.append("ARCHIVED")

    file_code = rule_files.executable(rule_files.body_of(entry))
    db_code = rule_files.executable(rule.amount_python_compute)
    if file_code != db_code:
        notes.append(f"CODE DIFFERS ({len(db_code)} lines on the database, "
                     f"{len(file_code)} in the repo)")

    if notes:
        findings.extend(f"{code}: {note}" for note in notes)
        print(f"  {code:<14} " + "; ".join(notes))
    else:
        print(f"  {code:<14} matches the repo")

for code in db_rules:
    if code not in repo:
        print(f"  {code:<14} on the database, not in the repo "
              f"(fine for rules nobody tracks)")

# --- the first differing line, so a diff is actionable ------------------------

for code, entry in repo.items():
    matches = db_rules.get(code) or []
    if not matches:
        continue
    file_code = rule_files.executable(rule_files.body_of(entry))
    db_code = rule_files.executable(matches[0].amount_python_compute)
    if file_code == db_code:
        continue
    print(f"\n  --- {code}: first difference ---")
    for index in range(max(len(file_code), len(db_code))):
        left = file_code[index] if index < len(file_code) else '(end of file)'
        right = db_code[index] if index < len(db_code) else '(end of database)'
        if left != right:
            print(f"    line {index + 1}")
            print(f"      repo: {left.strip()[:70]}")
            print(f"      db  : {right.strip()[:70]}")
            break

# --- will the pasted text even run --------------------------------------------

title("4. names the DATABASE copy uses")

sys.path.insert(0, RULES_DIR)
try:
    import check_rule_names
except Exception as error:                                       # noqa: BLE001
    findings.append(f"the pasted code was NOT name-checked: {error}")
    print(f"  cannot load check_rule_names.py from {RULES_DIR}: {error}")
    check_rule_names = None

if check_rule_names is not None:
    import ast
    for code, rules in sorted(db_rules.items()):
        rule = rules[0]
        if rule.amount_select != 'code' or not rule.amount_python_compute:
            continue
        try:
            tree = ast.parse(rule.amount_python_compute)
        except SyntaxError as error:
            findings.append(f"{code}: does not parse - {error}")
            print(f"  {code:<14} DOES NOT PARSE: {error}")
            continue
        bound = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                bound.add(node.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                bound.add(node.name)
                for argument in node.args.args:
                    bound.add(argument.arg)
            elif isinstance(node, ast.comprehension):
                for sub in ast.walk(node.target):
                    if isinstance(sub, ast.Name):
                        bound.add(sub.id)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                bound.add(node.name)
        read = {node.id for node in ast.walk(tree)
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
        unknown = sorted(read - bound
                         - check_rule_names.PAYSLIP_LOCALS
                         - check_rule_names.SAFE_EVAL_BUILTINS)
        if unknown:
            findings.append(f"{code}: uses {unknown}, which safe_eval will not "
                            f"provide")
            print(f"  {code:<14} FAILS AT COMPUTE -> {unknown}")
        else:
            print(f"  {code:<14} ok")

title("summary")

if not findings:
    print("  the structure matches the repo, and every rule can run")
else:
    for line in findings:
        print(f"  . {line}")

env.cr.rollback()
print("\nread only - nothing written.")
