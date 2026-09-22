"""Which calendar each employee actually works to, by id and by weekday.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_working_calendars.py

Kamlesh Ramkaran's August, day by day:

    2026-08-01 Sat  ssc Present 8.09h   native  SSC Overtime - Off Day  9.1h
    2026-08-02 Sun  ssc Present 8.05h   native  SSC Overtime - Off Day  9.0h
    2026-08-07 Fri  ssc Off Day 0.00h   native  (no entry at all)

Every working day is typed as off-day overtime and the actual weekly off day
has no entry. That is an inverted working schedule, not a payroll fault, and
neither ssc_attendance nor ssc_payroll assigns work_entry_type_id anywhere -
grep finds nothing. Odoo's own attendance classifier does it, from the version's
resource_calendar_id: hours on a working day become Attendance, hours on a
non-working day become off-day overtime.

probe_work_entry_blockers.py reported "Standard 48 hours/week" for all three,
which is why this exists. Twice today something has been the right NAME and the
wrong RECORD - input types matched by code, rules checked for a filled field
rather than its contents. A calendar name proves nothing about which days it
calls working.

WHAT IT PRINTS

  every resource.calendar with its id, hours per week, timezone, two-week flag,
  and the weekdays it actually defines attendance for;
  how many employees sit on each, per company;
  and for the named employees, the calendar on their version against the
  calendar on their employee record and on their resource - three fields that
  can disagree - with the weekday of every August day they worked marked
  against whether that calendar calls it a working day.

Read-only.
"""
import os
from collections import defaultdict

WIDTH = 116
NAMES = [n.strip().lower() for n in (os.environ.get('SSC_EMPLOYEE') or
         'Kamlesh Ramkaran,Parfait Uwanshuti,Ahmad Ali Sameu,Ram Lochan'
         ).split(',') if n.strip()]
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday',
        'Sunday']

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


Calendar = env['resource.calendar'].sudo()
Employee = env['hr.employee'].sudo()
Version = env['hr.version'].sudo()

# ------------------------------------------------------------ 1. the calendars
title("1. every working schedule, by id")
for calendar in Calendar.search([]):
    weekdays = defaultdict(float)
    for line in calendar.attendance_ids:
        weekdays[int(line.dayofweek)] += (line.hour_to or 0) - (line.hour_from or 0)
    print("")
    print("  [%s] %-40s  %s h/week  tz=%s  active=%s"
          % (calendar.id, (calendar.name or '?')[:40], calendar.hours_per_day,
             calendar.tz, calendar.active))
    if 'two_weeks_calendar' in calendar._fields and calendar.two_weeks_calendar:
        print("       two-week calendar")
    if not weekdays:
        print("       !! no attendance lines - EVERY day is a non-working day,")
        print("          so every punch becomes off-day overtime")
        continue
    parts = []
    for day in range(7):
        if day not in weekdays:
            continue
        hours = weekdays[day]
        parts.append("%s %s" % (DAYS[day][:3],
                                "-" if hours <= 0 else "%.1fh" % hours))
    print("       %s" % "  ".join(parts))
    missing = [DAYS[d][:3] for d in range(7) if d not in weekdays]
    if missing:
        print("       not a working day: %s" % ", ".join(missing))

# -------------------------------------------------- 2. who sits on which one
title("2. how many employees on each calendar, per company")
counts = defaultdict(lambda: defaultdict(int))
for employee in Employee.search([]):
    version = employee.sudo().version_id
    calendar = version.resource_calendar_id
    counts[employee.company_id.name or '?'][
        (calendar.id if calendar else 0,
         calendar.name if calendar else '(none)')] += 1
for company, per_calendar in sorted(counts.items()):
    print("")
    print("  %s" % company)
    for (calendar_id, name), count in sorted(per_calendar.items(),
                                             key=lambda kv: -kv[1]):
        print("      [%s] %-46s %s employee(s)" % (calendar_id, name[:46], count))

# ------------------------------------------------- 3. the employees in question
title("3. the calendar on the version, the employee and the resource")
for wanted in NAMES:
    found = Employee.search([]).filtered(
        lambda e: wanted in (e.name or '').lower())
    if not found:
        print("  no employee matching %r" % wanted)
        continue
    employee = found[0]
    version = employee.sudo().version_id
    print("")
    print("  %s   -   %s" % (employee.name or '?', employee.company_id.name or '-'))
    for label, record in (
            ("version.resource_calendar_id", version.resource_calendar_id),
            ("employee.resource_calendar_id",
             employee.resource_calendar_id
             if 'resource_calendar_id' in employee._fields else None),
            ("resource_id.calendar_id",
             employee.resource_id.calendar_id
             if employee.resource_id and 'calendar_id' in employee.resource_id._fields
             else None)):
        if record is None:
            print("      %-32s (no such field)" % label)
        elif not record:
            print("      %-32s EMPTY" % label)
        else:
            print("      %-32s [%s] %s" % (label, record.id, record.name or '?'))

    calendar = version.resource_calendar_id
    if not calendar:
        print("      no calendar on the version - nothing classifies as work")
        continue
    working = {int(line.dayofweek) for line in calendar.attendance_ids}
    print("      calendar [%s] calls these working days: %s"
          % (calendar.id,
             ", ".join(DAYS[d][:3] for d in sorted(working)) or "NONE"))
    print("      the weekly off day on the company is %s"
          % (employee.company_id.ssc_weekly_off_day
             if 'ssc_weekly_off_day' in employee.company_id._fields else '?'))

env.cr.rollback()
title("read only - nothing was written")
