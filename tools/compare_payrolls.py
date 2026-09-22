"""Hold the two payrolls side by side: who each one pays, and how much.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/compare_payrolls.py

    SSC_MONTH=AUG SSC_YEAR=2026 SSC_TOP=60 odoo-bin shell -d <database> \
        --no-http 2>/dev/null < tools/compare_payrolls.py

    # one company:
    SSC_COMPANIES="ROYAL ARROW" odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/compare_payrolls.py

Labour only. Staff are on a different sheet with a different arithmetic, and
mixing them in hides the thing this is for.

ssc_payroll is what the company actually paid, so where the two disagree it is
the native side that has to justify itself. There is no pass or fail here and
no average - a rule wrong by four hundred dirhams on one labourer is wrong by
a hundred and eighty thousand across the payroll, and an average would hide
exactly that. Every employee with a gap is printed with their own numbers.

BOTH SIDES DECOMPOSE THE SAME WAY, WHICH IS WHY THEY CAN BE COMPARED

    base    ssc: total_salary          native: BASIC + HOUALLOW + TRAALLOW
                                               + OTALLOW
    overtime ssc: overtime_salary      native: OT_REG + OT_OFF
    other   ssc: salary_adjustment     native: whatever NET has left over
    net     ssc: net_amount            native: NET

"other" is taken as a remainder on the native side on purpose. Naming every
deduction code would go stale the day somebody adds one, and a remainder cannot:
if the three named parts are right and the net is right, the rest is right by
subtraction, and if it is not, the number says so.

Read-only.
"""
import os
from collections import defaultdict

WIDTH = 124
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
TOP = int(os.environ.get('SSC_TOP') or 40)
TOLERANCE = float(os.environ.get('SSC_TOLERANCE') or 0.01)
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or '').split(',') if n.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def hr_employee_of(record):
    """The hr.employee behind an ssc record, whichever generation it is.

    ssc.employee retired on production on 2026-09-08 and every payroll document
    names hr.employee directly since. This tool still walked the old chain -
    employee_id.hr_employee_id - and hr.employee has no such field, so it died
    on the first record with the traceback hidden behind 2>/dev/null.
    """
    employee = record.employee_id
    if not employee or employee._name == 'hr.employee':
        return employee
    return employee.hr_employee_id

BASE_CODES = ('BASIC', 'HOUALLOW', 'TRAALLOW', 'OTALLOW')
OT_CODES = ('OT_REG', 'OT_OFF')


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value):
    return "{:>11,.2f}".format(value or 0.0)


NativeSlip = env.get('hr.payslip')
SscSlip = env.get('ssc.payslip')
if NativeSlip is None or SscSlip is None:
    print("one of the two payrolls is not installed here")
    raise SystemExit


def in_scope(company):
    name = (company.name or '').upper()
    return not ONLY or any(part in name for part in ONLY)


# ---------------------------------------------------------------- the two sides
native = defaultdict(dict)        # company -> {hr_employee_id: slip}
native_dupes = defaultdict(list)
for slip in NativeSlip.sudo().search([]):
    if not (slip.date_from and slip.date_from.strftime('%b').upper() == MONTH
            and str(slip.date_from.year) == str(YEAR)):
        continue
    if not (slip.struct_id.name or '').endswith('Labour Pay'):
        continue
    if slip.state == 'cancel':
        continue
    company = slip.employee_id.company_id
    if not in_scope(company):
        continue
    if slip.employee_id.id in native[company]:
        native_dupes[company].append(slip)
        continue
    native[company][slip.employee_id.id] = slip

ssc = defaultdict(dict)
ssc_unlinked = defaultdict(list)
for slip in SscSlip.sudo().search([
        ('month', '=', MONTH), ('year', '=', str(YEAR)), ('is_staff', '=', False)]):
    company = slip.employee_id.company_id
    if not in_scope(company):
        continue
    hr_employee = hr_employee_of(slip)
    if not hr_employee:
        ssc_unlinked[company].append(slip)
        continue
    ssc[company][hr_employee.id] = slip


def native_parts(slip):
    """base, overtime, other, net - the native payslip in four numbers."""
    base = overtime = net = 0.0
    for line in slip.line_ids:
        if line.code in BASE_CODES:
            base += line.total
        elif line.code in OT_CODES:
            overtime += line.total
        elif line.code == 'NET':
            net = line.total
    return base, overtime, net - base - overtime, net


def ssc_parts(slip):
    return (slip.total_salary, slip.overtime_salary,
            slip.salary_adjustment, slip.net_amount)


# ------------------------------------------------------------------- section 1
title("1. how many, and who   -   %s-%s, labour only" % (MONTH, YEAR))

companies = sorted(set(native) | set(ssc), key=lambda c: c.name or '')
matched = {}
for company in companies:
    on_native, on_ssc = native.get(company, {}), ssc.get(company, {})
    both = set(on_native) & set(on_ssc)
    matched[company] = both
    print("\n  %s" % (company.name or '?'))
    print("    native %4s   ssc %4s   matched %4s   native only %3s   ssc only %3s"
          % (len(on_native), len(on_ssc), len(both),
             len(set(on_native) - set(on_ssc)), len(set(on_ssc) - set(on_native))))
    if native_dupes[company]:
        print("    !! %s employee(s) have more than one native labour payslip"
              % len(native_dupes[company]))
    if ssc_unlinked[company]:
        print("    !! %s ssc payslip(s) have no hr.employee behind them"
              % len(ssc_unlinked[company]))

    for label, ids in (("native only", set(on_native) - set(on_ssc)),
                       ("ssc only", set(on_ssc) - set(on_native))):
        if not ids:
            continue
        names = sorted(env['hr.employee'].sudo().browse(sorted(ids)).mapped('name'))
        print("    %s: %s%s" % (label, ", ".join(n or '?' for n in names[:10]),
                                "  ... +%s" % (len(names) - 10) if len(names) > 10 else ""))

# ------------------------------------------------------------------- section 2
title("2. how much   -   ssc against native, per employee")
print("  Sorted by the size of the net gap. A positive gap means ssc pays more.\n")
print("  %-30s %11s %11s %11s   %11s %11s %11s   %11s"
      % ("employee", "ssc base", "nat base", "d base",
         "ssc net", "nat net", "d net", "d overtime"))
print("  " + "-" * (WIDTH - 4))

rows = []
for company in companies:
    for employee_id in matched.get(company, ()):
        s_base, s_ot, s_other, s_net = ssc_parts(ssc[company][employee_id])
        n_base, n_ot, n_other, n_net = native_parts(native[company][employee_id])
        rows.append({
            'name': native[company][employee_id].employee_id.name or '?',
            'company': company.name or '?',
            's': (s_base, s_ot, s_other, s_net),
            'n': (n_base, n_ot, n_other, n_net),
            'd_net': s_net - n_net,
            'd_base': s_base - n_base,
            'd_ot': s_ot - n_ot,
            'd_other': s_other - n_other,
        })

rows.sort(key=lambda r: -abs(r['d_net']))
for row in rows[:TOP]:
    print("  %-30s %s %s %s   %s %s %s   %s"
          % (row['name'][:30], num(row['s'][0]), num(row['n'][0]), num(row['d_base']),
             num(row['s'][3]), num(row['n'][3]), num(row['d_net']), num(row['d_ot'])))
if len(rows) > TOP:
    print("  ... %s more, smaller gaps. Raise SSC_TOP to see them."
          % (len(rows) - TOP))
if not rows:
    print("  no employee is on both sides - nothing to compare")

# ------------------------------------------------------------------- section 3
title("3. where the money is")

agree = [r for r in rows if abs(r['d_net']) <= TOLERANCE]
print("  %s of %s matched employee(s) agree to the fils." % (len(agree), len(rows)))

for label, key in (("base salary", 'd_base'), ("overtime", 'd_ot'),
                   ("other - deductions, inputs, adjustments", 'd_other'),
                   ("NET", 'd_net')):
    gaps = [r[key] for r in rows]
    disagree = [g for g in gaps if abs(g) > TOLERANCE]
    print("\n  %-42s %s employee(s) differ" % (label, len(disagree)))
    if disagree:
        print("    ssc higher by %s in total, native higher by %s"
              % (num(sum(g for g in disagree if g > 0)),
                 num(-sum(g for g in disagree if g < 0))))
        print("    net effect: %s" % num(sum(disagree)))

print("""
  Read the base gap first. Overtime and the adjustments are small and separable;
  the base is where a difference in how a day is counted shows up, and it is the
  one that moves with every missing punch.""")

title("read only - nothing was written")
