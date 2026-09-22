"""Two input types can share a code. A rule matches on identity, not on code.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_input_type_identity.py

Recomputing changed nothing: NET moved by 0.00 on every payslip tested, so the
payslips are current and the rules genuinely do not fire. The rules are active
and identical to Odoo's own UAE originals. The inputs are present with the
right codes. Every check made so far compared CODES - and a code is not an
identity.

Two things would produce exactly this, and both are invisible to a comparison
by code:

  1. more than one hr.payslip.input.type carries the same code. The rule points
     at one record through amount_other_input_id; the payslip input was created
     against another. Same code on the screen, different ids underneath, and
     condition_select='input' never matches.

  2. hr.payslip.input.type.struct_ids limits which structures a type belongs
     to. A type not attached to the Labour Pay structure may be invisible to
     the rules of that structure however the input line is created.

So this prints identities and nothing else: every input type with these codes
and its id, which struct_ids it is restricted to, which type each payslip input
actually points at, and which type each rule points at - then whether those two
ids are the same record.

It also prints _satisfy_condition from the running registry, because what
condition_select='input' requires is decided there and hr_payroll is Enterprise
- the source is on this server and nowhere else.

Read-only.
"""
import inspect
import os
from collections import defaultdict

WIDTH = 116
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
CODES = [c.strip() for c in (os.environ.get('SSC_CODES') or
         'OTHER_EARNINGS,SALARY_DEDUCTIONS,ADVREC,REIMBURSEMENT').split(',')
         if c.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


InputType = env['hr.payslip.input.type'].sudo()
Payslip = env['hr.payslip'].sudo()
Rule = env['hr.salary.rule'].sudo()

# ------------------------------------------------ 1. what the option requires
title("1. what condition_select='input' actually does")
field = Rule._fields.get('condition_select')
print("  condition_select options: %s"
      % (getattr(field, 'selection', None) if field else 'no such field'))
for name in ('_satisfy_condition', '_compute_rule'):
    member = getattr(type(Rule), name, None)
    if member is None:
        print("\n  %s does not exist on this version" % name)
        continue
    print("\n  hr.salary.rule.%s" % name)
    try:
        for line in inspect.getsource(member).splitlines():
            print("    " + line)
    except Exception as error:  # noqa: BLE001
        print("    (source not available - %s)" % error)

# ---------------------------------------------------- 2. every type per code
title("2. every hr.payslip.input.type carrying one of these codes")
by_code = defaultdict(list)
for input_type in InputType.search([]):
    if input_type.code in CODES:
        by_code[input_type.code].append(input_type)

for code in CODES:
    found = by_code.get(code, [])
    print("\n  %s   -   %s type(s)" % (code, len(found)))
    if len(found) > 1:
        print("      !! more than one record shares this code - a rule matches"
              " one of them by id")
    for input_type in found:
        structs = input_type.struct_ids if 'struct_ids' in input_type._fields \
            else None
        print("      [%s] %-34s active=%s" % (input_type.id,
                                              (input_type.name or '?')[:34],
                                              input_type.active))
        if structs is None:
            print("          (no struct_ids field on this version)")
        elif not structs:
            print("          struct_ids: none - available to every structure")
        else:
            print("          struct_ids: %s" % ", ".join(
                (s.name or '?') for s in structs))

# ------------------------------------- 3. which type the payslip inputs use
title("3. the input types the August payslip inputs actually point at")
used = defaultdict(lambda: defaultdict(int))
for slip in Payslip.search([('input_line_ids', '!=', False)]):
    if not (slip.date_from and slip.date_from.strftime('%b').upper() == MONTH
            and str(slip.date_from.year) == str(YEAR)):
        continue
    if not (slip.struct_id.name or '').endswith(('Labour Pay', 'Staff Pay')):
        continue
    for line in slip.input_line_ids:
        used[line.code or '?'][line.input_type_id.id] += 1

for code in sorted(used):
    print("\n  %s" % code)
    for type_id, count in sorted(used[code].items(), key=lambda kv: -kv[1]):
        input_type = InputType.browse(type_id)
        print("      type [%s] %-34s on %s input line(s)"
              % (type_id, (input_type.name or '?')[:34], count))

# ----------------------------------- 4. which type the rules point at, and if same
title("4. the rule's input type against the payslip's - by id, not by code")
structures = env['hr.payroll.structure'].sudo().search([]).filtered(
    lambda s: (s.name or '').endswith(('Labour Pay', 'Staff Pay')))
for structure in structures:
    rules = Rule.search([('struct_id', '=', structure.id),
                         ('code', 'in', CODES), ('active', '=', True)])
    if not rules:
        continue
    print("\n  %s" % (structure.name or '?'))
    for rule in rules:
        pointed = rule.amount_other_input_id \
            if 'amount_other_input_id' in rule._fields else None
        seen = sorted(used.get(rule.code, {}))
        if pointed:
            same = pointed.id in seen
            print("      %-20s rule points at type [%s] %-24s   payslips use %s"
                  % (rule.code, pointed.id, (pointed.name or '?')[:24],
                     seen or 'none'))
            if seen and not same:
                print("          !! DIFFERENT RECORD - same code, and the rule"
                      " will never match")
        else:
            print("      %-20s rule points at NO input type   condition_select=%s"
                  % (rule.code, rule.condition_select))
            print("          !! condition_select='input' with nothing to test"
                  " against cannot pass" if rule.condition_select == 'input'
                  else "")

env.cr.rollback()
title("read only - nothing was written")
