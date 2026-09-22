"""One employee, both payrolls, every figure that goes into the salary.

    cd ~/src/user

    # everybody who differs anywhere, Saud and Royal Arrow labour:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/audit_employee_payroll.py

    SSC_EMPLOYEE="Rageev Ahamad" ...   one person
    SSC_ALL=1 ...                      everybody, including those that agree
    SSC_DAYS=0 ...                     skip the day-by-day table
    SSC_TOP=20 ...                     how many full dossiers to print

The comparisons written so far each answer one question - who was paid, how the
components total, where the days and overtime differ. This answers all of them
for one person at a time, because a remaining gap is now specific to somebody
rather than systematic, and a total cannot be argued with while a line can.

WHAT EACH DOSSIER HOLDS

  contract    ssc basic, house, transport, other and gross against the native
              wage and what the structure derives from it; the day rate and
              both overtime rates
  attendance  ssc total_attendance and its day lines - status, earned fraction,
              worked hours, overtime, off-day flag, missing check-out - against
              the native worked-days lines and every work entry by type and
              state, cancelled ones marked as not counting
  overtime    regular and off-day, in HOURS and in money, on both sides, with
              the rate each side applied, so a rate difference and a counting
              difference cannot be confused for each other
  earnings    every native rule line by code, and the ssc figures beside them
  adjustments every ssc attachment with its type, value, sign and state, and
              every native salary input, and any native line outside the
              standard set
  net         the four gaps that make up the difference, each traceable to the
              section above it

An index runs first with one line per employee so a person can be found before
reading three hundred lines about somebody else.

Read-only.
"""
import os
from collections import defaultdict

from dateutil.relativedelta import relativedelta

WIDTH = 128
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
TOL = float(os.environ.get('SSC_TOLERANCE') or 0.5)
TOP = int(os.environ.get('SSC_TOP') or 15)
SHOW_DAYS = (os.environ.get('SSC_DAYS') or '1') != '0'
ALL = os.environ.get('SSC_ALL') == '1'
WANTED = (os.environ.get('SSC_EMPLOYEE') or '').strip().lower()
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or 'SAUD,ROYAL ARROW').split(',')
        if n.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

BASE_CODES = ('BASIC', 'HOUALLOW', 'TRAALLOW', 'OTALLOW')
STANDARD = set(BASE_CODES) | {'OT_REG', 'OT_OFF', 'GROSS', 'NET', 'NETCOST'}


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


def rule(char='-'):
    print("  " + char * (WIDTH - 4))


def num(value, width=11):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


NativeSlip = env['hr.payslip'].sudo()
SscSlip = env['ssc.payslip'].sudo()
WorkEntry = env['hr.work.entry'].sudo()
Attendance = env['hr.attendance'].sudo()


def days_in_month_of(value):
    first = value.replace(day=1)
    return ((first + relativedelta(months=1)) - first).days


# ------------------------------------------------------------- gather the pairs
rows = []
for ssc in SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR)),
                           ('is_staff', '=', False)]):
    employee = ssc.employee_id.hr_employee_id
    if not employee:
        continue
    company = employee.company_id
    if ONLY and not any(p in (company.name or '').upper() for p in ONLY):
        continue
    if WANTED and WANTED not in (employee.name or '').lower():
        continue
    native = NativeSlip.search([('employee_id', '=', employee.id)]).filtered(
        lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
        and str(s.date_from.year) == str(YEAR)
        and (s.struct_id.name or '').endswith('Labour Pay')
        and s.state != 'cancel')
    if not native:
        continue
    native = native[0]

    lines = defaultdict(float)
    for line in native.line_ids:
        lines[line.code or '?'] += line.total
    version = employee.sudo().version_id
    wage = version.wage or 0.0
    month_days = days_in_month_of(native.date_to) if native.date_to else 31
    basic = lines['BASIC']
    ratio = (basic / wage) if wage else 0.0

    ot_hours = defaultdict(float)
    worked_days = []
    for line in native.worked_days_line_ids:
        name = line.name or line.code or '?'
        if 'overtime' in name.lower():
            ot_hours['off' if 'off' in name.lower() else 'reg'] += \
                line.number_of_hours or 0.0
        worked_days.append(line)

    base = sum(lines[c] for c in BASE_CODES)
    rows.append({
        'employee': employee, 'company': company, 'ssc': ssc, 'native': native,
        'version': version, 'wage': wage, 'lines': lines, 'base': base,
        'ratio': ratio, 'native_days': ratio * month_days,
        'month_days': month_days, 'ot_hours': ot_hours,
        'worked_days': worked_days,
        'd_days': (ssc.total_attendance or 0.0) - ratio * month_days,
        'd_base': (ssc.total_salary or 0.0) - base,
        'd_ot_reg': (ssc.overtime_reg_amount or 0.0) - lines['OT_REG'],
        'd_ot_off': (ssc.overtime_off_amount or 0.0) - lines['OT_OFF'],
        'd_adjust': (ssc.salary_adjustment or 0.0)
        - (lines['NET'] - base - lines['OT_REG'] - lines['OT_OFF']),
        'd_net': (ssc.net_amount or 0.0) - lines['NET'],
    })


def differs(row):
    return (abs(row['d_days']) > 0.05 or abs(row['d_base']) > TOL
            or abs(row['d_ot_reg']) > TOL or abs(row['d_ot_off']) > TOL
            or abs(row['d_adjust']) > TOL or abs(row['d_net']) > TOL)


print("")
print("=" * WIDTH)
print("  %s-%s   %s   labour only, matched on both sides   %s employee(s)"
      % (MONTH, YEAR, ", ".join(ONLY), len(rows)))
print("=" * WIDTH)

# ------------------------------------------------------------------- the index
title("index - one line each, sorted by the size of the net gap")
print("  %-34s %8s %8s %10s %10s %10s %10s %10s"
      % ("employee", "days s", "days n", "d base", "d OTreg", "d OToff",
         "d adjust", "d net"))
rule()
ordered = sorted(rows, key=lambda r: -abs(r['d_net']))
for row in ordered:
    flag = "" if differs(row) else "  ok"
    print("  %-34s %8.2f %8.2f %10s %10s %10s %10s %10s%s"
          % ((row['employee'].name or '?')[:34],
             row['ssc'].total_attendance or 0.0, row['native_days'],
             num(row['d_base'], 10), num(row['d_ot_reg'], 10),
             num(row['d_ot_off'], 10), num(row['d_adjust'], 10),
             num(row['d_net'], 10), flag))
rule()
print("  %s of %s agree on every component"
      % (len([r for r in rows if not differs(r)]), len(rows)))

# --------------------------------------------------------------- the dossiers
chosen = ordered if (ALL or WANTED) else [r for r in ordered if differs(r)][:TOP]
title("%s dossier(s) follow" % len(chosen))

for row in chosen:
    ssc, native = row['ssc'], row['native']
    employee, version = row['employee'], row['version']
    lines = row['lines']

    title("%s   %s   -   %s"
          % (ssc.employee_code or '', employee.name or '?',
             row['company'].name or '-'))
    print("  ssc payslip [%s] %s %s .. %s   state=%s   %s"
          % (ssc.id, ssc.month, ssc.from_date, ssc.to_date, ssc.state,
             "CASH" if ssc.is_cash else "WPS"))
    print("  native      [%s] %s .. %s   state=%s   %s"
          % (native.id, native.date_from, native.date_to, native.state,
             native.struct_id.name or '?'))

    # ------------------------------------------------------------- contract
    rule('=')
    print("  CONTRACT")
    print("      %-26s %14s %14s"
          % ("", "ssc", "native"))
    print("      %-26s %14s %14s"
          % ("basic", num(ssc.basic_salary), num(row['wage'])))
    print("      %-26s %14s %14s"
          % ("house allowance", num(ssc.house_allowance), "derived"))
    print("      %-26s %14s %14s"
          % ("transport allowance", num(ssc.transport_allowance), "derived"))
    print("      %-26s %14s %14s"
          % ("other allowances", num(ssc.other_allowance), "derived"))
    print("      %-26s %14s %14s"
          % ("gross", num(ssc.gross_salary),
             num(row['wage'] * row['base'] / lines['BASIC'])
             if lines['BASIC'] else "n/a"))
    print("      %-26s %14s %14s"
          % ("days in month", ssc.days, row['month_days']))
    print("      %-26s %14s %14s"
          % ("rate per day", num(ssc.rate_per_day),
             num(row['wage'] / row['month_days'] if row['month_days'] else 0)))
    print("      %-26s %14s %14s"
          % ("OT rate regular", num(ssc.ot_rate_regular), "from the rule"))
    print("      %-26s %14s %14s"
          % ("OT rate off-day", num(ssc.ot_rate_off), "from the rule"))
    print("      contract %s .. %s   calendar %s"
          % (version.contract_date_start or 'none',
             version.contract_date_end or 'open',
             version.resource_calendar_id.name or 'none'))

    # ----------------------------------------------------------- attendance
    rule('=')
    print("  ATTENDANCE")
    print("      ssc    days paid %.2f" % (ssc.total_attendance or 0.0))
    print("      native ratio %.6f x %s days = %.2f day(s)"
          % (row['ratio'], row['month_days'], row['native_days']))
    print("      gap    %.2f day(s)" % row['d_days'])
    print("")
    print("      native worked-days lines:")
    if not row['worked_days']:
        print("          none")
    for line in row['worked_days']:
        print("          %-40s %8s day(s) %9s hour(s) %s"
              % ((line.name or line.code or '?')[:40], line.number_of_days,
                 line.number_of_hours, num(line.amount)))

    entries = defaultdict(lambda: [0, 0.0])
    by_date = defaultdict(list)
    for entry in WorkEntry.search([('employee_id', '=', employee.id),
                                   ('date', '>=', str(native.date_from)),
                                   ('date', '<=', str(native.date_to))],
                                  order='date'):
        key = (entry.work_entry_type_id.name or '?', entry.state)
        entries[key][0] += 1
        entries[key][1] += entry.duration if 'duration' in entry._fields else 0.0
        if entry.state != 'cancelled':
            by_date[str(entry.date)].append(entry)
    print("")
    print("      work entries by type and state:")
    for (name, state), (count, hours) in sorted(entries.items()):
        mark = "  (cancelled - does not count)" if state == 'cancelled' else ""
        print("          %-40s %-11s %4s  %8.2f h%s"
              % (name[:40], state, count, hours, mark))

    # ------------------------------------------------------------- overtime
    rule('=')
    print("  OVERTIME")
    print("      %-22s %12s %12s %12s   %12s %12s %12s"
          % ("", "ssc hours", "nat hours", "d hours",
             "ssc money", "nat money", "d money"))
    for label, s_h, n_h, s_m, n_m in (
            ("regular", ssc.overtime_reg or 0.0, row['ot_hours']['reg'],
             ssc.overtime_reg_amount or 0.0, lines['OT_REG']),
            ("off-day", ssc.overtime_off or 0.0, row['ot_hours']['off'],
             ssc.overtime_off_amount or 0.0, lines['OT_OFF'])):
        print("      %-22s %12.2f %12.2f %12.2f   %12s %12s %12s"
              % (label, s_h, n_h, s_h - n_h, num(s_m, 12), num(n_m, 12),
                 num(s_m - n_m, 12)))
    if (ssc.overtime_reg or 0) and lines['OT_REG']:
        print("      implied rate  ssc %.4f   native %.4f"
              % ((ssc.overtime_reg_amount or 0) / (ssc.overtime_reg or 1),
                 lines['OT_REG'] / (row['ot_hours']['reg'] or 1)))

    # ------------------------------------------------------------- earnings
    rule('=')
    print("  EARNINGS")
    print("      native rule lines:")
    for code in sorted(lines):
        if lines[code]:
            extra = "" if code in STANDARD else "   <-- outside the standard set"
            print("          %-18s %s%s" % (code, num(lines[code]), extra))
    print("")
    print("      %-26s %14s %14s %14s"
          % ("", "ssc", "native", "gap"))
    print("      %-26s %14s %14s %14s"
          % ("base earned", num(ssc.total_salary), num(row['base']),
             num(row['d_base'])))
    print("      %-26s %14s %14s %14s"
          % ("overtime", num(ssc.overtime_salary),
             num(lines['OT_REG'] + lines['OT_OFF']),
             num((ssc.overtime_salary or 0)
                 - lines['OT_REG'] - lines['OT_OFF'])))
    print("      %-26s %14s %14s %14s"
          % ("adjustments", num(ssc.salary_adjustment),
             num(lines['NET'] - row['base'] - lines['OT_REG'] - lines['OT_OFF']),
             num(row['d_adjust'])))
    print("      %-26s %14s %14s %14s"
          % ("NET", num(ssc.net_amount), num(lines['NET']), num(row['d_net'])))

    # ---------------------------------------------------------- adjustments
    rule('=')
    print("  ADJUSTMENTS")
    print("      ssc attachments:")
    if not ssc.attachment_ids:
        print("          none")
    for attachment in ssc.attachment_ids:
        print("          %-36s value %s  signed %s  state=%s"
              % ((attachment.type_id.name or '?')[:36],
                 num(attachment.value), num(attachment.signed_value),
                 attachment.state or '-'))
    print("      native salary inputs:")
    if not native.input_line_ids:
        print("          none")
    for line in native.input_line_ids:
        print("          %-36s %s   type [%s]"
              % ((line.code or '?')[:36], num(line.amount),
                 line.input_type_id.id))

    # ------------------------------------------------------------ day by day
    if SHOW_DAYS and ssc.day_ids:
        rule('=')
        print("  DAY BY DAY")
        print("      %-12s %-5s %-12s %7s %8s %7s %-4s %-8s %s"
              % ("date", "day", "ssc status", "earned", "worked", "ssc OT",
                 "off", "no exit", "native work entries"))
        rule()
        for day in ssc.day_ids.sorted(lambda d: d.date or ''):
            if native.date_from and day.date and day.date < native.date_from:
                continue
            side = ", ".join(
                "%s %.2f" % ((e.work_entry_type_id.name or '?')[:24],
                             e.duration if 'duration' in e._fields else 0.0)
                for e in by_date.get(str(day.date), [])) or "-"
            print("      %-12s %-5s %-12s %7.2f %8.2f %7.2f %-4s %-8s %s"
                  % (day.date, (day.day_name or '')[:5], (day.status or '')[:12],
                     day.day_ratio or 0.0, day.worked_hours or 0.0,
                     day.overtime or 0.0, "yes" if day.is_off_day else "",
                     "yes" if day.missing_checkout else "", side[:44]))

title("read only - nothing was written")
