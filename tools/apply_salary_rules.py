"""Put the salary rules from the repo into the structure, so nobody pastes them.

    cd ~/src/user

    # report only, writes nothing:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/apply_salary_rules.py

    # same again, this time writing:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http 2>/dev/null < tools/apply_salary_rules.py

Copying a hundred lines of Python into a form by hand is how a rule ends up
half-pasted, or pasted into the wrong structure, or pasted once and then edited
on screen until nobody knows which version is live. The bodies are already in
git; this writes them where Odoo runs them.

For every rule the repo defines it will, inside the named structure:

  * create it when it is missing, with the name, category, sequence and
    condition its marker block states;
  * update the Python when it differs, showing the first differing line first;
  * fix the sequence, the category, the amount type, and un-archive it.

It never deletes and never touches a rule the repo does not define - the
localization's own rules in the same structure are listed and left alone.

Run it from the repo root, or set SSC_RULES_DIR: a script piped into odoo-bin
shell has no __file__ to find itself with.

Reads only unless SSC_APPLY=1.
"""
import os
import sys

APPLY = os.environ.get('SSC_APPLY') == '1'
STRUCTURE = os.environ.get('SSC_STRUCTURE') or 'SSC Monthly Pay'
RULES_DIR = os.path.abspath(os.environ.get('SSC_RULES_DIR') or 'payroll_rules')

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92

# What a marker's Category name means in hr.salary.rule.category. Odoo ships
# these codes; the name is matched first so a renamed category still resolves.
CATEGORY_CODES = {
    'basic': 'BASIC', 'allowance': 'ALW', 'net': 'NET',
    'deduction': 'DED', 'gross': 'GROSS', 'taxable salary': 'GROSS',
    'company contribution': 'COMP', 'provision': 'PROV',
}


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


sys.path.insert(0, RULES_DIR)
try:
    import rule_files
except Exception as error:                                       # noqa: BLE001
    rule_files = None
    load_error = error

title("1. the rules in the repo")

print(f"  {RULES_DIR}")
repo, problem = ({}, None)
if rule_files is None:
    problem = f"cannot load rule_files.py: {load_error}"
else:
    repo, problem = rule_files.read(RULES_DIR)
if problem:
    print(f"  !! {problem}")
    print("  Run from the repo root, or set SSC_RULES_DIR.")
for code, entry in repo.items():
    said = rule_files.settings_of(entry)
    print(f"  {code:<14} {entry['file']:<20} "
          f"seq={said.get('sequence', '?'):<4} "
          f"category={said.get('category', '?'):<12} "
          f"{said.get('name', '(no name)')}")

# --- the structure ------------------------------------------------------------

title(f"2. the structure - {STRUCTURE!r}")

structure = None
if 'hr.payroll.structure' not in env:
    print("  hr_payroll is not installed on this database")
else:
    structure = env['hr.payroll.structure'].sudo().search(
        [('name', '=', STRUCTURE)], limit=1)
    if not structure:
        print(f"  !! no structure named {STRUCTURE!r}. Create it first, or set "
              f"SSC_STRUCTURE.")
        names = env['hr.payroll.structure'].sudo().search([]).mapped('name')
        print(f"  structures that exist: {', '.join(names) or '(none)'}")
    else:
        print(f"  [{structure.id}] {structure.name}   "
              f"type={structure.type_id.name if structure.type_id else '-'}")

# --- what would change --------------------------------------------------------

title("3. what this run would do")

Rule = env['hr.salary.rule'].sudo() if 'hr.salary.rule' in env else None
Category = (env['hr.salary.rule.category'].sudo()
            if 'hr.salary.rule.category' in env else None)


def resolve_category(name):
    """The category record a marker's Category name refers to."""
    if not name or Category is None:
        return None
    found = Category.search([('name', '=ilike', name)], limit=1)
    if found:
        return found
    code = CATEGORY_CODES.get(name.strip().lower())
    return Category.search([('code', '=', code)], limit=1) if code else None


planned = []
if structure and Rule is not None:
    existing = {}
    for rule in Rule.search([('struct_id', '=', structure.id)], order='sequence, id'):
        existing.setdefault(rule.code, []).append(rule)

    for code, entry in repo.items():
        said = rule_files.settings_of(entry)
        body = rule_files.body_of(entry)
        wanted_name = said.get('name') or code
        wanted_sequence = (int(said['sequence'])
                           if said.get('sequence', '').isdigit() else None)
        category = resolve_category(said.get('category'))

        matches = existing.get(code) or []
        if len(matches) > 1:
            print(f"  {code:<14} !! {len(matches)} rules share this code - "
                  f"fix that by hand first, this run leaves them alone")
            continue

        if not matches:
            vals = {
                'name': wanted_name,
                'code': code,
                'struct_id': structure.id,
                'amount_select': 'code',
                'amount_python_compute': body,
                'condition_select': 'none',
            }
            if wanted_sequence is not None:
                vals['sequence'] = wanted_sequence
            if category:
                vals['category_id'] = category.id
            planned.append(('create', code, vals, None))
            print(f"  {code:<14} CREATE  {wanted_name!r}  seq="
                  f"{wanted_sequence}  category="
                  f"{category.name if category else '(unresolved)'}")
            if not category:
                print(f"                 !! category {said.get('category')!r} not "
                      f"found - the rule would be created without one")
            continue

        rule = matches[0]
        changes = {}
        notes = []
        if rule_files.executable(rule.amount_python_compute) != \
                rule_files.executable(body):
            changes['amount_python_compute'] = body
            notes.append("python")
        if rule.amount_select != 'code':
            changes['amount_select'] = 'code'
            notes.append(f"amount type ({rule.amount_select} -> code)")
        if wanted_sequence is not None and rule.sequence != wanted_sequence:
            changes['sequence'] = wanted_sequence
            notes.append(f"sequence ({rule.sequence} -> {wanted_sequence})")
        if category and rule.category_id != category:
            changes['category_id'] = category.id
            notes.append(f"category ({rule.category_id.name or '-'} -> "
                         f"{category.name})")
        if not rule.active:
            changes['active'] = True
            notes.append("un-archive")

        if changes:
            planned.append(('update', code, changes, rule))
            print(f"  {code:<14} UPDATE  " + ", ".join(notes))
            if 'amount_python_compute' in changes:
                old = rule_files.executable(rule.amount_python_compute)
                new = rule_files.executable(body)
                for index in range(max(len(old), len(new))):
                    left = old[index] if index < len(old) else '(end of database)'
                    right = new[index] if index < len(new) else '(end of repo)'
                    if left != right:
                        print(f"                 first change at line {index + 1}")
                        print(f"                   was : {left.strip()[:64]}")
                        print(f"                   will: {right.strip()[:64]}")
                        break
        else:
            print(f"  {code:<14} already matches the repo")

    untouched = [code for code in existing if code not in repo]
    if untouched:
        print(f"\n  left alone - the repo does not define them: "
              f"{', '.join(sorted(untouched))}")

# --- apply --------------------------------------------------------------------

title("summary")

if problem:
    print("  the repo rules could not be read, so nothing was compared")
elif not structure:
    print("  the structure was not found, so nothing was compared")
elif not planned:
    print("  every rule the repo defines is already in the structure, unchanged")
else:
    for action, code, _payload, _rule in planned:
        print(f"  . {action} {code}")

if not APPLY:
    env.cr.rollback()
    print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write.")
else:
    written = []
    for action, code, payload, rule in planned:
        if action == 'create':
            Rule.create(payload)
            written.append(f"created {code}")
        else:
            rule.write(payload)
            written.append(f"updated {code}: {', '.join(sorted(payload))}")
    env.cr.commit()
    print("\nwritten:")
    for line in written or ['(nothing)']:
        print(f"  . {line}")
    print("\nRe-run tools/check_salary_rules.py to confirm, then recompute any "
          "payslip that was already built on this structure.")
