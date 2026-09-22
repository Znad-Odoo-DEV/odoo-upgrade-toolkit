"""A new day lists the active employees and nobody archived; the absent count leaves the archived out.

    odoo-bin shell -d DB < tools/exercise_populate_lines.py

Three things, on one day created under a context that reads archived records
- the context that used to put every archived person on it:

  the roster       an active employee gets a line, an archived one does not
  the note         an archived employee who punched anyway is flagged for HR
  the count        somebody archived AFTER the day was made keeps the day's
                   absent flag on the line - the line is a photograph and is
                   not rewritten - and is left out of the Absent button, its
                   drill-down, and the dashboard

Rolled back at the end.
"""
from datetime import date

Employee = env['hr.employee'].sudo()                               # noqa: F821
Day = env['ssc.attendance'].sudo()                                 # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-72s %s" % (label, detail))


company = env.company                                              # noqa: F821
active = Employee.create({'name': "Roster test: active", 'company_id': company.id,
                          'barcode': 'RTACT'})
archived = Employee.create({'name': "Roster test: archived", 'company_id': company.id,
                            'barcode': 'RTARC'})
archived.active = False
leaver = Employee.create({'name': "Roster test: leaves later", 'company_id': company.id,
                          'barcode': 'RTLAT'})

# The context that used to leak: a caller reading archived records.
when = date(2026, 9, 30)   # a Wednesday - not the off day
day = Day.with_context(active_test=False).create({'name': "roster test", 'date': when})
on_day = day.line_ids.mapped('employee_id')

check("the active employee is on the day", active in on_day, "line made")
check("the archived employee is NOT on the day, even under active_test=False",
      archived not in on_day, "no line" if archived not in on_day else "!! line made")
check("every line on the day is an active employee",
      all(e.active for e in on_day), "%s line(s)" % len(on_day))

# --- the note ---------------------------------------------------------------
note = Day._archived_punch_note(archived, when)
check("an archived employee who punched gets a note", bool(note), (note or '')[:70])
check("the note tells the reader to inform HR", bool(note) and 'inform HR' in note, "")
check("and names the day", bool(note) and '2026-09-30' in note, "")
check("an active employee gets no note", Day._archived_punch_note(active, when) is False, "False")
check("no employee at all gets no note", Day._archived_punch_note(Employee, when) is False, "False")

# --- the count: archived after the day was made -----------------------------
line = day.line_ids.filtered(lambda l: l.employee_id == leaver)
check("the future leaver is on the day with a badge and no punch",
      len(line) == 1 and line.attendance_id and not line.first_punch, "absent that day")
check("and the day marks them absent", line.absent, "absent")
before = day.absent_count
leaver.active = False
day.invalidate_recordset()
line.invalidate_recordset()
check("archiving them later leaves the line's stored flag as the day had it",
      line.absent, "still absent on the line - the photograph is not rewritten")
check("but the Absent button no longer counts them",
      day.absent_count == before - 1, "%s -> %s" % (before, day.absent_count))
drill = day.with_context(line_filter='absent').action_view_lines()['domain']
found = env['ssc.attendance.line'].sudo().search(drill)               # noqa: F821
check("nor does the button's drill-down list them",
      leaver not in found.mapped('employee_id') and active in found.mapped('employee_id'),
      "%s line(s) listed" % len(found))

Dash = env.get('ssc.attendance.dashboard')                          # noqa: F821
if Dash is not None and hasattr(Dash, 'get_dashboard_data'):
    data = Dash.sudo().get_dashboard_data(str(when), str(when))
    # kpis.total_absences is the absent count over the range - one day here.
    absent_kpi = (data.get('kpis') or {}).get('total_absences')
    check("nor does the dashboard's absent figure",
          absent_kpi is not None and absent_kpi == day.absent_count,
          "dashboard %s, day %s" % (absent_kpi, day.absent_count))

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
