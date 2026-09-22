"""Match the two payrolls line for line: who, how many days, and every dirham.

    cd ~/src/user

    # Saud and Royal Arrow labour, everything:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/reconcile_payrolls.py

    # every employee, not only the ones that differ:
    SSC_DETAIL=all odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/reconcile_payrolls.py

    # one company, or one person:
    SSC_COMPANIES="ROYAL ARROW" ...
    SSC_EMPLOYEE="Ahmad Ali Sameu" ...

THE TWO ARITHMETICS, WHICH IS WHY THEY CAN BE MATCHED AT ALL

    ssc     rate_per_day = gross_salary / days_in_month
            total_salary = gross_salary                       if attendance >= days
                         = rate_per_day * total_attendance    otherwise

    native  ratio = (period_days - absent) / days_in_month
            BASIC etc = wage * ratio

  They agree exactly when gross_salary equals wage and total_attendance equals
  period_days minus absences. So every gap is one of those two and nothing
  else, and both are printed as their own columns rather than left to be
  inferred back out of the money. A base gap is a wage gap or a day gap; there
  is no third kind.

  Native's day count is recovered as base / wage * days_in_month - the ratio
  the rule actually applied, in days, directly comparable to ssc's
  total_attendance. The worked-days lines are printed too, but those carry
  Odoo's own work-entry classification and do not always sum to the ratio.

WHAT IS COMPARED

  contract     ssc gross_salary (basic + house + transport + other)
               against hr.version.wage
  days         ssc days, total_attendance
               against the period length and the ratio native applied
  base         ssc total_salary against BASIC + HOUALLOW + TRAALLOW + OTALLOW
  overtime     ssc overtime_reg_amount / overtime_off_amount
               against OT_REG / OT_OFF, each side separately
  adjustments  ssc salary_adjustment and its attachments
               against the native inputs and whatever NET has left over
  net          ssc net_amount against NET

  Every component is a named field on both sides except the native adjustment,
  which is taken as a remainder on purpose: naming each deduction code would go
  stale the day somebody adds one, and if the named parts and the net are right
  the rest is right by subtraction.

Read-only.
"""
import os
from collections import defaultdict

from dateutil.relativedelta import relativedelta

WIDTH = 170
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
TOL = float(os.environ.get('SSC_TOLERANCE') or 0.5)
DETAIL = (os.environ.get('SSC_DETAIL') or 'mismatched').lower()
DEEP = int(os.environ.get('SSC_DEEP') or 3)
WANTED = (os.environ.get('SSC_EMPLOYEE') or '').strip().lower()
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or 'SAUD,ROYAL ARROW').split(',')
        if n.strip()]

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


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value, width=11):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


def day(value):
    return "{:>7.2f}".format(value or 0.0)


# Say the period out loud. Both sides are filtered on it and a reconciliation
# read against the wrong month is worse than none.
print("")
print("=" * WIDTH)
print("  period      %s-%s only" % (MONTH, YEAR))
print("  companies   %s" % ", ".join(ONLY))
print("  population  labour only - staff are a different sheet and a different sum")
print("=" * WIDTH)


NativeSlip = env['hr.payslip'].sudo()
SscSlip = env['ssc.payslip'].sudo()
Employee = env['hr.employee'].sudo()


def in_scope(company):
    name = (company.name or '').upper()
    return any(part in name for part in ONLY)


# --------------------------------------------------------------- collect both
native = defaultdict(dict)
native_dupes = defaultdict(list)
for slip in NativeSlip.search([]):
    if not (slip.date_from and slip.date_from.strftime('%b').upper() == MONTH
            and str(slip.date_from.year) == str(YEAR)):
        continue
    if not (slip.struct_id.name or '').endswith('Labour Pay'):
        continue
    # A cancelled payslip pays nothing and must not be counted as one.
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
for slip in SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR)),
                            ('is_staff', '=', False)]):
    company = slip.employee_id.company_id
    if not in_scope(company):
        continue
    employee = hr_employee_of(slip)
    if not employee:
        ssc_unlinked[company].append(slip)
        continue
    ssc[company][employee.id] = slip


def native_parts(slip):
    """Every native component this comparison names, by code."""
    parts = defaultdict(float)
    for line in slip.line_ids:
        parts[line.code or '?'] += line.total
    base = sum(parts[code] for code in BASE_CODES)
    return {
        'base': base,
        'ot_reg': parts.get('OT_REG', 0.0),
        'ot_off': parts.get('OT_OFF', 0.0),
        'net': parts.get('NET', 0.0),
        'adjust': parts.get('NET', 0.0) - base
        - parts.get('OT_REG', 0.0) - parts.get('OT_OFF', 0.0),
        'lines': parts,
    }


def days_in_month_of(date_value):
    first = date_value.replace(day=1)
    return ((first + relativedelta(months=1)) - first).days


# --------------------------------------------------------------- 1. who is on
title("1. who each payroll paid   -   %s-%s, labour only" % (MONTH, YEAR))
companies = sorted(set(native) | set(ssc), key=lambda c: c.name or '')
matched = {}
for company in companies:
    on_native, on_ssc = native.get(company, {}), ssc.get(company, {})
    both = set(on_native) & set(on_ssc)
    matched[company] = both
    print("\n  %s" % (company.name or '?'))
    print("    native %4s    ssc %4s    matched %4s    native only %3s    ssc only %3s"
          % (len(on_native), len(on_ssc), len(both),
             len(set(on_native) - set(on_ssc)), len(set(on_ssc) - set(on_native))))
    if native_dupes[company]:
        print("    !! %s employee(s) hold more than one native labour payslip"
              % len(native_dupes[company]))
        for slip in native_dupes[company][:6]:
            print("       %s" % (slip.employee_id.name or '?'))
    if ssc_unlinked[company]:
        print("    !! %s ssc payslip(s) have no hr.employee behind them"
              % len(ssc_unlinked[company]))

    for label, ids in (("native only", set(on_native) - set(on_ssc)),
                       ("ssc only", set(on_ssc) - set(on_native))):
        if not ids:
            continue
        print("    %s:" % label)
        for employee in Employee.browse(sorted(ids)):
            print("        %s" % (employee.name or '?'))

# ------------------------------------------------------------ build every row
rows = []
for company in companies:
    for employee_id in matched.get(company, ()):
        s = ssc[company][employee_id]
        n = native[company][employee_id]
        parts = native_parts(n)
        employee = n.employee_id
        wage = employee.sudo().version_id.wage or 0.0
        period_days = ((n.date_to - n.date_from).days + 1) if (n.date_to and n.date_from) else 0
        month_days = days_in_month_of(n.date_to) if n.date_to else 0
        # hr.version.wage is the BASIC alone - HOUALLOW and TRAALLOW are derived
        # from it by the structure, so wage is 60% of the contract, not all of
        # it. The ratio therefore has to be read off BASIC against wage; taking
        # the whole base against wage inflates it by 1/0.6 and turns 25 days
        # into 41.67, which is what the first run of this reported.
        basic = parts['lines'].get('BASIC', 0.0)
        ratio = (basic / wage) if wage else 0.0
        native_days = ratio * month_days
        # And the native contract gross, grossed back up by the same share.
        native_gross = (wage * parts['base'] / basic) if basic else wage
        worked = sum(line.number_of_days for line in n.worked_days_line_ids)
        rows.append({
            'company': company, 'employee': employee, 'ssc': s, 'native': n,
            'parts': parts, 'wage': wage, 'period_days': period_days,
            'month_days': month_days, 'native_days': native_days,
            'worked_days': worked, 'native_gross': native_gross,
            'basic': basic, 'ratio': ratio,
            'd_wage': (s.gross_salary or 0.0) - native_gross,
            'd_basic': (s.basic_salary or 0.0) - wage,
            'd_days': (s.total_attendance or 0.0) - native_days,
            'd_base': (s.total_salary or 0.0) - parts['base'],
            'd_reg': (s.overtime_reg_amount or 0.0) - parts['ot_reg'],
            'd_off': (s.overtime_off_amount or 0.0) - parts['ot_off'],
            'd_adjust': (s.salary_adjustment or 0.0) - parts['adjust'],
            'd_net': (s.net_amount or 0.0) - parts['net'],
        })


def signature(row):
    bits = []
    if abs(row['d_wage']) > TOL:
        bits.append('wage')
    if abs(row['d_days']) > 0.05:
        bits.append('days')
    if abs(row['d_base']) > TOL:
        bits.append('base')
    if abs(row['d_reg']) > TOL or abs(row['d_off']) > TOL:
        bits.append('overtime')
    if abs(row['d_adjust']) > TOL:
        bits.append('adjust')
    return "+".join(bits) or 'matches'


# ------------------------------------------------------------- 2. the totals
title("2. every component, totalled   (tolerance %s)" % TOL)
for company in companies:
    here = [r for r in rows if r['company'] == company]
    if not here:
        continue
    print("\n  %s   -   %s matched employee(s)" % (company.name or '?', len(here)))
    print("    %-22s %14s %14s %14s   %s"
          % ("component", "ssc", "native", "gap", "employees differing"))
    print("    " + "-" * (WIDTH - 6))
    for label, ssc_field, part, gap in (
            ("contract basic", 'basic_salary', 'wage', 'd_basic'),
            ("contract gross", 'gross_salary', 'native_gross', 'd_wage'),
            ("base earned", 'total_salary', 'base', 'd_base'),
            ("overtime regular", 'overtime_reg_amount', 'ot_reg', 'd_reg'),
            ("overtime off-day", 'overtime_off_amount', 'ot_off', 'd_off'),
            ("adjustments", 'salary_adjustment', 'adjust', 'd_adjust'),
            ("NET", 'net_amount', 'net', 'd_net')):
        ssc_total = sum(r['ssc'][ssc_field] or 0.0 for r in here)
        nat_total = sum(r['wage'] if part == 'wage'
                        else r['native_gross'] if part == 'native_gross'
                        else r['parts'][part] for r in here)
        differing = len([r for r in here if abs(r[gap]) > TOL])
        print("    %-22s %14s %14s %14s   %s"
              % (label, num(ssc_total, 13), num(nat_total, 13),
                 num(ssc_total - nat_total, 13), differing))
    ssc_days = sum(r['ssc'].total_attendance or 0.0 for r in here)
    nat_days = sum(r['native_days'] for r in here)
    print("    %-22s %14s %14s %14s   %s"
          % ("days paid", num(ssc_days, 13), num(nat_days, 13),
             num(ssc_days - nat_days, 13),
             len([r for r in here if abs(r['d_days']) > 0.05])))

# ---------------------------------------------------------- 3. the patterns
title("3. what kind of mismatch, and how many of each")
patterns = defaultdict(list)
for row in rows:
    patterns[signature(row)].append(row)
for pattern, group in sorted(patterns.items(), key=lambda kv: -len(kv[1])):
    total = sum(r['d_net'] for r in group)
    print("\n  %-28s %4s employee(s)   net effect %s"
          % (pattern, len(group), num(total)))
    for row in sorted(group, key=lambda r: -abs(r['d_net']))[:6]:
        print("        %-40s net gap %s" % ((row['employee'].name or '?')[:40],
                                            num(row['d_net'])))
    if len(group) > 6:
        print("        ... and %s more" % (len(group) - 6))

# -------------------------------------------------------- 4. every employee
title("4. employee by employee")
print("  ssc against native. A positive gap means ssc pays more."
      "  Detail: %s" % DETAIL)
print("\n  %-32s %9s %9s  %7s %7s  %11s %11s %11s %11s   %s"
      % ("employee", "wage ssc", "wage nat", "days s", "days n",
         "d base", "d overtime", "d adjust", "d net", "kind"))
print("  " + "-" * (WIDTH - 4))
shown = 0
for row in sorted(rows, key=lambda r: (r['company'].name or '', -abs(r['d_net']))):
    kind = signature(row)
    if DETAIL == 'mismatched' and kind == 'matches':
        continue
    if DETAIL == 'none':
        break
    print("  %-32s %9s %9s  %7s %7s  %11s %11s %11s %11s   %s"
          % ((row['employee'].name or '?')[:32],
             num(row['ssc'].gross_salary, 9), num(row['wage'], 9),
             day(row['ssc'].total_attendance), day(row['native_days']),
             num(row['d_base']), num(row['d_reg'] + row['d_off']),
             num(row['d_adjust']), num(row['d_net']), kind))
    shown += 1
print("\n  %s row(s) shown of %s matched" % (shown, len(rows)))

# ------------------------------------------- 4b. inputs that produced nothing
title("4b. did each salary input actually produce a line?")
print("""  The first version of this asked whether any rule MENTIONS the input code, and
  answered yes for everything. The arithmetic said otherwise: Mohamed Salah's
  NET is BASIC + HOUALLOW + TRAALLOW + LEAVESAL to the fils, with a
  SALARY_DEDUCTIONS input of 48.39 that moved nothing. A rule existing is not a
  rule firing.

  So the test here is empirical. For every payslip carrying an input, look for a
  line from a rule that reads that input and check it is non-zero. Mentioned but
  never landed is the answer that matters.
""")
Rule = env['hr.salary.rule'].sudo()
structures = {}
for row in rows:
    structures.setdefault(row['native'].struct_id, []).append(row)

for structure, group in sorted(structures.items(), key=lambda kv: kv[0].name or ''):
    rules = Rule.search([('struct_id', '=', structure.id)])
    print("  %s   -   %s rule(s), %s payslip(s)"
          % (structure.name or '?', len(rules), len(group)))

    written = defaultdict(float)
    carriers = defaultdict(list)
    for row in group:
        for line in row['native'].input_line_ids:
            written[line.code or '?'] += line.amount or 0.0
            carriers[line.code or '?'].append(row)

    if not written:
        print("      no inputs on any payslip of this structure")
    for code in sorted(written):
        readers = []
        for rule in rules:
            text = ""
            for field in ('amount_python_compute', 'condition_python'):
                value = rule[field] if field in rule._fields else None
                if isinstance(value, str):
                    text += " " + value
            points_at = ('amount_other_input_id' in rule._fields
                         and rule.amount_other_input_id
                         and rule.amount_other_input_id.code == code)
            if rule.code == code or code in text or points_at:
                readers.append(rule)

        # Ask the payslip for a line of this code. The previous version went
        # through the reader rules and answered zero for codes that had plainly
        # landed - Ram Lochan's SALARY_DEDUCTIONS line is -193.55 on the record.
        landed = 0
        landed_total = 0.0
        for row in carriers[code]:
            for line in row['native'].line_ids:
                if line.code == code and line.total:
                    landed += 1
                    landed_total += line.total
                    break
        held = len(carriers[code])
        print("      %-20s %s over %3s payslip(s)   %s rule(s), %s line(s) "
              "produced totalling %s%s"
              % (code, num(written[code]), held, len(readers), landed,
                 num(landed_total),
                 "   !! INERT - the money moves nothing" if not landed else ""))
        for rule in readers[:4]:
            print("          rule %-16s %-30s sequence %s"
                  % (rule.code or '?', (rule.name or '')[:30], rule.sequence))
    print("")

# ------------------------------------ 4c. what native pays that ssc does not
title("4c. rule lines with no counterpart on the ssc side")
print("""  LEAVESAL is 4,600 on one payslip and 3,100 on another - annual leave salary
  that native pays and ssc does not, and the whole of those employees' gaps.
  Anything native pays outside base, overtime and the inputs belongs here.
""")
KNOWN = set(BASE_CODES) | {'OT_REG', 'OT_OFF', 'NET', 'GROSS', 'NETCOST'}
extra = defaultdict(lambda: [0.0, []])
for row in rows:
    for code, value in row['parts']['lines'].items():
        if code in KNOWN or not value:
            continue
        extra[code][0] += value
        extra[code][1].append((row['employee'].name or '?', value))
if not extra:
    print("  none - every native line is one this comparison already names")
for code, (total, people) in sorted(extra.items(), key=lambda kv: -abs(kv[1][0])):
    print("  %-16s %s over %3s payslip(s)" % (code, num(total), len(people)))
    for name, value in sorted(people, key=lambda p: -abs(p[1]))[:6]:
        print("      %-44s %s" % (name[:44], num(value)))
    if len(people) > 6:
        print("      ... and %s more" % (len(people) - 6))


# ----------------------------- 4d. the adjustment gap, decomposed on both sides
title("4d. where the adjustment gap actually is, per employee")
print("""  The inputs land - Ram Lochan's SALARY_DEDUCTIONS line is -193.55 on the
  payslip and his NET is base + overtime + that, to the fils. So an adjustment
  gap is no longer "native ignored it"; it is the two sides holding different
  amounts. Both are listed rather than subtracted.

  The attachments were moved WITHOUT SSC_DETACH, so each one is deliberately on
  both sides. If ssc still counts an attachment in salary_adjustment that also
  became a native input, the two agree. If ssc counts something that never
  moved, it shows here as ssc-only.
""")
KNOWN_LINE = set(BASE_CODES) | {'OT_REG', 'OT_OFF', 'NET', 'GROSS', 'NETCOST'}
gapped = sorted((r for r in rows if abs(r['d_adjust']) > TOL),
                key=lambda r: -abs(r['d_adjust']))
print("  %s employee(s) differ on adjustments" % len(gapped))
for row in gapped[:int(os.environ.get('SSC_ADJUST') or 12)]:
    s, n = row['ssc'], row['native']
    print("")
    print("  %-40s ssc %s   native %s   gap %s"
          % ((row['employee'].name or '?')[:40], num(s.salary_adjustment),
             num(row['parts']['adjust']), num(row['d_adjust'])))
    print("      ssc attachments:")
    if not s.attachment_ids:
        print("          none")
    for attachment in s.attachment_ids:
        print("          %-34s %s  %s"
              % ((attachment.type_id.name or '?')[:34],
                 num(attachment.signed_value), attachment.state or '-'))
    print("      native lines outside base and overtime:")
    any_line = False
    for code, value in sorted(row['parts']['lines'].items()):
        if code in KNOWN_LINE or not value:
            continue
        print("          %-34s %s" % (code, num(value)))
        any_line = True
    if not any_line:
        print("          none")
    print("      native inputs:")
    if not n.input_line_ids:
        print("          none")
    for line in n.input_line_ids:
        print("          %-34s %s" % (line.code or '?', num(line.amount)))
if len(gapped) > 12:
    print("")
    print("... and %s more. Raise SSC_ADJUST to see them."
          % (len(gapped) - 12))


# ------------------------------------------------------------ 5. the deep dive
title("5. the worst gaps, whole")
if WANTED:
    deep = [r for r in rows if WANTED in (r['employee'].name or '').lower()]
else:
    deep = sorted(rows, key=lambda r: -abs(r['d_net']))[:DEEP]

for row in deep:
    n, s = row['native'], row['ssc']
    title("%s   -   %s" % (row['employee'].name or '?',
                           row['company'].name or '-'), '-')
    print("    contract   ssc gross %s   native wage %s   gap %s"
          % (num(s.gross_salary), num(row['wage']), num(row['d_wage'])))
    print("    period     native %s .. %s = %s day(s) of a %s day month"
          % (n.date_from, n.date_to, row['period_days'], row['month_days']))
    print("    days       ssc attendance %s   native ratio in days %s   gap %s"
          % (day(s.total_attendance), day(row['native_days']), day(row['d_days'])))
    print("    rate/day   ssc %s   native %s"
          % (num(s.rate_per_day),
             num(row['wage'] / row['month_days'] if row['month_days'] else 0)))

    print("\n    native worked-days lines (Odoo's own classification):")
    if not n.worked_days_line_ids:
        print("        none")
    for line in n.worked_days_line_ids:
        print("        %-36s %7s day(s) %8s hour(s) %s"
              % ((line.name or line.code or '?')[:36], line.number_of_days,
                 line.number_of_hours, num(line.amount)))

    print("\n    native salary rule lines:")
    for code, value in sorted(row['parts']['lines'].items()):
        if value:
            print("        %-16s %s" % (code, num(value)))

    print("\n    native salary inputs:")
    if not n.input_line_ids:
        print("        none")
    input_codes = defaultdict(float)
    for line in n.input_line_ids:
        input_codes[line.code or '?'] += line.amount or 0.0
        print("        %-20s %-34s %s"
              % (line.code or '?', (line.input_type_id.name or '')[:34],
                 num(line.amount)))
    orphans = [c for c in input_codes if c not in row['parts']['lines']]
    for code in sorted(orphans):
        print("        !! %-17s %s  written but no rule line of that code"
              % (code, num(input_codes[code])))

    print("\n    ssc attachments:")
    if not s.attachment_ids:
        print("        none")
    for attachment in s.attachment_ids:
        print("        %-34s %s  %-10s signed %s"
              % ((attachment.type_id.name or '?')[:34], num(attachment.value),
                 attachment.state or '-', num(attachment.signed_value)))
    print("        ssc salary_adjustment %s   native remainder %s   gap %s"
          % (num(s.salary_adjustment), num(row['parts']['adjust']),
             num(row['d_adjust'])))

title("read only - nothing was written")
