"""Rebuild the attendance overtime lines the cleared contract dates invalidated.

    cd ~/src/user

    # report only:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/rebuild_overtime_lines.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/rebuild_overtime_lines.py

Kamlesh, Parfait and Ahmad Ali Sameu hold work entries for every August day
they worked, all typed "SSC Overtime - Off Days", with the real Friday empty.
The calendar was the obvious suspect and it is innocent: every employee in all
four companies sits on calendar [9], Mon-Thu plus Sat-Sun working with Friday
off, which matches the company's own weekly off day. Ram Lochan is on the same
calendar and his entries are ordinary Attendance.

The cause is one this project has already met and written down:

    A rule with expected_hours_from_contract = True reads the expected hours
    from the contract running on that day. With a contract_date_end in the
    past, expected resolves to zero and the whole worked day becomes overtime.

Those three carried a past contract_date_end until it was cleared this morning.
Clearing it was necessary and it is not sufficient: hr.attendance.overtime.line
rows are not recomputed by anything that reads them. Recomputing the field
re-sums the same stale rows, and generate_work_entries - with or without force
- rebuilds the entries from that same stale classification, which is why fifty
four rebuilds changed nothing at all. Only _update_overtime deletes and rebuilds
the lines.

WHAT IT DOES

  For each employee in scope, rebuilds the overtime lines over the pay period
  with _update_overtime, then regenerates the work entries with force=True, then
  recomputes the draft payslip - in that order, because each step reads what the
  one before it produced. Overtime hours and payslip days are printed before
  against after.

  In chunks, committing per chunk, as the note that recorded this says: it
  touches every attendance row of every employee in scope and a single
  transaction over hundreds of them is a long lock on a live database.

SCOPE

  By default, employees with an August labour payslip in Saud or Royal Arrow
  whose work entries include off-day overtime, or whose day count disagrees
  with ssc by more than SSC_TOLERANCE. SSC_EMPLOYEE narrows it to one person.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

from dateutil.relativedelta import relativedelta

WIDTH = 118
APPLY = os.environ.get('SSC_APPLY') == '1'
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
TOL = float(os.environ.get('SSC_TOLERANCE') or 0.5)
CHUNK = int(os.environ.get('SSC_CHUNK') or 25)
WANTED = (os.environ.get('SSC_EMPLOYEE') or '').strip().lower()
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or 'SAUD,ROYAL ARROW').split(',')
        if n.strip()]

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


def num(value, width=10):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


NativeSlip = env['hr.payslip'].sudo()
SscSlip = env['ssc.payslip'].sudo()
Attendance = env['hr.attendance'].sudo()
WorkEntry = env['hr.work.entry'].sudo()


def days_in_month_of(value):
    first = value.replace(day=1)
    return ((first + relativedelta(months=1)) - first).days


def native_day_count(slip, employee):
    basic = sum(l.total for l in slip.line_ids if l.code == 'BASIC')
    wage = employee.sudo().version_id.wage or 0.0
    month_days = days_in_month_of(slip.date_to) if slip.date_to else 0
    return (basic / wage * month_days) if wage else 0.0


rows = []
for slip in SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR)),
                            ('is_staff', '=', False)]):
    employee = slip.employee_id.hr_employee_id
    if not employee:
        continue
    if ONLY and not any(p in (employee.company_id.name or '').upper()
                        for p in ONLY):
        continue
    if WANTED and WANTED not in (employee.name or '').lower():
        continue
    native = NativeSlip.search([('employee_id', '=', employee.id)]).filtered(
        lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
        and str(s.date_from.year) == str(YEAR)
        and (s.struct_id.name or '').endswith('Labour Pay'))
    if not native:
        continue
    native = native[0]

    entries = defaultdict(int)
    for entry in WorkEntry.search([('employee_id', '=', employee.id),
                                   ('date', '>=', str(native.date_from)),
                                   ('date', '<=', str(native.date_to)),
                                   ('state', '!=', 'cancelled')]):
        entries[entry.work_entry_type_id.name or '?'] += 1
    off_day = sum(count for name, count in entries.items()
                  if 'off' in name.lower())
    attendance_entries = sum(count for name, count in entries.items()
                             if 'attendance' in name.lower())

    days_native = native_day_count(native, employee)
    gap = (slip.total_attendance or 0.0) - days_native
    if not (off_day or abs(gap) > TOL or WANTED):
        continue

    punches = Attendance.search([('employee_id', '=', employee.id),
                                 ('check_in', '>=', str(native.date_from) + ' 00:00:00'),
                                 ('check_in', '<=', str(native.date_to) + ' 23:59:59')])
    rows.append({
        'employee': employee, 'native': native, 'ssc': slip,
        'days_native': days_native, 'gap': gap, 'punches': punches,
        'overtime': sum(punches.mapped('overtime_hours'))
        if 'overtime_hours' in Attendance._fields else 0.0,
        'off_day': off_day, 'attendance_entries': attendance_entries,
        'contract_end': employee.sudo().version_id.contract_date_end,
    })

rows.sort(key=lambda r: (-r['off_day'], -abs(r['gap'])))

title("employees whose overtime lines look stale")
print("  %s in scope" % len(rows))
print("")
print("  %-36s %8s %8s %8s %9s %9s %8s %s"
      % ("employee", "days ssc", "days nat", "gap", "OT hours",
         "off-day WE", "attnd WE", "contract end"))
print("  " + "-" * (WIDTH - 4))
for row in rows:
    print("  %-36s %8.2f %8.2f %8.2f %9.2f %9s %8s %s"
          % ((row['employee'].name or '?')[:36],
             row['ssc'].total_attendance or 0.0, row['days_native'], row['gap'],
             row['overtime'], row['off_day'], row['attendance_entries'],
             row['contract_end'] or 'open'))

worst = [r for r in rows if r['off_day'] and not r['attendance_entries']]
title("summary")
print("  %s employee(s) in scope, %s of them hold off-day overtime entries and"
      " no attendance entry at all" % (len(rows), len(worst)))
for row in worst:
    print("      %-40s %s punch(es), %s OT hours"
          % ((row['employee'].name or '?')[:40], len(row['punches']),
             num(row['overtime'])))

if not APPLY:
    env.cr.rollback()
    print("")
    print("  report only - nothing written. Re-run with SSC_APPLY=1.")
else:
    done = 0
    failures = []
    for start in range(0, len(rows), CHUNK):
        chunk = rows[start:start + CHUNK]
        for row in chunk:
            employee, native = row['employee'], row['native']
            before_ot, before_days = row['overtime'], row['days_native']
            before_net = sum(l.total for l in native.line_ids if l.code == 'NET')
            try:
                domain = [('employee_id', '=', employee.id),
                          ('check_in', '>=', str(native.date_from) + ' 00:00:00'),
                          ('check_in', '<=', str(native.date_to) + ' 23:59:59')]
                punches = Attendance.search(domain)
                # Order matters: the overtime lines feed the work entries, and
                # the work entries feed the payslip.
                if punches:
                    punches._update_overtime(domain)
                version = employee.sudo().version_id
                version.generate_work_entries(native.date_from, native.date_to,
                                              force=True)
                if native.state == 'draft':
                    native.with_context(active_test=True).compute_sheet()
                done += 1
                after_ot = sum(Attendance.search(domain).mapped('overtime_hours'))
                print("  %-36s OT %s -> %s   days %6.2f -> %6.2f   net %s -> %s"
                      % ((employee.name or '?')[:36], num(before_ot, 9),
                         num(after_ot, 9), before_days,
                         native_day_count(native, employee), num(before_net),
                         num(sum(l.total for l in native.line_ids
                                 if l.code == 'NET'))))
            except Exception as error:  # noqa: BLE001
                failures.append((employee.name or '?',
                                 str(error).strip().splitlines()[0]))
        env.cr.commit()
        print("  -- committed %s of %s --" % (min(start + CHUNK, len(rows)),
                                              len(rows)))

    title("done")
    print("  %s employee(s) rebuilt" % done)
    if failures:
        print("  %s refused:" % len(failures))
        for name, reason in failures:
            print("    %-40s %s" % (name[:40], reason[:60]))
    print("")
    print("  Re-run compare_days_overtime.py - the off-day overtime column is")
    print("  the one that should collapse.")
