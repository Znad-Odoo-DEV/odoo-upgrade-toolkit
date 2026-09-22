"""What it would take to pay ssc.attachment through Salary Inputs instead.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/probe_attachments_to_inputs.py

ssc_payroll settles everything that is not the base salary through
ssc.attachment: overtime for last month, the sick-leave payback, the phone
bill, advances, fines, loans, leave expenses. Native payroll has its own place
for exactly that - hr.payslip.input, typed by hr.payslip.input.type and read by
a salary rule.

Moving one to the other is a mapping problem before it is a code problem, and
the mapping cannot be designed against a guess. So this reports, from the
database:

  * every hr.payslip.input.type that exists, and which structures can use it;
  * every salary rule that reads an input, and the codes it reads - the rules
    are what turn an input into money, and an input type nothing reads is a box
    that does nothing;
  * every ssc.attachment.type, how many attachments carry it, what they are
    worth, and what state they are in - a type with nothing on it needs no
    destination, and a type with paid history needs one that does not disturb
    it;
  * the attachment types created on the fly by the Studio bridge, which are the
    ones nobody designed and nobody will remember.

Read-only. Nothing here writes.

WHAT TO DECIDE FROM IT

Whether an existing input type can carry each attachment type, or whether a new
one is needed. The instruction is no new input types unless there is no other
way, so the report is ordered to make the reuse obvious: input types first,
then what each attachment type would have to fit into.
"""
from collections import defaultdict

WIDTH = 100

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def money(value):
    return "{:>12,.2f}".format(value or 0.0)


# ---------------------------------------------------------------- input types
title("1. input types that already exist")

InputType = env.get('hr.payslip.input.type')
if InputType is None:
    print("  hr_payroll is not installed")
    input_types = []
else:
    input_types = InputType.sudo().search([], order='code, name')
    if not input_types:
        print("  (none)")
    # Availability is not decoration: an input type restricted to structures
    # an employee is not on cannot carry their money, so the list is printed
    # whole and the SSC ones are counted rather than truncated.
    ssc_structures = env['hr.payroll.structure'].sudo().search([])
    ssc_names = {s.name for s in ssc_structures
                 if (s.name or '').endswith(('Labour Pay', 'Staff Pay'))}
    for input_type in input_types:
        structures = input_type.struct_ids
        if not structures:
            where = "ALL structures"
        else:
            names = {s.name for s in structures}
            covered = len(ssc_names & names)
            where = "%s structure(s), %s of the %s SSC ones" % (
                len(names), covered, len(ssc_names))
            if covered < len(ssc_names):
                where += "   <-- NOT on every SSC structure"
        print("  %-22s %-30s %s" % (input_type.code or '-',
                                    (input_type.name or '')[:30], where))

# ------------------------------------------------------------ rules that read
title("2. salary rules that turn an input into money")

Rule = env.get('hr.salary.rule')
readers = defaultdict(set)
if Rule is not None:
    for rule in Rule.sudo().search([]):
        body = rule.amount_python_compute or ''
        codes = set()
        if rule.amount_select == 'input':
            # The rule pays whatever its own code names.
            codes.add(rule.code)
        for input_type in input_types:
            code = input_type.code or ''
            if code and ("inputs['%s'" % code in body
                         or 'inputs["%s"' % code in body
                         or "inputs.get('%s'" % code in body):
                codes.add(code)
        for code in codes:
            readers[code].add((rule.code, rule.struct_id.name or '?'))

if not readers:
    print("  (no rule reads any input)")
for code in sorted(readers):
    rules = sorted(readers[code])
    print("  %-22s read by %s rule(s): %s" % (
        code, len(rules),
        ", ".join(sorted({name for name, _s in rules}))))

orphan_types = [t for t in input_types if (t.code or '') not in readers]
if orphan_types:
    print("\n  input types NOTHING reads - a box that does nothing:")
    for input_type in orphan_types:
        print("    %-22s %s" % (input_type.code or '-', input_type.name or ''))

# -------------------------------------------------------- what has to move
title("3. what ssc.attachment actually holds")

Attachment = env.get('ssc.attachment')
if Attachment is None:
    print("  ssc_payroll is not installed")
else:
    rows = []
    for att_type in env['ssc.attachment.type'].sudo().search([]):
        found = Attachment.sudo().search([('type_id', '=', att_type.id)])
        if not found:
            rows.append((att_type, 0, 0.0, {}, False))
            continue
        by_state = defaultdict(int)
        for att in found:
            by_state[att.state] += 1
        from_studio = any(att.studio_ref_id for att in found)
        rows.append((att_type, len(found), sum(found.mapped('signed_value')),
                     dict(by_state), from_studio))

    print("  %-34s %-10s %6s %13s  %s"
          % ("type", "kind", "count", "signed total", "states"))
    print("  " + "-" * (WIDTH - 4))
    for att_type, count, total, by_state, from_studio in sorted(
            rows, key=lambda r: (-r[1], r[0].name or '')):
        states = ", ".join("%s=%s" % (k, v) for k, v in sorted(by_state.items()))
        note = "  <-- made by the Studio bridge" if from_studio else ""
        print("  %-34s %-10s %6s %13s  %s%s"
              % ((att_type.name or '?')[:34], att_type.kind, count,
                 money(total), states or "-", note))

    unpaid = Attachment.sudo().search_count([('state', '!=', 'paid')])
    print("\n  %s attachment(s) are not paid - those are the ones a move has to "
          "carry. Anything paid is history and should stay where it is."
          % unpaid)

# ------------------------------------------------- how the rules read the sign
title("4. which way each destination rule points")
print("""  hr.payslip.input.amount is a positive number; the RULE decides whether
  it adds or subtracts. Put a negative amount into a rule that already negates
  and the deduction pays out instead. So the bodies, verbatim.
""")

TARGETS = ('OTHER_EARNINGS', 'SALARY_DEDUCTIONS', 'ADVREC', 'OTHER_DEDUCTIONS',
           'BONUS', 'AIRFARE_ALLOWANCE', 'REIMBURSEMENT', 'DEDUCTION')
if Rule is not None:
    for code in TARGETS:
        rule = Rule.sudo().search(
            [('code', '=', code), ('active', '=', True)],
            order='struct_id', limit=1)
        if not rule:
            print("  %-20s (no active rule)" % code)
            continue
        print("  %-20s category=%-10s amount=%s"
              % (code, rule.category_id.code or '?', rule.amount_select))
        body = (rule.amount_python_compute or '').strip()
        if rule.amount_select != 'code':
            print("      (pays inputs['%s'].amount as it stands)" % code)
        for line in (body.splitlines() or ['(empty)'])[:12]:
            print("      " + line)
        print()

# ------------------------------------------------------------------ the sums
title("5. the shape of the question")
print("""  For each attachment type above, one of three answers:

    reuse    an input type already exists and a rule already pays it
    rename   an input type exists but nothing reads it - it needs a rule
    new      neither exists, and only then is a new input type justified

  Read section 2 before section 1: an input type with no rule behind it moves
  no money, so 'it already exists' is only half an answer.

  Read-only run. Nothing was changed.""")
