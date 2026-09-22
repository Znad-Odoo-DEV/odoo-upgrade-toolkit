"""Stop the native payroll paying annual leave salary, because ssc does not.

    cd ~/src/user

    # report, and prove the effect without keeping it:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/stop_leave_salary_rule.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/stop_leave_salary_rule.py

LEAVESAL is 10,306.67 across three August payslips and the whole of those three
employees' gaps. ssc_payroll pays none of it - not because it forgets leave,
but because leave settlement is its own document there, ssc.leave.expense, and
not a payslip line. Native adding LEAVESAL on top pays the same entitlement
through a second channel.

ssc is the side that has actually paid the company's wages, so the rule stops.
Archiving is the way to stop it: active=False leaves the rule, its formula and
its history in place and reversible in one click, where deleting it would take
the audit trail with it and rewriting its condition would leave something that
looks live and is not.

BEFORE ARCHIVING, WHAT ELSE READS IT

  A rule other rules depend on cannot just be switched off. GROSS or NET may
  reference rules['LEAVESAL'] directly, and a python that reads a rule which no
  longer computes raises rather than returning zero. So every rule in these
  structures whose python names LEAVESAL is printed first, and the tool refuses
  to write if any of them would be left referring to a rule that is gone.

THE CONTEXT THIS RUNS IN

  This script reads with active_test=False so it can find archived rules at
  all. Computing a payslip under that same context lets the payslip see them
  too, so an archived rule keeps producing its line and archiving looks like
  it did nothing. The proof below computes with active_test=True, the way the
  server does when anybody presses Compute Sheet.

IT PROVES ITSELF FIRST

  In report mode the rules are archived inside a savepoint, the affected
  payslips are recomputed, the net is printed before against after, and it is
  all rolled back. The expected drop is exactly the LEAVESAL line; anything
  else moving means something depended on it after all.

Reads only unless SSC_APPLY=1.
"""
import os

WIDTH = 112
APPLY = os.environ.get('SSC_APPLY') == '1'
CODE = os.environ.get('SSC_RULE') or 'LEAVESAL'
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
SUFFIXES = ('Labour Pay', 'Staff Pay')

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value):
    return "{:>12,.2f}".format(value or 0.0)


Rule = env['hr.salary.rule'].sudo()
Payslip = env['hr.payslip'].sudo()
Structure = env['hr.payroll.structure'].sudo()

structures = Structure.search([]).filtered(
    lambda s: (s.name or '').endswith(SUFFIXES))

# ------------------------------------------------------------- 1. the rules
title("1. the %s rule in each structure" % CODE)
targets = Rule.search([('code', '=', CODE), ('active', '=', True)]).filtered(
    lambda r: r.struct_id in structures)
print("  %s active rule(s) across %s structure(s)"
      % (len(targets), len(structures)))
for rule in targets:
    print("      [%s] seq %-6s %-30s %s"
          % (rule.id, rule.sequence, (rule.name or '?')[:30],
             rule.struct_id.name or '?'))
if not targets:
    print("      nothing to stop")

# ------------------------------------------------ 2. what else depends on it
title("2. rules whose python names %s" % CODE)
dependants = []
for structure in structures:
    for rule in Rule.search([('struct_id', '=', structure.id),
                             ('active', '=', True)]):
        if rule in targets:
            continue
        text = ""
        for field in ('amount_python_compute', 'condition_python',
                      'amount_percentage_base', 'quantity'):
            value = rule[field] if field in rule._fields else None
            if isinstance(value, str):
                text += " " + value
        if CODE in text:
            dependants.append(rule)
if not dependants:
    print("  none - no rule reads %s by name, so switching it off is safe" % CODE)
seen = set()
for rule in dependants:
    key = (rule.code, rule.amount_python_compute, rule.condition_python)
    if key in seen:
        continue
    seen.add(key)
    print("\n  !! [%s] %-16s in %s" % (rule.id, rule.code or '?',
                                       rule.struct_id.name or '?'))
    for field in ('condition_python', 'amount_python_compute'):
        value = rule[field] if field in rule._fields else None
        if value and CODE in str(value):
            for line in str(value).splitlines():
                if CODE in line:
                    print("        %s" % line.strip())

# ------------------------------------------------------- 3. what it is worth
title("3. the payslips carrying a %s line in %s-%s" % (CODE, MONTH, YEAR))
affected = []
for slip in Payslip.search([]):
    if not (slip.date_from and slip.date_from.strftime('%b').upper() == MONTH
            and str(slip.date_from.year) == str(YEAR)):
        continue
    if not (slip.struct_id.name or '').endswith(SUFFIXES):
        continue
    line = slip.line_ids.filtered(lambda l: l.code == CODE and l.total)
    if line:
        affected.append((slip, sum(line.mapped('total'))))
total = sum(value for _s, value in affected)
print("  %s payslip(s), %s in total" % (len(affected), num(total)))
for slip, value in sorted(affected, key=lambda r: -abs(r[1])):
    print("      %-40s %s   state=%s"
          % ((slip.employee_id.name or '?')[:40], num(value), slip.state))

# ------------------------------------------------------------ 4. prove it
title("4. archived inside a savepoint, recomputed, then discarded")
proved, surprises = 0, []
if not affected:
    print("  no payslip to test against")
for slip, value in affected:
    before = {l.code or '?': l.total for l in slip.line_ids}
    try:
        with env.cr.savepoint():
            targets.write({'active': False})
            # This script's env sets active_test=False so it can see archived
            # rules at all. Computing under that context lets the payslip see
            # them too, so an archived rule keeps producing its line and
            # archiving looks like it did nothing - which is exactly what the
            # first run reported. Compute the way the server does.
            slip.with_context(active_test=True).compute_sheet()
            after = {l.code or '?': l.total for l in slip.line_ids}
            moved = (after.get('NET') or 0) - (before.get('NET') or 0)
            print("\n  %-40s NET %s -> %s   moved %s"
                  % ((slip.employee_id.name or '?')[:40],
                     num(before.get('NET')), num(after.get('NET')), num(moved)))
            if abs(moved + value) > 0.05:
                surprises.append((slip.employee_id.name or '?', value, moved))
                print("      !! expected the net to fall by %s" % num(value))
            else:
                proved += 1
            for code in sorted(set(before) | set(after)):
                b, a = before.get(code, 0.0), after.get(code, 0.0)
                if abs((a or 0) - (b or 0)) > 0.005:
                    print("      %-18s %s -> %s" % (code, num(b), num(a)))
            raise RuntimeError('discard')
    except RuntimeError as error:
        if str(error) != 'discard':
            raise
    except Exception as error:  # noqa: BLE001
        print("      compute_sheet raised: %s"
              % str(error).strip().splitlines()[0])
        surprises.append((slip.employee_id.name or '?', value, None))

title("summary")
print("  %s rule(s) would be archived" % len(targets))
print("  %s payslip(s) affected, %s of leave salary" % (len(affected), num(total)))
print("  %s of %s behaved exactly as expected" % (proved, len(affected)))
if dependants:
    print("  !! %s rule(s) read %s by name" % (len(dependants), CODE))
if surprises:
    print("  !! %s payslip(s) did something other than lose the leave line:"
          % len(surprises))
    for name, value, moved in surprises:
        print("      %-40s expected %s, moved %s"
              % (name[:40], num(-value), num(moved) if moved is not None else 'error'))

if not APPLY:
    env.cr.rollback()
    print("")
    print("  report only - nothing written. Re-run with SSC_APPLY=1.")
elif not targets:
    env.cr.rollback()
    print("")
    print("  nothing to archive")
elif dependants or surprises:
    env.cr.rollback()
    print("")
    print("  REFUSING TO WRITE. Another rule depends on %s, or a payslip moved"
          "\n  by something other than the leave line. Switching it off would"
          "\n  break more than it fixes, and the next report would not say so."
          % CODE)
else:
    targets.write({'active': False})
    recomputed = 0
    for slip, _value in affected:
        if slip.state != 'draft':
            continue
        slip.with_context(active_test=True).compute_sheet()
        recomputed += 1
    env.cr.commit()
    print("")
    print("  %s rule(s) archived, %s draft payslip(s) recomputed"
          % (len(targets), recomputed))
    print("  Leave settlement stays where ssc keeps it - ssc.leave.expense -"
          "\n  and the payslip no longer pays it a second time.")
