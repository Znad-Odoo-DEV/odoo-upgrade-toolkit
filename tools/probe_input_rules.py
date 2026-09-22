"""Why a salary rule that reads an input produces no line.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/probe_input_rules.py

reconcile_payrolls.py section 4b settled that every input written this month is
inert: OTHER_EARNINGS over 47 Royal Arrow payslips and 232 Saud ones,
SALARY_DEDUCTIONS over 49, ADVREC over 8, REIMBURSEMENT over 7 - and not one
produced a line. A rule of the right code exists in every case. None of them
fire.

Four things stop a rule that otherwise looks correct, and the report reads the
same for all four, so all four are printed rather than the likeliest:

  active            an archived rule stays attached to its structure and is
                    returned by any search made with active_test=False, which
                    is exactly how it was found. It simply never runs.
  condition         condition_select and its range/python. A condition that
                    evaluates false produces no line and says nothing.
  amount            amount_select and the python or the input type it points
                    at. A python that never assigns result yields nothing.
  appears_on_payslip  a rule can affect the net while showing no line - so a
                    missing line is not by itself proof the money was lost.
                    The NET arithmetic already proved that separately.

Every rule is named "(copy)", and REIMBURSEMENT appears twice at the same
sequence, so where the duplicates came from matters too: the original is
printed beside the copy wherever one exists, with the fields that differ
between them called out. A copy that lost its condition or its category is the
likeliest single explanation for all of them at once.

Read-only.
"""
import os
from collections import defaultdict

WIDTH = 116
CODES = [c.strip() for c in (os.environ.get('SSC_CODES') or
         'OTHER_EARNINGS,SALARY_DEDUCTIONS,ADVREC,REIMBURSEMENT,ADV').split(',')
         if c.strip()]
SUFFIXES = ('Labour Pay', 'Staff Pay')

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def show(rule, indent="      "):
    print("%s[%s] %-22s %-32s sequence %s"
          % (indent, rule.id, rule.code or '?', (rule.name or '')[:32],
             rule.sequence))
    print("%s    active=%s  appears_on_payslip=%s  category=%s"
          % (indent, rule.active,
             rule.appears_on_payslip if 'appears_on_payslip' in rule._fields
             else '?',
             rule.category_id.name if rule.category_id else '(none)'))
    print("%s    struct=%s" % (indent, rule.struct_id.name or '(none)'))
    print("%s    condition_select=%s   amount_select=%s"
          % (indent, rule.condition_select, rule.amount_select))
    for field in ('condition_range', 'condition_range_min', 'condition_range_max'):
        if field in rule._fields and rule[field]:
            print("%s    %s = %s" % (indent, field, rule[field]))
    if 'amount_other_input_id' in rule._fields and rule.amount_other_input_id:
        print("%s    amount_other_input_id = %s (code %s)"
              % (indent, rule.amount_other_input_id.name,
                 rule.amount_other_input_id.code))
    for field in ('condition_python', 'amount_python_compute'):
        value = rule[field] if field in rule._fields else None
        if not value:
            continue
        print("%s    %s:" % (indent, field))
        for line in str(value).strip().splitlines():
            print("%s        %s" % (indent, line))


Rule = env['hr.salary.rule'].sudo()
Structure = env['hr.payroll.structure'].sudo()
structures = Structure.search([]).filtered(
    lambda s: (s.name or '').endswith(SUFFIXES))

title("1. the rules that should be consuming this month's inputs")
print("  %s structure(s) whose name ends in %s" % (len(structures), SUFFIXES))

by_code = defaultdict(list)
for structure in structures:
    for rule in Rule.search([('struct_id', '=', structure.id)]):
        if rule.code in CODES:
            by_code[rule.code].append(rule)

for code in CODES:
    found = by_code.get(code, [])
    title("%s   -   %s rule(s) across the structures" % (code, len(found)), '-')
    if not found:
        print("      no rule of this code in any Labour or Staff structure")
        continue
    inactive = [r for r in found if not r.active]
    if inactive:
        print("      !! %s of %s are ARCHIVED - an archived rule never runs, and"
              % (len(inactive), len(found)))
        print("         a search with active_test=False still returns it, which"
              " is how it looked present")
    # One structure's worth is enough to read; the rest are copies of it.
    seen = set()
    for rule in found:
        key = (rule.code, rule.sequence, rule.condition_select,
               rule.amount_select, rule.condition_python,
               rule.amount_python_compute, rule.active)
        if key in seen:
            continue
        seen.add(key)
        show(rule)
        print("")
    if len(found) > len(seen):
        print("      (%s further rule(s) are identical to one shown above)"
              % (len(found) - len(seen)))

# ------------------------------------------------- duplicates within a structure
title("2. the same code twice in one structure")
for structure in structures:
    counts = defaultdict(list)
    for rule in Rule.search([('struct_id', '=', structure.id)]):
        counts[rule.code or '?'].append(rule)
    doubled = {code: rules for code, rules in counts.items() if len(rules) > 1}
    if not doubled:
        continue
    print("\n  %s" % (structure.name or '?'))
    for code, rules in sorted(doubled.items()):
        print("      %-22s %s copies   ids %s   active %s"
              % (code, len(rules), ", ".join(str(r.id) for r in rules),
                 ", ".join(str(r.active) for r in rules)))

# ------------------------------------------ what the originals look like
title("3. the same code outside these structures, for comparison")
print("""  Every rule above is named "(copy)". If the thing it was copied from still
  exists and differs, the difference is the bug - and it is one edit, not
  fifty four.
""")
for code in CODES:
    others = Rule.search([('code', '=', code)]).filtered(
        lambda r: r not in by_code.get(code, []))
    if not others:
        continue
    print("  %s   -   %s rule(s) elsewhere" % (code, len(others)))
    for rule in others[:3]:
        show(rule, indent="      ")
        print("")

env.cr.rollback()
title("read only - nothing was written")
