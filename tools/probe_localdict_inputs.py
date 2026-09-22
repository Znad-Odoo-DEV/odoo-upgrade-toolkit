"""What is in localdict['inputs'], and what the condition compares it against.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_localdict_inputs.py

fix_input_rule_condition.py found nothing to fix: condition_other_input_id is
already set on every one of these rules. That theory is dead, and it died the
same way the last two did - I checked whether a field was FILLED and not what
it was filled WITH. Presence is not identity, twice over now.

The condition is exactly this:

    return self.condition_other_input_id.code in localdict['inputs']

Two halves, and only two things can make it false:

  left    condition_other_input_id.code might not be the code the payslip
          carries. A rule coded SALARY_DEDUCTIONS may point its condition at
          some other input type entirely, and every report so far would show
          it as correctly configured.

  right   localdict['inputs'] is built by hr.payslip during computation. What
          goes into it - every input line, or only those whose type belongs to
          the structure, or keyed by something other than code - decides
          everything, and it is Enterprise source that exists on this server
          and nowhere else.

So this prints both halves and compares them, and dumps the code that builds
the dict rather than assuming it is keyed the obvious way.

Read-only.
"""
import inspect
import os
from collections import defaultdict

WIDTH = 116
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
SUFFIXES = ('Labour Pay', 'Staff Pay')

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


Rule = env['hr.salary.rule'].sudo()
Payslip = env['hr.payslip'].sudo()
Structure = env['hr.payroll.structure'].sudo()

# --------------------------------------------- 1. the left half of the test
title("1. what each rule's condition actually points at")
structures = Structure.search([]).filtered(
    lambda s: (s.name or '').endswith(SUFFIXES))

seen = set()
for structure in structures:
    for rule in Rule.search([('struct_id', '=', structure.id),
                             ('active', '=', True)]):
        if rule.condition_select not in ('input', 'property_input'):
            continue
        condition = rule.condition_other_input_id \
            if 'condition_other_input_id' in rule._fields else None
        amount = rule.amount_other_input_id \
            if 'amount_other_input_id' in rule._fields else None
        key = (rule.code, condition.id if condition else 0,
               amount.id if amount else 0, rule.condition_select)
        if key in seen:
            continue
        seen.add(key)
        print("\n  rule %-22s in %s" % (rule.code or '?', structure.name or '?'))
        print("      condition_select        %s" % rule.condition_select)
        print("      condition_other_input   %s"
              % ("[%s] %s  code=%s" % (condition.id, condition.name,
                                       condition.code) if condition else "EMPTY"))
        print("      amount_other_input      %s"
              % ("[%s] %s  code=%s" % (amount.id, amount.name, amount.code)
                 if amount else "EMPTY"))
        if condition and condition.code != rule.code:
            print("      !! the condition tests for %r while the rule is coded %r"
                  % (condition.code, rule.code))

# --------------------------------------------- 2. the right half of the test
title("2. how hr.payslip builds localdict['inputs']")
printed = False
for name in sorted(n for n in dir(Payslip) if 'localdict' in n.lower()
                   or 'local_dict' in n.lower()):
    member = getattr(type(Payslip), name, None)
    if not callable(member):
        continue
    print("\n  hr.payslip.%s" % name)
    try:
        for line in inspect.getsource(member).splitlines():
            print("    " + line)
        printed = True
    except Exception as error:  # noqa: BLE001
        print("    (source not available - %s)" % error)

if not printed:
    for name in ('_compute_payslip_lines', '_get_payslip_lines'):
        member = getattr(type(Payslip), name, None)
        if member is None:
            continue
        print("\n  hr.payslip.%s" % name)
        try:
            for line in inspect.getsource(member).splitlines()[:90]:
                print("    " + line)
        except Exception as error:  # noqa: BLE001
            print("    (source not available - %s)" % error)

# ------------------------------------------- 3. the codes actually carried
title("3. the input codes the August payslips carry")
carried = defaultdict(lambda: [0.0, 0])
for slip in Payslip.search([('input_line_ids', '!=', False)]):
    if not (slip.date_from and slip.date_from.strftime('%b').upper() == MONTH
            and str(slip.date_from.year) == str(YEAR)):
        continue
    if not (slip.struct_id.name or '').endswith(SUFFIXES):
        continue
    for line in slip.input_line_ids:
        carried[line.code or '?'][0] += line.amount or 0.0
        carried[line.code][1] += 1
for code, (total, count) in sorted(carried.items()):
    print("  %-24s %12.2f over %s line(s)" % (code, total, count))

# ---------------------------------- 4. the rules of those codes, whatever they use
title("4. every active rule whose code matches a carried input")
for code in sorted(carried):
    rules = Rule.search([('code', '=', code), ('active', '=', True)]).filtered(
        lambda r: (r.struct_id.name or '').endswith(SUFFIXES))
    print("\n  %s   -   %s active rule(s) in these structures" % (code, len(rules)))
    for rule in rules[:2]:
        condition = rule.condition_other_input_id \
            if 'condition_other_input_id' in rule._fields else None
        print("      [%s] seq %-5s condition_select=%-16s tests for %s"
              % (rule.id, rule.sequence, rule.condition_select,
                 condition.code if condition else '(nothing)'))
    if not rules:
        print("      !! no active rule of this code - the input can never be read")

env.cr.rollback()
title("read only - nothing was written")
