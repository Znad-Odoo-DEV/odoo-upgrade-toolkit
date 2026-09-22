"""Days and overtime, ssc against native, for Saud and Royal Arrow labour.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/compare_days_overtime.py

    SSC_COMPANIES="ROYAL ARROW" ...          # one company
    SSC_EMPLOYEE="Parfait Uwanshuti" ...     # one person, day by day
    SSC_DEEP=6 ...                           # how many to open day by day

The money is settled except here. Contracts match to the fils, adjustments come
out even, LEAVESAL is stopped. What is left is days and overtime, and
probe_work_entry_blockers.py showed the two faults underneath them - neither of
which is a missing work entry:

  every day typed as off-day overtime.  Parfait, Kamlesh and Ahmad Ali Sameu
      hold 21, 22 and 14 work entries for August and not one is of type
      Attendance. All are "SSC Overtime - Off Days", nine and ten hours each.
      The proration rule counts a day with no attendance entry as absent, so
      22 worked days price at zero: 174.19 / 1800 * 31 = 3.00 days.

  attendance entries cancelled.  Shakir Valiyil holds 21 Attendance entries in
      state cancelled and 7 in draft. A cancelled entry does not reach the
      payslip, which is his 25 days against 10.

Both are invisible in a money comparison and neither is fixed by generating
work entries, so this counts them directly.

WHAT IT COMPARES

  days        ssc total_attendance, and the day lines behind it, against the
              ratio native actually applied (BASIC / wage * days in month) and
              its worked-days lines
  overtime    ssc overtime_reg and overtime_off in HOURS, and the amounts they
              price to at ot_rate_regular and ot_rate_off, against native's
              OT_REG and OT_OFF lines and the hours on its overtime worked-days
  entries     every hr.work.entry in the period by type and state, so a day
              typed wrong or cancelled is a number rather than a suspicion

Read-only.
"""
import os
from collections import defaultdict

from dateutil.relativedelta import relativedelta

WIDTH = 150
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
TOL = float(os.environ.get('SSC_TOLERANCE') or 0.5)
DEEP = int(os.environ.get('SSC_DEEP') or 4)
WANTED = (os.environ.get('SSC_EMPLOYEE') or '').strip().lower()
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or 'SAUD,ROYAL ARROW').split(',')
        if n.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value, width=11):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


NativeSlip = env['hr.payslip'].sudo()
SscSlip = env['ssc.payslip'].sudo()
WorkEntry = env['hr.work.entry'].sudo()

print("")
print("=" * WIDTH)
print("  period      %s-%s only          companies   %s" % (MONTH, YEAR, ", ".join(ONLY)))
print("  population  labour only, matched on both sides")
print("=" * WIDTH)


def days_in_month_of(value):
    first = value.replace(day=1)
    return ((first + relativedelta(months=1)) - first).days


rows = []
for slip in SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR)),
                            ('is_staff', '=', False)]):
    employee = slip.employee_id.hr_employee_id
    if not employee:
        continue
    company = employee.company_id
    if ONLY and not any(p in (company.name or '').upper() for p in ONLY):
        continue
    native = NativeSlip.search([('employee_id', '=', employee.id)]).filtered(
        lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
        and str(s.date_from.year) == str(YEAR)
        and (s.struct_id.name or '').endswith('Labour Pay')
        and s.state != 'cancel')
    if not native:
        continue
    native = native[0]

    parts = defaultdict(float)
    for line in native.line_ids:
        parts[line.code or '?'] += line.total
    wage = employee.sudo().version_id.wage or 0.0
    month_days = days_in_month_of(native.date_to) if native.date_to else 0
    native_days = (parts['BASIC'] / wage * month_days) if wage else 0.0

    # Native's overtime hours live on the worked-days lines, not the rule lines.
    ot_hours = defaultdict(float)
    worked_days = defaultdict(float)
    for line in native.worked_days_line_ids:
        name = (line.name or line.code or '?')
        if 'overtime' in name.lower():
            key = 'off' if 'off' in name.lower() else 'reg'
            ot_hours[key] += line.number_of_hours or 0.0
        else:
            worked_days[name] += line.number_of_days or 0.0

    entries = defaultdict(int)
    for entry in WorkEntry.search([('employee_id', '=', employee.id),
                                   ('date', '>=', str(native.date_from)),
                                   ('date', '<=', str(native.date_to))]):
        entries[(entry.work_entry_type_id.name or '?', entry.state)] += 1

    rows.append({
        'employee': employee, 'company': company, 'ssc': slip, 'native': native,
        'native_days': native_days, 'ot_hours': ot_hours,
        'worked_days': worked_days, 'entries': entries,
        'nat_ot_reg': parts['OT_REG'], 'nat_ot_off': parts['OT_OFF'],
        'd_days': (slip.total_attendance or 0.0) - native_days,
        'd_ot_reg_h': (slip.overtime_reg or 0.0) - ot_hours['reg'],
        'd_ot_off_h': (slip.overtime_off or 0.0) - ot_hours['off'],
        'd_ot_reg': (slip.overtime_reg_amount or 0.0) - parts['OT_REG'],
        'd_ot_off': (slip.overtime_off_amount or 0.0) - parts['OT_OFF'],
    })

companies = sorted({r['company'] for r in rows}, key=lambda c: c.name or '')

# ------------------------------------------------------------- 1. the totals
title("1. days and overtime, totalled")
for company in companies:
    here = [r for r in rows if r['company'] == company]
    print("")
    print("  %s   -   %s matched employee(s)" % (company.name or '?', len(here)))
    print("    %-30s %14s %14s %14s   %s"
          % ("", "ssc", "native", "gap", "employees differing"))
    print("    " + "-" * (WIDTH - 6))
    for label, ssc_get, nat_get, gap_key, tol in (
            ("days paid",
             lambda r: r['ssc'].total_attendance, lambda r: r['native_days'],
             'd_days', TOL),
            ("overtime regular, hours",
             lambda r: r['ssc'].overtime_reg, lambda r: r['ot_hours']['reg'],
             'd_ot_reg_h', 0.5),
            ("overtime off-day, hours",
             lambda r: r['ssc'].overtime_off, lambda r: r['ot_hours']['off'],
             'd_ot_off_h', 0.5),
            ("overtime regular, money",
             lambda r: r['ssc'].overtime_reg_amount, lambda r: r['nat_ot_reg'],
             'd_ot_reg', 0.5),
            ("overtime off-day, money",
             lambda r: r['ssc'].overtime_off_amount, lambda r: r['nat_ot_off'],
             'd_ot_off', 0.5)):
        ssc_total = sum(ssc_get(r) or 0.0 for r in here)
        nat_total = sum(nat_get(r) or 0.0 for r in here)
        differing = len([r for r in here if abs(r[gap_key]) > tol])
        print("    %-30s %14s %14s %14s   %s"
              % (label, num(ssc_total, 13), num(nat_total, 13),
                 num(ssc_total - nat_total, 13), differing))

# --------------------------------------------------- 2. the work entry types
title("2. every work entry in the period, by type and state")
print("  A day typed as off-day overtime earns no attendance, and the proration")
print("  rule counts it absent. A cancelled entry does not reach the payslip at")
print("  all. Both are invisible in the money and both are counted here.")
for company in companies:
    here = [r for r in rows if r['company'] == company]
    combined = defaultdict(int)
    for row in here:
        for key, count in row['entries'].items():
            combined[key] += count
    print("")
    print("  %s" % (company.name or '?'))
    for (name, state), count in sorted(combined.items(),
                                       key=lambda kv: (-kv[1], kv[0])):
        mark = ""
        if state == 'cancelled':
            mark = "   <-- cancelled entries never reach a payslip"
        elif 'off' in name.lower():
            mark = "   <-- priced as off-day overtime, not as an attended day"
        print("      %-44s %-12s %6s%s" % (name[:44], state, count, mark))

    no_attendance = [r for r in here
                     if not any('attendance' in n.lower()
                                for (n, s) in r['entries'] if s != 'cancelled')
                     and r['entries']]
    if no_attendance:
        print("      !! %s employee(s) hold work entries but none of type"
              " Attendance:" % len(no_attendance))
        for row in sorted(no_attendance, key=lambda r: -abs(r['d_days']))[:10]:
            print("          %-40s day gap %s"
                  % ((row['employee'].name or '?')[:40], num(row['d_days'], 8)))

    cancelled = [r for r in here
                 if any(s == 'cancelled' for (_n, s) in r['entries'])]
    if cancelled:
        print("      !! %s employee(s) hold cancelled work entries:"
              % len(cancelled))
        for row in sorted(cancelled, key=lambda r: -abs(r['d_days']))[:10]:
            count = sum(c for (_n, s), c in row['entries'].items()
                        if s == 'cancelled')
            print("          %-40s %3s cancelled   day gap %s"
                  % ((row['employee'].name or '?')[:40], count,
                     num(row['d_days'], 8)))

# ------------------------------------------------------- 3. employee by employee
title("3. employee by employee")
print("  %-32s %8s %8s %8s   %8s %8s   %8s %8s   %11s %11s"
      % ("employee", "days s", "days n", "d days",
         "OTreg s", "OTreg n", "OToff s", "OToff n",
         "d OTreg AED", "d OToff AED"))
print("  " + "-" * (WIDTH - 4))
shown = 0
for row in sorted(rows, key=lambda r: (r['company'].name or '',
                                       -abs(r['d_days']), -abs(r['d_ot_reg']))):
    if (abs(row['d_days']) <= TOL and abs(row['d_ot_reg']) <= 0.5
            and abs(row['d_ot_off']) <= 0.5):
        continue
    print("  %-32s %8.2f %8.2f %8.2f   %8.2f %8.2f   %8.2f %8.2f   %11s %11s"
          % ((row['employee'].name or '?')[:32],
             row['ssc'].total_attendance or 0.0, row['native_days'], row['d_days'],
             row['ssc'].overtime_reg or 0.0, row['ot_hours']['reg'],
             row['ssc'].overtime_off or 0.0, row['ot_hours']['off'],
             num(row['d_ot_reg']), num(row['d_ot_off'])))
    shown += 1
print("")
print("  %s row(s) differ of %s matched" % (shown, len(rows)))

# ------------------------------------------------------------ 4. day by day
title("4. the worst gaps, day by day")
if WANTED:
    deep = [r for r in rows if WANTED in (r['employee'].name or '').lower()]
else:
    deep = sorted(rows, key=lambda r: -abs(r['d_days']))[:DEEP]

for row in deep:
    slip, native = row['ssc'], row['native']
    title("%s   -   %s" % (row['employee'].name or '?',
                           row['company'].name or '-'), '-')
    print("    ssc    days %6.2f   OT reg %6.2f h = %s   OT off %6.2f h = %s"
          % (slip.total_attendance or 0.0, slip.overtime_reg or 0.0,
             num(slip.overtime_reg_amount), slip.overtime_off or 0.0,
             num(slip.overtime_off_amount)))
    print("    native days %6.2f   OT reg %6.2f h = %s   OT off %6.2f h = %s"
          % (row['native_days'], row['ot_hours']['reg'], num(row['nat_ot_reg']),
             row['ot_hours']['off'], num(row['nat_ot_off'])))
    print("    rates  regular %s   off %s"
          % (slip.ot_rate_regular, slip.ot_rate_off))

    entries_by_date = defaultdict(list)
    for entry in WorkEntry.search([('employee_id', '=', row['employee'].id),
                                   ('date', '>=', str(native.date_from)),
                                   ('date', '<=', str(native.date_to))],
                                  order='date'):
        entries_by_date[str(entry.date)].append(entry)

    print("")
    print("    %-12s %-4s %-16s %7s %7s %7s %-5s  %s"
          % ("date", "day", "ssc status", "earned", "hours", "OT", "off",
             "native work entries"))
    print("    " + "-" * (WIDTH - 6))
    for day in slip.day_ids.sorted(lambda d: d.date or ''):
        native_side = entries_by_date.get(str(day.date), [])
        text = ", ".join(
            "%s[%s] %.1fh" % ((e.work_entry_type_id.name or '?')[:22], e.state,
                              e.duration if 'duration' in e._fields else 0.0)
            for e in native_side) or "-"
        print("    %-12s %-4s %-16s %7.2f %7.2f %7.2f %-5s  %s"
              % (day.date, (day.day_name or '')[:4], (day.status or '')[:16],
                 day.day_ratio or 0.0, day.worked_hours or 0.0,
                 day.overtime or 0.0, "yes" if day.is_off_day else "",
                 text[:60]))

title("read only - nothing was written")
