"""Generate One Payslip pays what the monthly sheet would have paid the same person.

    odoo-bin shell -d DB < tools/exercise_generate_one_payslip.py

Two labourers with identical contracts and identical punches over 1..25
August 2026, a missing check-out and an absent day among them. One is paid
through a monthly sheet the ordinary way; the other through the wizard with
the same period and the same switches. Every money figure on the two payslips
must be equal - the wizard has no arithmetic of its own to disagree with.

Then the things only the wizard does: the sheet lists that one employee, the
payslip says the chosen period, a second unpaid payslip for the month is
refused, office staff are refused, and a period over two months is refused.

Rolled back at the end.
"""
from datetime import date, datetime, timedelta

from odoo.exceptions import UserError

Employee = env['hr.employee'].sudo()                               # noqa: F821
Attendance = env['hr.attendance'].sudo()                           # noqa: F821
Sheet = env['ssc.attendance.sheet'].sudo()                         # noqa: F821
Wizard = env['ssc.payslip.generate.wizard'].sudo()                 # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-70s %s" % (label, detail))


company = env.company                                              # noqa: F821
company.ssc_weekly_off_day = '4'
START, LAST = date(2026, 8, 1), date(2026, 8, 25)

calendar = env['resource.calendar'].sudo().create({                # noqa: F821
    'name': "Site 6 x 8h, Friday off", 'company_id': company.id,
    'tz': 'Asia/Dubai', 'hours_per_day': 8.0,
    'attendance_ids': [(0, 0, {
        'name': "Day", 'dayofweek': str(weekday), 'day_period': 'morning',
        'hour_from': 7.0, 'hour_to': 15.0,
    }) for weekday in (5, 6, 0, 1, 2, 3)],
})


def person(name, workforce='labour'):
    employee = Employee.create({
        'name': name, 'company_id': company.id, 'tz': 'Asia/Dubai',
        'ssc_workforce': workforce, 'resource_calendar_id': calendar.id,
        'wage': 1200.0,
    })
    employee.contract_date_start = date(2026, 1, 1)
    employee.l10n_ae_other_allowances = 300.0
    day = START
    while day <= LAST:
        if day.weekday() != 4 and day != date(2026, 8, 12):        # absent the 12th
            check_in = datetime(day.year, day.month, day.day, 3, 0)
            closed = day != date(2026, 8, 5)                       # no check-out the 5th
            Attendance.create({
                'employee_id': employee.id, 'check_in': check_in,
                'check_out': check_in + timedelta(hours=8) if closed else check_in})
        day += timedelta(days=1)
    return employee


monthly_man = person("One payslip test: monthly")
wizard_man = person("One payslip test: wizard")

# --- the ordinary way -------------------------------------------------------
sheet = Sheet.create({'company_id': company.id, 'start_date': START, 'last_date': LAST,
                      'no_advance_days': True,
                      'only_employee_ids': [(6, 0, [monthly_man.id])]})
# only_employee_ids here just keeps the scratch database's other employees off
# the comparison; the engine under it is the one every monthly sheet runs.
sheet.action_generate()
sheet.action_submit()
sheet.action_approve()
sheet.action_generate_payroll()
monthly = sheet.payslip_ids
check("the monthly sheet made a payslip", len(monthly) == 1, monthly.display_name)

# --- the wizard -------------------------------------------------------------
wizard = Wizard.create({'employee_id': wizard_man.id, 'date_from': START, 'date_to': LAST})
action = wizard.action_generate()
check("the wizard opens the payslip it made", action.get('res_model') == 'ssc.payslip',
      action.get('res_model'))
single = env['ssc.payslip'].sudo().browse(action.get('res_id'))    # noqa: F821

for field in ('total_attendance', 'gross_salary', 'rate_per_day', 'total_salary',
              'overtime_salary', 'salary_adjustment', 'net_amount', 'days'):
    check("%s is what the monthly sheet paid" % field,
          abs((single[field] or 0) - (monthly[field] or 0)) < 0.005,
          "%s / %s" % (single[field], monthly[field]))
check("23 days: 25 less the absent 12th and the unclosed 5th",
      abs(single.total_attendance - 23.0) < 0.005, single.total_attendance)
check("priced at 1,500 over 31 days", abs(single.total_salary - 1500.0 / 31 * 23) < 0.2,
      single.total_salary)

# --- what only the wizard does ----------------------------------------------
own_sheet = single.attendance_sheet_id
check("its sheet lists that one employee and nobody else",
      own_sheet.summary_ids.mapped('employee_id') == wizard_man,
      "%s line(s)" % len(own_sheet.summary_ids))
check("and says whose it is", wizard_man.name in (own_sheet.name or ''), own_sheet.name)
check("the payslip carries the chosen period",
      single.from_date == START and single.to_date == LAST,
      "%s .. %s" % (single.from_date, single.to_date))
check("the sheet is approved, like any sheet with a payslip", own_sheet.state == 'approved',
      own_sheet.state)


def refused(values, label):
    try:
        with env.cr.savepoint():                                   # noqa: F821
            Wizard.create(values).action_generate()
        check(label, False, "NOT refused")
    except UserError as error:
        check(label, True, str(error)[:60])


refused({'employee_id': wizard_man.id, 'date_from': START, 'date_to': LAST},
        "a second unpaid payslip for the same month is refused")
# --- office staff: the same button, the staff sheet underneath ---------------
office = person("One payslip test: office", 'office_staff')
action = Wizard.create({'employee_id': office.id, 'date_from': START,
                        'date_to': LAST}).action_generate()
check("office staff get a payslip too", action.get('res_model') == 'ssc.payslip',
      action.get('res_model'))
staff_slip = env['ssc.payslip'].sudo().browse(action.get('res_id'))   # noqa: F821
staff_sheet = staff_slip.staff_attendance_id
check("made by the staff sheet, not the labour one",
      bool(staff_sheet) and not staff_slip.attendance_sheet_id and staff_slip.is_staff,
      staff_sheet.name)
check("which lists that one employee", staff_sheet.line_ids.mapped('employee_id') == office,
      "%s line(s)" % len(staff_sheet.line_ids))
check("the staff payslip carries the chosen period",
      staff_slip.from_date == START and staff_slip.to_date == LAST,
      "%s .. %s" % (staff_slip.from_date, staff_slip.to_date))
check("pays the 25 days of the period and no advance",
      staff_slip.total_attendance == 25 and staff_sheet.line_ids.advance_days == 0,
      staff_slip.total_attendance)
check("at the gross over the 31 days of the month",
      abs(staff_slip.total_salary - 1500.0 / 31 * 25) < 0.2, staff_slip.total_salary)
check("and settles no previous period it was not given",
      staff_sheet.line_ids.last_month_absence == 0 and not staff_slip.attachment_ids,
      "no last-month deduction")
refused({'employee_id': monthly_man.id, 'date_from': date(2026, 7, 20),
         'date_to': date(2026, 8, 10)}, "a period over two months is refused")

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
