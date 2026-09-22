"""Call the condition and the amount directly, on a real payslip's localdict.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_rule_evaluation.py

Everything checks out and the money still does not move, so the theorising ends
here. localdict['inputs'] is built as

    {line.code: line for line in self.input_line_ids if line.code}

- keyed by code, every line, no filtering by structure. The rules test for
exactly the codes the payslips carry: SALARY_DEDUCTIONS tests for
SALARY_DEDUCTIONS, ADVREC for ADVREC, OTHER_EARNINGS for OTHER_EARNINGS. So the
condition passes and the rule runs.

Which means the earlier conclusion was wrong in its method, not its data. That
probe reported set(after) - set(before) and codes whose total moved. A line
that already existed with a total of zero, and stayed zero, appears in neither.
"No line" may have been "a line of zero" the whole time, and those are
different faults with different fixes.

So this stops inferring from what changed and asks the rule itself:

    localdict = slip._get_localdict()
    rule._satisfy_condition(localdict)     -> did the condition pass?
    rule._compute_rule(localdict)          -> what amount, quantity, rate?

and prints every line on the payslip including the zeros, which is what should
have been printed two rounds ago.

Read-only.
"""
import os

WIDTH = 112
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
CODES = [c.strip() for c in (os.environ.get('SSC_CODES') or
         'SALARY_DEDUCTIONS,ADVREC,OTHER_EARNINGS,REIMBURSEMENT').split(',')
         if c.strip()]
SAMPLE = int(os.environ.get('SSC_SAMPLE') or 3)

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


Payslip = env['hr.payslip'].sudo()
Rule = env['hr.salary.rule'].sudo()

candidates = Payslip.search([('input_line_ids', '!=', False)]).filtered(
    lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
    and str(s.date_from.year) == str(YEAR)
    and (s.struct_id.name or '').endswith(('Labour Pay', 'Staff Pay'))
    and any(line.code in CODES for line in s.input_line_ids))[:SAMPLE]

if not candidates:
    print("no August payslip carries any of %s" % CODES)
    raise SystemExit

for slip in candidates:
    title("%s   -   %s" % (slip.employee_id.name or '?',
                           slip.struct_id.name or '?'))

    # ---------------------------------------------- every line, zeros included
    print("  every line currently on the payslip, zeros included:")
    for line in slip.line_ids.sorted(lambda l: l.sequence):
        mark = "  <-- an input code" if line.code in CODES else ""
        print("      seq %-6s %-22s %12.2f%s"
              % (line.sequence, line.code or '?', line.total, mark))
    present = {line.code for line in slip.line_ids}
    for code in CODES:
        if code in present:
            continue
        if any(l.code == code for l in slip.input_line_ids):
            print("      %-22s NO LINE AT ALL, though the input is present" % code)

    print("\n  inputs on the payslip:")
    for line in slip.input_line_ids:
        print("      %-22s %12.2f   type [%s] %s"
              % (line.code or '?', line.amount or 0.0,
                 line.input_type_id.id, line.input_type_id.name or '?'))

    # ------------------------------------------------ ask the rule directly
    localdict = slip._get_localdict()
    print("\n  localdict['inputs'] keys: %s" % sorted(localdict['inputs']))

    rules = Rule.search([('struct_id', '=', slip.struct_id.id),
                         ('code', 'in', CODES), ('active', '=', True)])
    print("\n  asking each rule, on this payslip's own localdict:")
    for rule in rules.sorted(lambda r: r.sequence):
        print("\n      [%s] %-20s seq %-6s condition_select=%s amount_select=%s"
              % (rule.id, rule.code or '?', rule.sequence,
                 rule.condition_select, rule.amount_select))
        try:
            passed = rule._satisfy_condition(dict(localdict))
            print("          _satisfy_condition -> %s" % passed)
        except Exception as error:  # noqa: BLE001
            print("          _satisfy_condition RAISED %s: %s"
                  % (type(error).__name__, str(error).strip().splitlines()[0]))
            continue
        if not passed:
            condition = rule.condition_other_input_id \
                if 'condition_other_input_id' in rule._fields else None
            print("          it tested for %r against keys %s"
                  % (condition.code if condition else None,
                     sorted(localdict['inputs'])))
            continue
        try:
            amount, quantity, rate = rule._compute_rule(dict(localdict))
            print("          _compute_rule      -> amount %.2f  qty %.2f  rate %.2f"
                  % (amount, quantity, rate))
            print("          the line would be    %.2f" % (amount * quantity * rate / 100.0))
        except Exception as error:  # noqa: BLE001
            print("          _compute_rule RAISED %s: %s"
                  % (type(error).__name__, str(error).strip().splitlines()[0]))

    # Whether the rule is even in the structure's computed sequence.
    all_rules = slip.struct_id.rule_ids
    print("\n  the structure holds %s rule(s); %s of the codes above are among them"
          % (len(all_rules),
             len([r for r in rules if r in all_rules])))
    missing = [r.code for r in rules if r not in all_rules]
    if missing:
        print("      !! %s carry the right struct_id but are not in rule_ids"
              % ", ".join(missing))

env.cr.rollback()
title("read only - nothing was written")
