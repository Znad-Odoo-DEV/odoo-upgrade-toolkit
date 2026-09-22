"""Why the two payrolls disagree about what an hour of overtime is.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_overtime_definition.py

    SSC_EMPLOYEE="Rageev Ahamad" ...    # one person, day by day

The disagreement is systematic and it runs in opposite directions, which means
a difference of definition and not an arithmetic fault:

    overtime regular, hours   ssc 5,727.23   native 5,444.11   ssc  higher 283
    overtime off-day, hours   ssc   831.87   native 1,453.26   nat  higher 621

Rageev Ahamad shows it on one payslip: 3.02 hours of regular overtime on the
ssc side against 0.63 on Odoo's.

Two candidates, both from figures already seen today, and neither yet checked:

  the length of a day.  ssc_attendance_sheet.py sets STANDARD_WORK_HOURS = 8.0
      and treats anything past it as overtime. Calendar [9] defines nine hours
      against each working weekday while carrying hours_per_day = 8.0. If Odoo
      prices overtime past nine and ssc past eight, every day between the two
      is overtime on one side only - and ssc would report more regular
      overtime, which it does.

  the length of an entry.  Kamlesh Ramkaran's days read 8.09 hours on the ssc
      side and 9.1 on the work entry - an hour more, every day. A break counted
      by one and deducted by the other would do that, and it would push native's
      off-day overtime up, which it is.

So this reads the definitions rather than inferring them: the calendar's own
attendance lines hour by hour, the overtime ruleset on the version with every
rule in it - threshold, rate, and the work entry type each one produces - and
then one employee day by day with ssc's worked hours and overtime beside the
native work entries and their durations.

Read-only.
"""
import os
from collections import defaultdict

WIDTH = 124
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
WANTED = (os.environ.get('SSC_EMPLOYEE') or 'Rageev Ahamad').strip().lower()
DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


def clock(value):
    hours = int(value or 0)
    return "%02d:%02d" % (hours, round(((value or 0) - hours) * 60))


Employee = env['hr.employee'].sudo()
Calendar = env['resource.calendar'].sudo()
WorkEntry = env['hr.work.entry'].sudo()
Attendance = env['hr.attendance'].sudo()
SscSlip = env.get('ssc.payslip')

found = Employee.search([]).filtered(lambda e: WANTED in (e.name or '').lower())
if not found:
    print("no employee matching %r" % WANTED)
    raise SystemExit
employee = found[0]
version = employee.sudo().version_id

title("%s   -   %s" % (employee.name or '?', employee.company_id.name or '-'))

# ------------------------------------------------------------ 1. the calendar
title("1. the working schedule, hour by hour", '-')
calendar = version.resource_calendar_id
if not calendar:
    print("  no calendar on the version")
else:
    print("  [%s] %s   hours_per_day=%s   tz=%s"
          % (calendar.id, calendar.name or '?', calendar.hours_per_day,
             calendar.tz))
    per_day = defaultdict(list)
    for line in calendar.attendance_ids:
        per_day[int(line.dayofweek)].append(line)
    total = 0.0
    for day in range(7):
        lines = per_day.get(day)
        if not lines:
            print("      %-4s  not a working day" % DAYS[day])
            continue
        spans, hours = [], 0.0
        for line in sorted(lines, key=lambda l: l.hour_from):
            spans.append("%s-%s" % (clock(line.hour_from), clock(line.hour_to)))
            hours += (line.hour_to or 0) - (line.hour_from or 0)
        total += hours
        print("      %-4s  %-28s %5.2f h" % (DAYS[day], ", ".join(spans), hours))
    print("      %-4s  %-28s %5.2f h" % ("", "week", total))
    print("")
    print("      the schedule says %.2f h a day; hours_per_day says %s"
          % (total / max(1, len(per_day)), calendar.hours_per_day))
    print("      ssc_attendance_sheet.py uses STANDARD_WORK_HOURS = 8.0")

# ------------------------------------------------------- 2. the overtime rules
title("2. the overtime ruleset on the version", '-')
ruleset = version.ruleset_id if 'ruleset_id' in version._fields else None
if not ruleset:
    print("  no ruleset_id on the version - nothing rule-driven to read")
else:
    print("  [%s] %s" % (ruleset.id, ruleset.name or '?'))
    rules = ruleset.rule_ids if 'rule_ids' in ruleset._fields else []
    if not rules:
        print("      no rules on it")
    for rule in rules:
        print("")
        print("      [%s] %s" % (rule.id, rule.name or '?'))
        for field in sorted(rule._fields):
            if field in ('id', 'display_name', 'create_uid', 'create_date',
                         'write_uid', 'write_date', '__last_update'):
                continue
            try:
                value = rule[field]
            except Exception:  # noqa: BLE001
                continue
            if value in (False, None, 0, 0.0, '', []):
                continue
            if hasattr(value, '_name'):
                value = getattr(value, 'display_name', value)
            print("          %-32s %s" % (field, value))

# ------------------------------------------------------------- 3. day by day
title("3. the same days, both sides", '-')
slips = SscSlip.sudo().search([('month', '=', MONTH), ('year', '=', str(YEAR))]) \
    if SscSlip is not None else []
ssc_slip = next((s for s in slips
                 if s.employee_id.hr_employee_id.id == employee.id), None)
if not ssc_slip:
    print("  no ssc payslip for %s-%s" % (MONTH, YEAR))
else:
    print("  ssc  rate/day %s   OT rate regular %s   OT rate off %s"
          % (ssc_slip.rate_per_day, ssc_slip.ot_rate_regular,
             ssc_slip.ot_rate_off))
    print("  ssc  OT regular %s h   OT off-day %s h"
          % (ssc_slip.overtime_reg, ssc_slip.overtime_off))

    entries = defaultdict(list)
    for entry in WorkEntry.search([('employee_id', '=', employee.id),
                                   ('state', '!=', 'cancelled')], order='date'):
        entries[str(entry.date)].append(entry)

    print("")
    print("  %-12s %-4s %-10s %8s %8s %6s   %s"
          % ("date", "day", "ssc status", "worked", "ssc OT", "off",
             "native entries (type, hours)"))
    print("  " + "-" * (WIDTH - 4))
    ssc_worked = ssc_ot = native_hours = 0.0
    for day in ssc_slip.day_ids.sorted(lambda d: d.date or ''):
        rows = entries.get(str(day.date), [])
        text = ", ".join(
            "%s %.2f" % ((e.work_entry_type_id.name or '?')[:26],
                         e.duration if 'duration' in e._fields else 0.0)
            for e in rows) or "-"
        ssc_worked += day.worked_hours or 0.0
        ssc_ot += day.overtime or 0.0
        native_hours += sum(e.duration if 'duration' in e._fields else 0.0
                            for e in rows)
        print("  %-12s %-4s %-10s %8.2f %8.2f %6s   %s"
              % (day.date, (day.day_name or '')[:4], (day.status or '')[:10],
                 day.worked_hours or 0.0, day.overtime or 0.0,
                 "yes" if day.is_off_day else "", text[:58]))
    print("  " + "-" * (WIDTH - 4))
    print("  %-28s ssc worked %.2f h   ssc OT %.2f h   native entries %.2f h"
          % ("totals", ssc_worked, ssc_ot, native_hours))
    print("")
    print("  native hours minus ssc worked hours = %.2f" % (native_hours - ssc_worked))
    print("  if that is about one hour per attended day, it is a break that one")
    print("  side counts and the other deducts.")

env.cr.rollback()
title("read only - nothing was written")
