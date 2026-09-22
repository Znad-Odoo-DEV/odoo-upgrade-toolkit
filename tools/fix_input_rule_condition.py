"""The condition reads condition_other_input_id, and it is empty.

    cd ~/src/user

    # report, and prove the fix on a real payslip without keeping it:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/fix_input_rule_condition.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/fix_input_rule_condition.py

hr.salary.rule._satisfy_condition, read out of the running registry:

    if self.condition_select == 'input':
        return self.condition_other_input_id.code in localdict['inputs']

condition_other_input_id - not amount_other_input_id, which is the field this
session kept checking and the field that is correctly set. On every Labour and
Staff structure, SALARY_DEDUCTIONS and ADVREC use condition_select='input' with
condition_other_input_id empty, so the test evaluates '' in inputs, which is
False for every payslip ever computed. The rule never fires and never
complains. OTHER_EARNINGS points at input type 33 through its AMOUNT field
while its CONDITION field is the one being tested.

Everything else was already sound and is worth stating, because each was a
suspect in turn: the rules are active; they match Odoo's own UAE originals; one
input type exists per code; each is attached to all eight structures; and the
August input lines point at exactly those type ids. The payslips are current -
recomputing six of them moved NET by 0.00.

THE FIX

  For every rule in a Labour or Staff structure with condition_select='input'
  and no condition_other_input_id, set it to the input type whose code equals
  the rule's own code. Nothing else is touched: the amount side already works,
  and SALARY_DEDUCTIONS and ADVREC take their amount from python that reads the
  input by name.

  A rule whose code has no matching input type is reported and skipped rather
  than pointed at something approximate.

IT PROVES ITSELF BEFORE IT IS KEPT

  In report mode this applies the change inside a savepoint, recomputes a real
  payslip that carries one of these inputs, prints the lines that appear and
  the net that moves, and rolls the whole thing back. A fix that cannot be
  shown to work on a real payslip is a guess, and this session has already
  spent two rounds on those.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

WIDTH = 112
APPLY = os.environ.get('SSC_APPLY') == '1'
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
SUFFIXES = ('Labour Pay', 'Staff Pay')
PROVE = int(os.environ.get('SSC_PROVE') or 3)

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value):
    return "{:>12,.2f}".format(value or 0.0)


Rule = env['hr.salary.rule'].sudo()
InputType = env['hr.payslip.input.type'].sudo()
Payslip = env['hr.payslip'].sudo()
Structure = env['hr.payroll.structure'].sudo()

types_by_code = {}
for input_type in InputType.search([]):
    types_by_code.setdefault(input_type.code, input_type)

structures = Structure.search([]).filtered(
    lambda s: (s.name or '').endswith(SUFFIXES))

# ------------------------------------------------------------- 1. the damage
title("1. rules whose condition can never pass")
broken, unfixable = [], []
for structure in structures:
    for rule in Rule.search([('struct_id', '=', structure.id),
                             ('active', '=', True)]):
        if rule.condition_select != 'input':
            continue
        if rule.condition_other_input_id:
            continue
        target = types_by_code.get(rule.code)
        (broken if target else unfixable).append((rule, target))

if not broken and not unfixable:
    print("  none - every condition_select='input' rule has its input type set")
by_code = defaultdict(list)
for rule, target in broken:
    by_code[rule.code].append((rule, target))
print("  %-22s %-34s %s" % ("rule code", "will point at", "rules"))
print("  " + "-" * (WIDTH - 4))
for code, group in sorted(by_code.items()):
    target = group[0][1]
    print("  %-22s [%s] %-29s %s"
          % (code, target.id, (target.name or '?')[:29], len(group)))
for rule, _t in unfixable:
    print("  !! %-20s no input type of this code exists - skipped" % rule.code)

# ---------------------------------------------- 2. what it is worth in money
title("2. what those rules would have paid this month")
carried = defaultdict(lambda: [0.0, 0])
for slip in Payslip.search([('input_line_ids', '!=', False)]):
    if not (slip.date_from and slip.date_from.strftime('%b').upper() == MONTH
            and str(slip.date_from.year) == str(YEAR)):
        continue
    if not (slip.struct_id.name or '').endswith(SUFFIXES):
        continue
    for line in slip.input_line_ids:
        if line.code in by_code:
            carried[line.code][0] += line.amount or 0.0
            carried[line.code][1] += 1
for code, (total, count) in sorted(carried.items()):
    print("  %-22s %s over %s payslip(s)" % (code, num(total), count))
if not carried:
    print("  no August payslip carries an input of these codes")

# --------------------------------------------------------- 3. prove it works
title("3. the fix, applied to a real payslip and then discarded")
samples = Payslip.search([('input_line_ids', '!=', False)]).filtered(
    lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
    and str(s.date_from.year) == str(YEAR)
    and (s.struct_id.name or '').endswith(SUFFIXES)
    and any(line.code in by_code for line in s.input_line_ids))[:PROVE]

proved = 0
if not samples:
    print("  no payslip to test against")
for slip in samples:
    before = {line.code or '?': line.total for line in slip.line_ids}
    inputs = {line.code or '?': line.amount for line in slip.input_line_ids}
    print("\n  %s   -   %s" % (slip.employee_id.name or '?',
                               slip.struct_id.name or '?'))
    print("      inputs %s" % ", ".join("%s=%s" % (c, round(a, 2))
                                        for c, a in sorted(inputs.items())))
    print("      NET before %s" % num(before.get('NET')))
    try:
        with env.cr.savepoint():
            for rule, target in broken:
                rule.condition_other_input_id = target.id
            slip.compute_sheet()
            after = {line.code or '?': line.total for line in slip.line_ids}
            appeared = sorted(set(after) - set(before))
            print("      NET after  %s   moved %s"
                  % (num(after.get('NET')),
                     num((after.get('NET') or 0) - (before.get('NET') or 0))))
            landed = [c for c in appeared if c in inputs]
            for code in appeared:
                print("        + %-20s %s%s"
                      % (code, num(after[code]),
                         "   <-- the input landed" if code in inputs else ""))
            if landed:
                proved += 1
            else:
                print("        no input produced a line - the fix is not enough")
            raise RuntimeError('discard')
    except RuntimeError as error:
        if str(error) != 'discard':
            raise
    except Exception as error:  # noqa: BLE001
        print("      compute_sheet raised: %s"
              % str(error).strip().splitlines()[0])

title("summary")
print("  %s rule(s) would be repaired across %s structure(s)"
      % (len(broken), len(structures)))
print("  %s of %s test payslip(s) gained an input line under the fix"
      % (proved, len(samples)))

if not APPLY:
    env.cr.rollback()
    print("\n  report only - nothing written. Re-run with SSC_APPLY=1.")
elif not broken:
    env.cr.rollback()
    print("\n  nothing to repair")
else:
    if not proved:
        env.cr.rollback()
        print("\n  REFUSING TO WRITE: the fix did not make a single input land"
              "\n  on a real payslip. Writing it would change fifty rules and"
              "\n  fix nothing, and the next report would say it had worked.")
    else:
        fixed = 0
        for rule, target in broken:
            rule.condition_other_input_id = target.id
            fixed += 1
        env.cr.commit()
        print("\n  %s rule(s) repaired" % fixed)
        print("  Recompute the August payslips - Compute Sheet on the selection"
              "\n  - and the inputs will land. Then re-run reconcile_payrolls.py.")
