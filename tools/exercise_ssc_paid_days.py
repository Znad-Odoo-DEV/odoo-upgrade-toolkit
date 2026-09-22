"""hr.employee._ssc_paid_days says what the attendance sheet says, for every kind of day.

    odoo-bin shell -d DB < tools/exercise_ssc_paid_days.py

Eleven labourers on one period, 1..25 August 2026, each built to exercise one
rule the company has about a day. A real ssc.attendance.sheet is generated for
them - the engine the office runs every month - and the method is held against
its summary line for each: attended days, advance days, whether the advance
was granted, and the total. Then a handful of absolute figures are asserted as
well, so the test cannot pass by both sides being wrong together.

Rolled back at the end. Nothing survives.
"""
from datetime import date, datetime, timedelta

Employee = env['hr.employee'].sudo()                               # noqa: F821
Attendance = env['hr.attendance'].sudo()                           # noqa: F821
Leave = env['hr.leave'].sudo()                                     # noqa: F821
LeaveType = env['hr.leave.type'].sudo()                            # noqa: F821
Holiday = env['ssc.public.holiday'].sudo()                         # noqa: F821
Sheet = env['ssc.attendance.sheet'].sudo()                         # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-72s %s" % (label, detail))


company = env.company                                              # noqa: F821
company.ssc_weekly_off_day = '4'                                   # Friday
START, LAST = date(2026, 8, 1), date(2026, 8, 25)
FRIDAY = 4

# The working schedule the site actually keeps: six days, one eight-hour
# block, Friday off. Odoo 19 nets the calendar's lunch break out of
# hr.attendance.worked_hours, so on the shipped "Standard 40 hours/week" an
# eight-hour punch is worth seven hours on a weekday and a day earns 0.875 of
# itself - which is a fact about the calendar, not about the engine.
calendar = env['resource.calendar'].sudo().create({                # noqa: F821
    'name': "Site 6 x 8h, Friday off", 'company_id': company.id,
    'tz': 'Asia/Dubai', 'hours_per_day': 8.0,
    'attendance_ids': [(0, 0, {
        'name': "Day", 'dayofweek': str(weekday), 'day_period': 'morning',
        'hour_from': 7.0, 'hour_to': 15.0,
    }) for weekday in (5, 6, 0, 1, 2, 3)],
})


def person(name, joined=date(2026, 1, 1), **values):
    employee = Employee.create(dict({
        'name': name, 'company_id': company.id, 'tz': 'Asia/Dubai',
        'ssc_workforce': 'labour', 'resource_calendar_id': calendar.id,
    }, **values))
    employee.contract_date_start = joined
    return employee


def punch(employee, day, hours=8.0, missing_checkout=False):
    # 07:00 Dubai is 03:00 UTC
    check_in = datetime(day.year, day.month, day.day, 3, 0)
    check_out = check_in if missing_checkout else check_in + timedelta(hours=hours)
    Attendance.create({'employee_id': employee.id,
                       'check_in': check_in, 'check_out': check_out})


def workdays(first=START, last=LAST, skip=()):
    day = first
    while day <= last:
        if day.weekday() != FRIDAY and day not in skip:
            yield day
        day += timedelta(days=1)


def full_month(employee, skip=(), first=START):
    for day in workdays(first=first, skip=skip):
        punch(employee, day)


def approved_leave(employee, type_name, first, last):
    leave_type = LeaveType.with_context(lang='en_US').search(
        [('name', '=', type_name)], limit=1)
    assert leave_type, "no leave type named %r on this database" % type_name
    leave = Leave.with_context(leave_skip_state_check=True).create({
        'employee_id': employee.id, 'holiday_status_id': leave_type.id,
        'request_date_from': first, 'request_date_to': last,
    })
    try:
        leave.action_approve()
    except Exception:                                              # noqa: BLE001
        pass
    if leave.state != 'validate':
        leave.write({'state': 'validate'})
    return leave


# --- the eleven --------------------------------------------------------------
people = {}

people['full'] = person("Full month")
full_month(people['full'])

people['missing checkout'] = person("Missing check-out on the 3rd")
full_month(people['missing checkout'], skip=(date(2026, 8, 3),))
punch(people['missing checkout'], date(2026, 8, 3), missing_checkout=True)

people['half day'] = person("Four hours on the 5th")
full_month(people['half day'], skip=(date(2026, 8, 5),))
punch(people['half day'], date(2026, 8, 5), hours=4.0)

people['stranded friday'] = person("Away Thursday 6th and Saturday 8th")
full_month(people['stranded friday'], skip=(date(2026, 8, 6), date(2026, 8, 8)))

people['no punches'] = person("Never punched")

people['joiner'] = person("Joined on the 20th", joined=date(2026, 8, 20))
full_month(people['joiner'], first=date(2026, 8, 20))

Holiday.create({'name': "Test Holiday", 'date': date(2026, 8, 10),
                'company_id': company.id})
people['holiday penalty'] = person("Absent the Sunday before the holiday")
full_month(people['holiday penalty'], skip=(date(2026, 8, 9), date(2026, 8, 10)))

people['sick'] = person("Sick on the 11th and 12th")
full_month(people['sick'], skip=(date(2026, 8, 11), date(2026, 8, 12)))
approved_leave(people['sick'], 'Sick Time Off', date(2026, 8, 11), date(2026, 8, 12))

people['neutral leave'] = person("Unpaid leave on the 13th")
full_month(people['neutral leave'], skip=(date(2026, 8, 13),))
approved_leave(people['neutral leave'], 'Unpaid', date(2026, 8, 13), date(2026, 8, 13))

people['on leave today'] = person("Full month, on leave today")
full_month(people['on leave today'])
today = date.today()
approved_leave(people['on leave today'], 'Unpaid', today, today)

people['leaving'] = person("Full month, departure date set")
full_month(people['leaving'])
people['leaving'].departure_date = date(2026, 9, 30)

# --- the sheet the office would generate ----------------------------------
sheet = Sheet.create({'company_id': company.id, 'start_date': START, 'last_date': LAST})
sheet.action_generate()
summaries = {s.employee_id.id: s for s in sheet.summary_ids}
check("the sheet lists all eleven", all(p.id in summaries for p in people.values()),
      "%s of %s" % (sum(1 for p in people.values() if p.id in summaries), len(people)))

# --- method against sheet, person by person -------------------------------
for label, employee in people.items():
    summary = summaries.get(employee.id)
    figures = employee._ssc_paid_days(START, LAST)
    if summary is None:
        check("%s: on the sheet" % label, False, "missing")
        continue
    same = (abs(figures['attended'] - summary.attended_days) < 0.005
            and figures['advance_days'] == summary.advance_days
            and figures['advance_granted'] == summary.advance_granted
            and abs(figures['total_days'] - summary.total_att_days) < 0.005
            and figures['period_days'] == summary.period_days)
    check("%s: method == sheet" % label, same,
          "attended %.2f/%.2f  advance %s/%s granted %s/%s  total %.2f/%.2f" % (
              figures['attended'], summary.attended_days,
              figures['advance_days'], summary.advance_days,
              figures['advance_granted'], summary.advance_granted,
              figures['total_days'], summary.total_att_days))

# --- and the figures themselves, so the two cannot be wrong together ------
f = {label: employee._ssc_paid_days(START, LAST) for label, employee in people.items()}
check("full month: 25 attended, 6 advanced, 31 in all, ratio 1",
      f['full']['attended'] == 25 and f['full']['advance_days'] == 6
      and f['full']['advance_granted'] and f['full']['total_days'] == 31
      and f['full']['ratio'] == 1.0, "%(attended)s + %(advance_days)s = %(total_days)s" % f['full'])
check("missing check-out: the day earns nothing - 24 attended, 30 in all",
      f['missing checkout']['attended'] == 24 and f['missing checkout']['total_days'] == 30,
      f['missing checkout']['total_days'])
check("half day: 24.5 attended", abs(f['half day']['attended'] - 24.5) < 0.005,
      f['half day']['attended'])
check("stranded Friday: Thursday, Friday and Saturday all lost - 22",
      f['stranded friday']['attended'] == 22, f['stranded friday']['attended'])
check("never punched: nothing, and no advance either",
      f['no punches']['total_days'] == 0 and not f['no punches']['advance_granted'],
      f['no punches']['total_days'])
check("joiner on the 20th: 6 days of period, 6 advanced, 12 in all",
      f['joiner']['period_days'] == 6 and f['joiner']['attended'] == 6
      and f['joiner']['advance_days'] == 6 and f['joiner']['total_days'] == 12,
      "%(period_days)s/%(attended)s/%(advance_days)s/%(total_days)s" % f['joiner'])
check("holiday penalty: the Sunday and the holiday both lost - 23",
      f['holiday penalty']['attended'] == 23 and f['holiday penalty']['penalty'] == 1,
      "%(attended)s penalty %(penalty)s" % f['holiday penalty'])
check("sick: two days out of the base and not absence - 23 attended, absence 0",
      f['sick']['attended'] == 23 and f['sick']['absence'] == 0 and f['sick']['sick'] == 2,
      "%(attended)s sick %(sick)s absence %(absence)s" % f['sick'])
check("neutral leave: neither earned nor absent - 24 attended, absence 0",
      f['neutral leave']['attended'] == 24 and f['neutral leave']['absence'] == 0,
      "%(attended)s absence %(absence)s" % f['neutral leave'])
check("on leave today: full attendance, advance withheld - 25 in all",
      f['on leave today']['attended'] == 25 and not f['on leave today']['advance_granted']
      and f['on leave today']['total_days'] == 25, f['on leave today']['total_days'])
check("leaving: advance withheld too", not f['leaving']['advance_granted']
      and f['leaving']['total_days'] == 25, f['leaving']['total_days'])
check("ratio is total over the days in the month, capped at one",
      abs(f['missing checkout']['ratio'] - 30 / 31) < 1e-9 and f['full']['ratio'] == 1.0,
      "%.6f" % f['missing checkout']['ratio'])

# --- a whole-month period advances nothing --------------------------------
whole = people['full']._ssc_paid_days(date(2026, 8, 1), date(2026, 8, 31))
check("a period running to month end has no advance days",
      whole['advance_days'] == 0, whole['advance_days'])

print()
print("PASS  %s" % len(ok))
for row in ok:
    print("   ok   %s" % row)
if bad:
    print()
    print("FAIL  %s" % len(bad))
    for row in bad:
        print("   XX   %s" % row)
else:
    print()
    print("nothing failed")

env.cr.rollback()                                                  # noqa: F821
print("rolled back")
