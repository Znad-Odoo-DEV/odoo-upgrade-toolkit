"""The base salary rules pay the days the attendance sheet counts, on every Labour structure.

    cd ~/src/user
    # report, and prove it on real August payslips inside a savepoint:
    odoo-bin shell -d <database> --no-http < tools/set_ssc_base_rules.py 2>&1 | grep -v " INFO "
    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/set_ssc_base_rules.py 2>&1 | grep -v " INFO "

    SSC_MONTH=AUG SSC_YEAR=2026    the month whose ssc.payslips are the proof
    SSC_PROOF=12                   how many employees to prove on (default 12)
    SSC_SUFFIX="Labour Pay"        which structures (staff have another sheet)

WHAT CHANGES

BASIC, HOUALLOW, TRAALLOW and OTALLOW stop counting days for themselves. They
ask hr.employee._ssc_paid_days(payslip.date_from, payslip.date_to), which runs
the attendance sheet's own engine - the missing check-out, the half day, the
stranded Friday, the holiday penalty, the days after the period paid in
advance - and hands back one ratio: paid days over the days in the month,
capped at one. Each rule multiplies its contract figure by that. The four
lines still add up to what ssc.payslip calls total_salary, to the fils,
because it is the same arithmetic on the same days.

The proration floor, the scheduled-hours divisor and everything else the old
prelude carried go with it: they were the second engine.

THE PROOF, BEFORE ANYTHING IS WRITTEN

The rules are rewritten inside a savepoint, the native payslips of SSC_PROOF
employees who have an ssc.payslip for the month are recomputed, BASIC +
allowances is set against ssc total_salary for each, and the savepoint is
rolled back. The report prints every one. Contract figures that differ between
the ssc snapshot and hr.version are named as such, since no day-counting can
make those agree; everybody else must be exact. With SSC_APPLY=1 the same
proof runs first and the write only happens when it passes.

Reads only unless SSC_APPLY=1. Never touches a Staff structure, the overtime
rules, or a validated payslip.
"""
import os

WIDTH = 120
APPLY = os.environ.get('SSC_APPLY') == '1'
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
PROOF = int(os.environ.get('SSC_PROOF') or 12)
SUFFIX = os.environ.get('SSC_SUFFIX') or 'Labour Pay'
CODES = ('BASIC', 'HOUALLOW', 'TRAALLOW', 'OTALLOW')
MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
          'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US',  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

PRELUDE = """
# One engine. The attendance sheet decides which days are paid - the missing
# check-out, the half day, the stranded Friday, the holiday penalty, the days
# after the period paid in advance - and this rule only prices them. Nothing
# about a day is decided here, so nothing here can drift from the sheet.
#
# ratio = paid days / days in the month, capped at one. The four base rules
# all take the same ratio, and together they are ssc.payslip's total_salary:
# the whole gross when the days reach the month, a thirty-first of it per day
# otherwise.
figures = employee._ssc_paid_days(payslip.date_from, payslip.date_to)
ratio = figures['ratio']
"""
PLAN = {
    'BASIC': PRELUDE + "result = version.wage * ratio\n",
    'HOUALLOW': PRELUDE + "result = version.l10n_ae_housing_allowance * ratio\n",
    'TRAALLOW': PRELUDE + "result = version.l10n_ae_transportation_allowance * ratio\n",
    'OTALLOW': PRELUDE + "result = version.l10n_ae_other_allowances * ratio\n",
}


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value, width=11):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


Rule = env['hr.salary.rule'].sudo()
Structure = env['hr.payroll.structure'].sudo()
Payslip = env['hr.payslip'].sudo()
SscSlip = env['ssc.payslip'].sudo()

if not hasattr(env['hr.employee'], '_ssc_paid_days'):
    print("  !! hr.employee._ssc_paid_days is not on this database - ssc_payroll "
          "1.91.0 has not been deployed. Nothing to do.")
    raise SystemExit

structures = Structure.search([]).filtered(
    lambda s: (s.name or '').endswith(SUFFIX))
title("structures ending in %r" % SUFFIX)
for structure in structures:
    print("  [%s] %s" % (structure.id, structure.name))

# ------------------------------------------------------------ 1. the rules
title("1. the rules, and what they say today")
targets = Rule.search([('struct_id', 'in', structures.ids), ('code', 'in', CODES),
                       ('active', '=', True)])
by_code = {}
for rule in targets:
    by_code.setdefault(rule.code, []).append(rule)
missing = [code for code in CODES if len(by_code.get(code, [])) != len(structures)]
for code in CODES:
    print("  %-10s %s rule(s) across %s structure(s)"
          % (code, len(by_code.get(code, [])), len(structures)))
if missing:
    print("  !! %s is not on every structure - nothing is written" % missing)
    raise SystemExit
already = [r for r in targets if '_ssc_paid_days' in (r.amount_python_compute or '')]
print("  %s already carry the sheet engine, %s would change"
      % (len(already), len(targets) - len(already)))
sample = by_code['BASIC'][0]
print("\n  BASIC on %s today:" % (sample.struct_id.name or '?'))
for line in (sample.amount_python_compute or '').strip().splitlines()[:14]:
    print("      %s" % line[:110])

# ------------------------------------------------------------- 2. the proof
title("2. the proof: native BASIC+allowances against ssc total_salary, %s-%s" % (MONTH, YEAR))
month_index = MONTHS.index(MONTH) + 1
pairs = []
for ssc in SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR)),
                           ('is_staff', '=', False)]):
    employee = ssc.employee_id
    if employee._name != 'hr.employee':
        continue
    native = Payslip.search([('employee_id', '=', employee.id), ('state', '=', 'draft'),
                             ('struct_id', 'in', structures.ids)]).filtered(
        lambda s: s.date_from and s.date_from.month == month_index
        and s.date_from.year == int(YEAR))
    if native:
        pairs.append((employee, ssc, native[0]))
print("  %s employee(s) hold both an ssc.payslip and a draft native payslip" % len(pairs))
if not pairs:
    print("  nothing to prove on - the write is refused")
    raise SystemExit

# The widest spread of days, so the proof is not twelve full months.
pairs.sort(key=lambda p: p[1].total_attendance or 0.0)
step = max(1, len(pairs) // PROOF)
chosen = pairs[::step][:PROOF]


def base_of(slip):
    return sum(line.total for line in slip.line_ids if line.code in CODES)


exact, rounding, contract, wrong = [], [], [], []
# ssc.payslip rounds rate_per_day to the fils - it is a Monetary field - and
# multiplies the rounded rate by the days: 1,500 / 31 = 48.387 becomes 48.39,
# times 24 days is 1,161.36. The rule multiplies the exact fraction and gets
# 1,161.29. Up to half a fils per day, so up to 0.16 on a full month: a
# rounding artefact on the ssc side, not a disagreement about a day.
ROUNDING = 0.20


class _Proved(Exception):
    """Raised at the end of the proof so the savepoint rolls itself back."""


try:
    with env.cr.savepoint():
        for rule in targets:
            rule.write({'amount_python_compute': PLAN[rule.code]})
        print("\n  %-36s %7s %7s %12s %12s %10s   %s"
              % ("employee", "ssc d", "eng d", "ssc salary", "native", "gap", "note"))
        print("  " + "-" * (WIDTH - 4))
        for employee, ssc, native in chosen:
            native.with_context(active_test=True).compute_sheet()
            figures = employee._ssc_paid_days(native.date_from, native.date_to)
            got = base_of(native)
            gap = (ssc.total_salary or 0.0) - got
            version = native.version_id
            native_gross = (version.wage + version.l10n_ae_housing_allowance
                            + version.l10n_ae_transportation_allowance
                            + version.l10n_ae_other_allowances)
            if abs(gap) <= 0.02:
                note, bucket = "exact", exact
            elif (abs(gap) <= ROUNDING
                  and abs(figures['total_days'] - (ssc.total_attendance or 0.0)) < 0.005):
                note = "rounding - ssc rounds the day rate to the fils first"
                bucket = rounding
            elif abs((ssc.gross_salary or 0.0) - native_gross) > 0.02:
                note = ("contract: ssc gross %s, hr.version %s"
                        % (num(ssc.gross_salary, 1), num(native_gross, 1)))
                bucket = contract
            else:
                note, bucket = "!! DIFFERS on the same contract", wrong
            bucket.append(employee)
            print("  %-36s %7.2f %7.2f %12s %12s %10s   %s"
                  % ((employee.name or '?')[:36], ssc.total_attendance or 0.0,
                     figures['total_days'], num(ssc.total_salary), num(got),
                     num(gap, 10), note))
        # Leave through an exception: the savepoint rolls back the rule
        # bodies and the recomputed payslips, and nothing of the proof stays.
        raise _Proved()
except _Proved:
    pass

print("\n  exact %s   rounding %s   contract differs %s   DIFFERS %s"
      % (len(exact), len(rounding), len(contract), len(wrong)))
if wrong:
    print("  !! the engine and ssc.payslip disagree on the same contract for:")
    for employee in wrong:
        print("       %s" % (employee.name or '?'))

# ------------------------------------------------------------------ 3. write
title("3. summary")
if wrong:
    print("  the write is refused while any employee differs on the same contract")
    raise SystemExit
if not APPLY:
    print("  report only - nothing written. Re-run with SSC_APPLY=1.")
    raise SystemExit

targets = Rule.search([('struct_id', 'in', structures.ids), ('code', 'in', CODES),
                       ('active', '=', True)])
for rule in targets:
    rule.write({'amount_python_compute': PLAN[rule.code]})
env.cr.commit()
title("APPLIED")
print("  rewrote %s rule(s) on %s structure(s)" % (len(targets), len(structures)))
print("  Now: SSC_APPLY=1 SSC_SUFFIX=\"Labour Pay\" SSC_COMPANIES=\"SAUD,ROYAL ARROW,"
      "ROYAL WOODEN,MALAK\" ... < tools/recompute_payslips.py, then the audit.")
