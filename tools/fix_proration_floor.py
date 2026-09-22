"""Stop paying the weekly rest days to somebody who worked none of the month.

    cd ~/src/user

    # report, and prove it on two real employees without keeping it:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/fix_proration_floor.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/fix_proration_floor.py

Every leaver's payslip paid the same 3/31 of their wage - Mandeep Singh Raj
Singh 1,000 x 3/31 = 96.77 - and Kamlesh, Parfait and Ahmad Ali Sameu showed
exactly 3.00 days before their overtime lines were rebuilt. The live rule says
why:

    scheduled = payslip._get_l10n_ae_total_work_hours() / hours_per_day
    covered   = sum(l.number_of_days for l in payslip.worked_days_line_ids
                    if not (l.work_entry_type_id.code or '').startswith('SSC_OT'))
    absent    = max(0.0, scheduled - covered)
    ratio     = (period_days - absent) / days_in_month

1..25 August is 25 calendar days holding 22 scheduled days and 3 Fridays. Work
nothing and covered is 0, so absent is 22, and the numerator is 25 - 22 = 3.

The numerator counts CALENDAR days while absent counts SCHEDULED days, so the
weekly rest always survives the subtraction. That is right for somebody who
worked the days around it - rest is paid - and wrong for somebody who worked
none of them, who is paid for resting from nothing.

THE FIX, AND ITS BLAST RADIUS

    if covered <= 0 and scheduled > 0:
        ratio = 0.0

  Only the all-or-nothing case moves. Work twenty of twenty two days and absent
  is 2, the ratio is 23/31, and the Fridays are still paid exactly as before.
  Paid Time Off counts toward covered - the filter excludes only SSC_OT codes -
  so somebody on approved leave is untouched.

  Applied to BASIC, HOUALLOW, TRAALLOW and OTALLOW in every Labour and Staff
  structure, since all four share the same prelude.

IT IS PROVED BOTH WAYS BEFORE IT IS KEPT

  In report mode the rules are patched inside a savepoint and two payslips are
  computed and discarded: one for an employee with no work entries, which must
  fall to zero, and one for an employee with a full month, which must not move
  at all. A fix that only demonstrates the case it was written for is half
  tested, and the half it skips is the one with everybody in it.

Reads only unless SSC_APPLY=1.
"""
import os

WIDTH = 112
APPLY = os.environ.get('SSC_APPLY') == '1'
FROM = os.environ.get('SSC_FROM') or '2026-08-01'
TO = os.environ.get('SSC_TO') or '2026-08-25'
CODES = ('BASIC', 'HOUALLOW', 'TRAALLOW', 'OTALLOW')
SUFFIXES = ('Labour Pay', 'Staff Pay')

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

NL = chr(10)
MARKER = "ratio = (period_days - absent) / days_in_month if days_in_month else 0.0"
GUARD = (NL
         + "# Nothing covered at all: the weekly rest days are not earned either." + NL
         + "# The numerator counts calendar days while absent counts scheduled" + NL
         + "# ones, so without this the off days survive for somebody who worked" + NL
         + "# none of the month - 25 - 22 = 3 days of Fridays, paid for nothing." + NL
         + "if covered <= 0 and scheduled > 0:" + NL
         + "    ratio = 0.0")


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


Rule = env['hr.salary.rule'].sudo()
Structure = env['hr.payroll.structure'].sudo()
Payslip = env['hr.payslip'].sudo()
Employee = env['hr.employee'].sudo()
WorkEntry = env['hr.work.entry'].sudo()

structures = Structure.search([]).filtered(
    lambda s: (s.name or '').endswith(SUFFIXES))

# ------------------------------------------------------------ 1. the rules
title("1. rules carrying the proration prelude")
targets, already, missing = [], [], []
for structure in structures:
    for rule in Rule.search([('struct_id', '=', structure.id),
                             ('active', '=', True), ('code', 'in', CODES)]):
        body = rule.amount_python_compute or ''
        if "if covered <= 0" in body:
            already.append(rule)
        elif MARKER in body:
            targets.append(rule)
        else:
            missing.append(rule)

print("  %s rule(s) would be patched" % len(targets))
print("  %s already carry the guard" % len(already))
if missing:
    print("  !! %s do not contain the expected line and are left alone:"
          % len(missing))
    for rule in missing[:10]:
        print("      %-12s %s" % (rule.code, rule.struct_id.name or '?'))

by_structure = {}
for rule in targets:
    by_structure.setdefault(rule.struct_id.name or '?', []).append(rule.code)
for name, codes in sorted(by_structure.items()):
    print("      %-46s %s" % (name[:46], ", ".join(sorted(codes))))

# ------------------------------------------- 2. two employees, opposite cases
title("2. the two cases this has to get right")


def pick(with_entries):
    for employee in Employee.search([('company_id', '!=', False)]):
        version = employee.sudo().version_id
        if not version.contract_date_start or not version.structure_type_id:
            continue
        if version.contract_date_end and str(version.contract_date_end) < TO:
            continue
        structure = next((s for s in structures
                          if s.type_id == version.structure_type_id), None)
        if not structure or not version.wage:
            continue
        live = WorkEntry.search_count([
            ('employee_id', '=', employee.id), ('date', '>=', FROM),
            ('date', '<=', TO), ('state', '!=', 'cancelled')])
        if bool(live) == with_entries:
            return employee, version, structure
    return None


worked = pick(True)
idle = pick(False)
for label, chosen in (("worked the month", worked), ("no work entry", idle)):
    if chosen:
        print("  %-18s %-40s wage %s"
              % (label, (chosen[0].name or '?')[:40], chosen[1].wage))
    else:
        print("  %-18s none found" % label)


def ratio_of(employee, version, structure):
    slip = Payslip.create({
        'employee_id': employee.id, 'date_from': FROM, 'date_to': TO,
        'struct_id': structure.id, 'name': 'proration probe'})
    slip.with_context(active_test=True).compute_sheet()
    basic = sum(l.total for l in slip.line_ids if l.code == 'BASIC')
    return basic, (basic / version.wage) if version.wage else 0.0


title("3. patched inside a savepoint, both computed, then discarded")
proved_zero = proved_stable = None
try:
    with env.cr.savepoint():
        before = {}
        for label, chosen in (("idle", idle), ("worked", worked)):
            if chosen:
                before[label] = ratio_of(*chosen)
        for rule in targets:
            rule.amount_python_compute = (
                rule.amount_python_compute or '').replace(
                    MARKER, MARKER + GUARD, 1)
        after = {}
        for label, chosen in (("idle", idle), ("worked", worked)):
            if chosen:
                after[label] = ratio_of(*chosen)

        for label in ('idle', 'worked'):
            if label not in before:
                continue
            b_amount, b_ratio = before[label]
            a_amount, a_ratio = after[label]
            print("  %-8s BASIC %10.2f -> %10.2f   ratio %.6f -> %.6f  (%.2f -> %.2f days of 31)"
                  % (label, b_amount, a_amount, b_ratio, a_ratio,
                     b_ratio * 31, a_ratio * 31))
        if 'idle' in after:
            proved_zero = abs(after['idle'][0]) < 0.005
        if 'worked' in after:
            proved_stable = abs(after['worked'][0] - before['worked'][0]) < 0.005
        raise RuntimeError('discard')
except RuntimeError as error:
    if str(error) != 'discard':
        raise
except Exception as error:  # noqa: BLE001
    print("  the test could not run: %s: %s"
          % (type(error).__name__, str(error).strip().splitlines()[0]))

title("summary")
print("  idle employee falls to zero      %s" % proved_zero)
print("  working employee does not move   %s" % proved_stable)
print("  %s rule(s) to patch" % len(targets))

if not APPLY:
    env.cr.rollback()
    print("")
    print("  report only - nothing written. Re-run with SSC_APPLY=1.")
elif not targets:
    env.cr.rollback()
    print("")
    print("  nothing to patch")
elif not (proved_zero and proved_stable):
    env.cr.rollback()
    print("")
    print("  REFUSING TO WRITE. The change has to do both things: send the idle")
    print("  employee to zero AND leave the working one exactly where he was.")
    print("  One of those did not hold, so patching every structure now would")
    print("  move money for people who worked.")
else:
    patched = 0
    for rule in targets:
        rule.amount_python_compute = (
            rule.amount_python_compute or '').replace(MARKER, MARKER + GUARD, 1)
        patched += 1
    env.cr.commit()
    title("done")
    print("  %s rule(s) patched across %s structure(s)"
          % (patched, len(by_structure)))
    print("")
    print("  Recompute the draft payslips - tools/recompute_payslips.py - and")
    print("  anybody who worked nothing drops to zero instead of three days.")
