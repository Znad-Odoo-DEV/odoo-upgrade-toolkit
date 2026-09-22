"""Who has a payslip on one side and not the other, by name, with the reason.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/compare_payslip_populations.py

    SSC_MONTH=AUG SSC_YEAR=2026 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/compare_payslip_populations.py

Native payroll made 219 payslips for Saud Shehatha Labour and ssc_payroll's WPS
batch holds 186. Comparing the two engines' arithmetic is pointless until they
are computing for the same people, and a difference of thirty three is not
something to reason about from two screenshots.

Three things make the counts differ, and all of them push the same way:

  * ssc splits its payslips into a WPS batch and a CASH batch on whether the
    employee has an employee_code. One batch is never the whole company;
  * ssc skips an employee whose total attendance days come to zero -
    "if not (employee and summary.total_att_days): continue" - and native
    generates for anybody with a running contract;
  * an hr.employee with no ssc.employee behind it never reaches the attendance
    sheet, so it gets no ssc payslip at all, while native neither knows nor
    cares.

So this lists both populations per company, and then the names in one and not
the other with which of those three explains it.

Read-only.
"""
import os
from collections import defaultdict

WIDTH = 104
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


title("payslip populations for %s-%s" % (MONTH, YEAR))

NativeSlip = env.get('hr.payslip')
SscSlip = env.get('ssc.payslip')
if NativeSlip is None or SscSlip is None:
    print("  one of the two payrolls is not installed here")
    raise SystemExit

# --- native, keyed by hr.employee -------------------------------------------
native = defaultdict(set)          # company -> {hr_employee_id}
native_slips = defaultdict(list)
for slip in NativeSlip.sudo().search([]):
    if not (slip.date_from and slip.date_from.strftime('%b').upper() == MONTH
            and str(slip.date_from.year) == str(YEAR)):
        continue
    company = slip.employee_id.company_id
    native[company].add(slip.employee_id.id)
    native_slips[company].append(slip)

# --- ssc, keyed by the hr.employee behind its ssc.employee -------------------
ssc = defaultdict(set)
ssc_unlinked = defaultdict(list)
ssc_slips = defaultdict(list)
for slip in SscSlip.sudo().search([('month', '=', MONTH), ('year', '=', str(YEAR))]):
    company = slip.employee_id.company_id
    ssc_slips[company].append(slip)
    hr_employee = slip.employee_id.hr_employee_id
    if hr_employee:
        ssc[company].add(hr_employee.id)
    else:
        ssc_unlinked[company].append(slip)

companies = sorted(set(native) | set(ssc), key=lambda c: c.name or '')

for company in companies:
    title(company.name or '?', '-')
    on_native = native.get(company, set())
    on_ssc = ssc.get(company, set())
    print("  native %4s payslip(s) for %4s employee(s)"
          % (len(native_slips.get(company, [])), len(on_native)))
    print("  ssc    %4s payslip(s) for %4s employee(s)%s"
          % (len(ssc_slips.get(company, [])), len(on_ssc),
             "   (+%s with no hr.employee behind them)"
             % len(ssc_unlinked[company]) if ssc_unlinked[company] else ""))

    # ssc splits WPS from CASH; say so rather than let one batch look like all.
    by_kind = defaultdict(int)
    for slip in ssc_slips.get(company, []):
        by_kind['CASH' if slip.is_cash else 'WPS'] += 1
    if by_kind:
        print("  ssc payslips by payment type: %s"
              % ", ".join("%s=%s" % kv for kv in sorted(by_kind.items())))

    only_native = on_native - on_ssc
    only_ssc = on_ssc - on_native
    print("\n  %s on native only, %s on ssc only"
          % (len(only_native), len(only_ssc)))

    if only_native:
        print("\n  ON NATIVE ONLY - why ssc did not make one:")
        reasons = defaultdict(list)
        for employee in env['hr.employee'].sudo().browse(sorted(only_native)):
            profile = env['ssc.employee'].sudo().search(
                [('hr_employee_id', '=', employee.id)], limit=1)
            if not profile:
                reasons["no ssc.employee behind them - off the sheet entirely"]\
                    .append(employee.name)
            elif profile.is_engineer_office:
                reasons["Engineer/Office staff - paid on the staff sheet"]\
                    .append(employee.name)
            elif profile.is_cancelled:
                reasons["cancelled on ssc.employee"].append(employee.name)
            else:
                summary = env['ssc.attendance.summary'].sudo().search(
                    [('ssc_employee_id', '=', profile.id)], limit=1)
                if summary and not summary.total_att_days:
                    reasons["zero attendance days - ssc skips them"]\
                        .append(employee.name)
                else:
                    reasons["on the sheet, but no ssc payslip - worth a look"]\
                        .append(employee.name)
        for why, names in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
            print("    %4s  %s" % (len(names), why))
            print("          %s" % ", ".join(sorted(names)[:8]))
            if len(names) > 8:
                print("          ... and %s more" % (len(names) - 8))

    if only_ssc:
        print("\n  ON SSC ONLY - native made no payslip:")
        names = env['hr.employee'].sudo().browse(sorted(only_ssc)).mapped('name')
        print("    %s" % ", ".join(sorted(n or '?' for n in names)[:12]))
        if len(names) > 12:
            print("    ... and %s more" % (len(names) - 12))
        print("    (a contract not running in the period, or the pay run did "
              "not include them)")

title("read only - nothing was written")
