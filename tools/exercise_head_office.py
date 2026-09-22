"""Head office is the Workforce field, and the day's four counts are four facts.

    odoo-bin shell -d DB < tools/exercise_head_office.py

Six employees on one day, chosen so that every pair the old rule and the new
rule disagree on is present:

  an office engineer with a badge who punched      old: not head office
  an office engineer with a badge who did not      old: not head office, absent
  an office engineer with no badge                 both: head office
  a labourer with a badge who punched              both: not head office
  a labourer with a badge who did not              both: absent
  a labourer with NO badge                         old: HEAD OFFICE  new: not

The last one is the whole reason: a man on site before his badge is registered
went into the head office count, and that count is read by payroll.
"""
from datetime import date, datetime

Employee = env['hr.employee']                                     # noqa: F821
Day = env['ssc.attendance']                                       # noqa: F821
Line = env['ssc.attendance.line']                                 # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-66s %s" % (label, detail))


def person(name, workforce):
    return Employee.create({'name': name, 'ssc_workforce': workforce})


when = date(2026, 9, 9)
day = Day.create({'name': str(when), 'date': when} if 'name' in Day._fields
                 else {'date': when})

cases = [
    # label, workforce, badge, punched
    ("office, badge, punched", 'office_staff', 'HO1', True),
    ("office, badge, no punch", 'office_staff', 'HO2', False),
    ("office, no badge", 'office_staff', False, False),
    ("labour, badge, punched", 'labour', 'LB1', True),
    ("labour, badge, no punch", 'labour', 'LB2', False),
    ("labour, NO badge", 'labour', False, False),
]
# Creating the day populates a line for every employee already on the
# database, and a scratch database has at least an Administrator. Those are
# not part of the experiment: the counts below are about six known people.
mine = Employee
lines = {}
for label, workforce, badge, punched in cases:
    employee = person(label, workforce)
    values = {
        'external_id': day.id, 'employee_id': employee.id,
        'hr_employee_id': employee.id, 'date': when,
        'attendance_id': badge or False,
    }
    if punched:
        values['first_punch'] = datetime(2026, 9, 9, 6, 40)
        values['last_punch'] = datetime(2026, 9, 9, 16, 5)
    lines[label] = Line.create(values)
    mine |= employee
day.line_ids.filtered(lambda l: l.employee_id not in mine).unlink()

# --- head office is the workforce, nothing else -------------------------------
for label in ("office, badge, punched", "office, badge, no punch", "office, no badge"):
    check("%s -> head office" % label, lines[label].head_office_staff, "yes")
for label in ("labour, badge, punched", "labour, badge, no punch", "labour, NO badge"):
    check("%s -> NOT head office" % label, not lines[label].head_office_staff, "no")

# --- and it follows the employee when the employee changes -------------------
moved = lines["labour, badge, punched"]
moved.employee_id.ssc_workforce = 'office_staff'
check("reclassifying the employee reclassifies his lines",
      moved.head_office_staff, "labour -> office, line followed")
moved.employee_id.ssc_workforce = 'labour'
check("and back", not moved.head_office_staff, "office -> labour, line followed")

# --- absence is untouched by any of this -------------------------------------
check("an office engineer with a badge who did not punch is still absent",
      lines["office, badge, no punch"].absent, "absent - the rule did not move")
check("a badge-less labourer is still not absent (he cannot be measured)",
      not lines["labour, NO badge"].absent, "not absent")

# --- the day's counts are counted, not left over -----------------------------
day.invalidate_recordset()
check("Employees = 6", day.line_count == 6, day.line_count)
check("Present = the two who punched", day.present_count == 2, day.present_count)
check("Absent = the two with a badge and no punch", day.absent_count == 2,
      day.absent_count)
check("Head Office = the three office employees", day.head_office_count == 3,
      day.head_office_count)
# The old arithmetic would have said 6 - 2 - 3 = 1 present, for two punches.
check("the button and the list it opens agree",
      day.present_count == len(day.line_ids.filtered('first_punch')),
      "both count first_punch")

# --- the dashboard's 'no reason' says what its heading says ------------------
Dash = env['ssc.attendance.dashboard'] if 'ssc.attendance.dashboard' in env else None  # noqa: F821
if Dash is not None and hasattr(Dash, 'get_dashboard_data'):
    data = Dash.get_dashboard_data(str(when), str(when))
    names = {row['employee'] for row in data.get('no_reason_table', [])}
    check("no-reason lists the badge-less labourer",
          "labour, NO badge" in names, sorted(names))
    check("and not the badge-less office engineer, who has a reason",
          "office, no badge" not in names, "office staff excluded, as the hint says")

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
