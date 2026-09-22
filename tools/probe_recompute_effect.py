"""Recompute a payslip inside a savepoint and see whether the inputs land.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_recompute_effect.py

    SSC_EMPLOYEE="Mohamed Salah" ...      # one person
    SSC_SAMPLE=6 ...                      # how many to try

Every input written this month is inert - not one produced a line. The rules
looked like the culprit and they are not. probe_input_rules.py showed them
active, and byte for byte identical to Odoo's own UAE originals they were
copied from. REIMBURSEMENT is the clearest case: rule 407, active, condition
   result = 'REIMBURSEMENT' in inputs
which is exactly the test that should pass, on five payslips that carry the
input, producing nothing.

An active rule with a correct condition and a present input that yields no line
leaves one explanation worth testing before any other: the payslip has not been
recomputed since the inputs were written. A payslip holds the lines from its
last computation, not the lines its current inputs imply. The inputs went in at
12:20 and the comparison ran at 12:32, so this costs one command to rule in or
out and would otherwise send the next hour into rewriting rules that are fine.

WHAT IT DOES

  Takes payslips that carry an input, records their lines and net, calls
  compute_sheet() inside a savepoint, records them again, prints the
  difference, and rolls back. Nothing is kept - the point is to find out
  whether recomputing is the fix, not to apply it.

  A payslip that gains its input lines here proves the data is right and only
  the computation is stale. One that does not, with the input still on it, puts
  the rules back under suspicion with the cheap explanation eliminated.

Read-only: every change is rolled back, including on the way out.
"""
import os
from collections import defaultdict

WIDTH = 112
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
SAMPLE = int(os.environ.get('SSC_SAMPLE') or 6)
WANTED = (os.environ.get('SSC_EMPLOYEE') or '').strip().lower()

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value):
    return "{:>12,.2f}".format(value or 0.0)


Payslip = env['hr.payslip'].sudo()

candidates = Payslip.search([('input_line_ids', '!=', False)]).filtered(
    lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
    and str(s.date_from.year) == str(YEAR)
    and (s.struct_id.name or '').endswith(('Labour Pay', 'Staff Pay')))

if WANTED:
    candidates = candidates.filtered(
        lambda s: WANTED in (s.employee_id.name or '').lower())

title("payslips carrying an input in %s-%s" % (MONTH, YEAR))
print("  %s found" % len(candidates))
if not candidates:
    print("  nothing to test")
    raise SystemExit

# Take a spread rather than the first few, so one odd structure cannot stand
# for all of them.
by_structure = defaultdict(list)
for slip in candidates:
    by_structure[slip.struct_id].append(slip)
chosen = []
for structure, slips in by_structure.items():
    chosen.extend(slips[:max(1, SAMPLE // max(1, len(by_structure)))])
chosen = chosen[:SAMPLE] or list(candidates[:SAMPLE])

print("  testing %s of them, across %s structure(s)"
      % (len(chosen), len(by_structure)))

gained_any = 0
for slip in chosen:
    title("%s   -   %s" % (slip.employee_id.name or '?',
                           slip.struct_id.name or '?'), '-')
    inputs = {line.code or '?': line.amount or 0.0 for line in slip.input_line_ids}
    print("    inputs on the payslip:")
    for code, amount in sorted(inputs.items()):
        print("        %-22s %s" % (code, num(amount)))

    before = {line.code or '?': line.total for line in slip.line_ids}
    print("    state=%s   lines before %s   NET before %s"
          % (slip.state, len(before), num(before.get('NET'))))

    try:
        with env.cr.savepoint():
            slip.compute_sheet()
            after = {line.code or '?': line.total for line in slip.line_ids}
            appeared = sorted(set(after) - set(before))
            changed = sorted(code for code in set(after) & set(before)
                             if abs((after[code] or 0) - (before[code] or 0)) > 0.005)
            print("    lines after  %s   NET after  %s   (%s)"
                  % (len(after), num(after.get('NET')),
                     "NET moved by %s" % num((after.get('NET') or 0)
                                             - (before.get('NET') or 0))))
            if appeared:
                print("    NEW line(s):")
                for code in appeared:
                    print("        %-22s %s%s"
                          % (code, num(after[code]),
                             "   <-- this is an input landing"
                             if code in inputs else ""))
            if changed:
                print("    changed line(s):")
                for code in changed:
                    print("        %-22s %s -> %s"
                          % (code, num(before[code]), num(after[code])))
            if not appeared and not changed:
                print("    nothing changed - the payslip was already current,"
                      " so the rules are the problem")
            if any(code in inputs for code in appeared):
                gained_any += 1
            # Roll the savepoint back by raising out of it.
            raise RuntimeError('rollback')
    except RuntimeError as error:
        if str(error) != 'rollback':
            raise
    except Exception as error:  # noqa: BLE001
        print("    compute_sheet raised: %s" % str(error).strip().splitlines()[0])

title("verdict")
if gained_any:
    print("  %s of %s payslip(s) gained a line for an input they already carried."
          % (gained_any, len(chosen)))
    print("""
  The data is right and the computation is stale. Recompute the August payslips
  - Compute Sheet on the selection, or Recompute Whole Sheet where the contract
  dates changed - and the adjustments will land. No rule needs editing.""")
else:
    print("""  No payslip gained an input line. The cheap explanation is
  eliminated: these payslips are current, and the rules that read the inputs do
  not fire on them. That is where to look next - condition_select='input' and
  what Odoo requires of it, since the deduction rules carry no
  amount_other_input_id at all.""")

env.cr.rollback()
title("read only - the transaction was rolled back")
