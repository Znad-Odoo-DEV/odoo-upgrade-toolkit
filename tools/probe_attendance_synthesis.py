"""What punches have to look like to mean eight hours and the right overtime.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http < tools/probe_attendance_synthesis.py

    SSC_LINE=x_...    name the Studio daily-line model if the guess is wrong
    SSC_EMP=SSCLLC-1  measure against one particular badge

Read only. It creates attendances to measure them and rolls every one back.

x_attendance_per_emplo holds no punches. It records that somebody did their day
and how much overtime they did on top - so the migration cannot copy check-ins,
it has to invent them, and invent them so that Odoo arrives back at the same two
numbers.

Two things make that harder than adding hours to a start time.

hr.attendance.worked_hours is check_out minus check_in MINUS the lunch
intervals the employee's calendar defines inside that span, for anybody whose
resource is not flexible. So eight worked hours is a span of eight plus however
much lunch falls in it, and that is a property of each employee's calendar
rather than a constant.

Overtime cannot be written at all. _update_overtime deletes every overtime line
in range and regenerates them from the punches and the version's ruleset; the
manual_duration it preserves carries a status, not a figure. So the overtime a
day ends up with is whatever the ruleset makes of the punches - which means the
check-out has to be pushed out until the ruleset produces the number Studio
recorded, and an employee whose version carries NO ruleset gets no overtime at
all no matter what is imported.

So this measures rather than derives: it creates a real attendance for a real
employee, reads back what Odoo made of it, and rolls it back.
"""
import os
from collections import defaultdict
from datetime import datetime, timedelta

from pytz import timezone, utc

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

WRAPPER = os.environ.get('SSC_WRAPPER') or 'x_attendance_per_emplo'
UNTIL = os.environ.get('SSC_UNTIL') or '2026-04-30'
WIDTH = 108


def title(text):
    print()
    print("=" * WIDTH)
    print(text)
    print("=" * WIDTH)


# =====================================================================  1
title("1. THE SOURCE - which model holds a day, and what a day says")

Wrapper = env.get(WRAPPER)
SOURCE_OK = Wrapper is not None
if not SOURCE_OK:
    print("  %s is not on this database - skipping to the measurement." % WRAPPER)
wrap_meta = Wrapper.sudo().fields_get() if SOURCE_OK else {}

MIXIN = ('message_', 'activity_', 'rating_', 'website_message_', 'my_activity_')
buckets = {n: m for n, m in wrap_meta.items()
           if m.get('type') in ('one2many', 'many2many') and not n.startswith(MIXIN)}
by_comodel = defaultdict(list)
for name, meta in buckets.items():
    by_comodel[meta.get('relation')].append(name)

PUNCH = ('check', 'punch', 'in_time', 'out_time', 'first', 'last')
OVERTIME = ('overtime', 'ot_', '_ot', 'extra')
PROJECT = ('project', 'site', 'job')

# Studio gives each month its own comodel, so there is no single line model -
# there are as many as there are month buckets. Enumerating them is the whole
# point: a migration that reads one reads one month.
models_seen = {}
for comodel, names in by_comodel.items():
    if not comodel or comodel not in env:
        continue
    try:
        rows = env[comodel].sudo().search_count([])
    except Exception:                                           # noqa: BLE001
        continue
    models_seen[comodel] = (names, rows)

if SOURCE_OK:
    print("  wrapper : %s   (%s record(s))"
          % (WRAPPER, Wrapper.sudo().search_count([])))
    print("  %s distinct line model(s) behind %s bucket field(s)"
          % (len(models_seen), sum(len(n) for n, _ in models_seen.values())))
    print()
    print("  %-38s %-30s %-8s %-8s %-7s %s"
          % ("LINE MODEL", "BUCKET FIELD", "ROWS", "DATED", "IN RNG", "RANGE"))
    print("  " + "-" * (WIDTH - 4))
    grand = dated_total = in_range = 0
    dateless_models = []
    for comodel in sorted(models_seen, key=lambda m: -models_seen[m][1]):
        names, rows = models_seen[comodel]
        grand += rows
        cols = env[comodel].sudo().fields_get()
        # The date column, and not a related mirror of it: those carry the same
        # value but belong to the wrapper, and one of them is what a naive pick
        # lands on.
        # create_date is a date column and sorts before x_studio_date, so
        # picking the first one measured when the row was WRITTEN instead of
        # which day it stands for - every model then read 100% dated with a
        # range of timestamps. Audit columns are not data.
        AUDIT = ('create_date', 'write_date', '__last_update')
        candidates = [n for n, m in sorted(cols.items())
                      if m.get('type') in ('date', 'datetime') and n not in AUDIT]
        # A plain date beats a datetime, and a field of our own beats a related
        # mirror of the wrapper's.
        datecol = (next((n for n in candidates
                         if cols[n].get('type') == 'date' and 'related' not in n), None)
                   or next((n for n in candidates if 'related' not in n), None)
                   or (candidates[0] if candidates else None))
        dated = span = ""
        n_in_range = ""
        if datecol and rows:
            dated = env[comodel].sudo().search_count([(datecol, '!=', False)])
            dated_total += dated
            n_in_range = env[comodel].sudo().search_count(
                [(datecol, '!=', False), (datecol, '<=', UNTIL)])
            in_range += n_in_range
            if dated:
                lo = env[comodel].sudo().search(
                    [(datecol, '!=', False)], order='%s asc' % datecol, limit=1)
                hi = env[comodel].sudo().search(
                    [(datecol, '!=', False)], order='%s desc' % datecol, limit=1)
                span = "%s .. %s" % (lo[datecol], hi[datecol])
        if rows and not dated:
            dateless_models.append((comodel, rows, datecol))
        print("  %-38s %-30s %-8s %-8s %-7s %s"
              % (comodel[-38:], (names[0] if names else '')[:30], rows,
                 dated, n_in_range, span))
    print("  " + "-" * (WIDTH - 4))
    print("  %-38s %-30s %-8s %-8s %-7s"
          % ("TOTAL", "", grand, dated_total, in_range))
    print()
    print("  IN RNG counts rows dated on or before %s - the size of the move." % UNTIL)
    if dateless_models:
        print()
        print("  !! %s model(s) hold rows but not one carries a date. Nothing can be"
              % len(dateless_models))
        print("     placed on a day, so nothing here can become an attendance:")
        for comodel, rows, datecol in dateless_models:
            print("        %-40s %s row(s), date column: %s"
                  % (comodel[-40:], rows, datecol or 'NONE'))
        print("     Look at one before assuming it is junk - together they are")
        print("     %s rows." % sum(r for _, r, _ in dateless_models))
    print("  Every one of these is a month. A migration reading only the")
    print("  best-scoring model reads one month and silently drops the rest.")

LINE = os.environ.get('SSC_LINE')
if not LINE and models_seen:
    LINE = max(models_seen, key=lambda m: models_seen[m][1])
if SOURCE_OK and (not LINE or LINE not in env):
    raise SystemExit("No daily-line model found. Pass SSC_LINE=<model>.")

Line = env[LINE].sudo() if SOURCE_OK else None
if SOURCE_OK:
    # The buckets named *_summary hold 78k rows between them and apr_summary
    # alone holds five times what apr_2025 does, so "summary of April" it is
    # not. Whatever they are, importing them alongside the month buckets would
    # double whatever they overlap - so their shape is printed, not assumed.
    summaries = [(m, models_seen[m]) for m in models_seen
                 if any('summary' in n for n in models_seen[m][0])
                 and models_seen[m][1]]
    if summaries:
        print()
        print("  the *_summary buckets, side by side with a month bucket:")
        for comodel, (names, rows) in sorted(summaries, key=lambda kv: -kv[1][1])[:2]:
            cols = env[comodel].sudo().fields_get()
            own = sorted(n for n in cols
                         if n.startswith('x_') or n.endswith('_id'))
            print("      %-34s %s row(s)" % (names[0][:34], rows))
            print("          %s" % ", ".join(own[:12]))
            row = env[comodel].sudo().search([], limit=1)
            if row:
                shown = []
                for name in own[:8]:
                    try:
                        value = row[name]
                    except Exception:                           # noqa: BLE001
                        continue
                    shown.append("%s=%s" % (name.replace('x_studio_', ''),
                                            str(getattr(value, 'display_name', value))[:18]))
                print("          one row: %s" % "  ".join(shown))

    print()
    print("  columns, read off the largest of them: %s" % LINE)
# =====================================================================  2
title("2. THE TARGET - each employee's day, as Odoo understands it")

Employee = env['hr.employee'].sudo()
badge = os.environ.get('SSC_EMP')
if badge:
    employees = Employee.search([('barcode', '=', badge)], limit=1)
else:
    employees = Employee.search([('ssc_workforce', '!=', 'office_staff')], limit=6)
if not employees:
    raise SystemExit("No employee to measure against.")

print("  %-30s %-26s %-9s %-7s %s"
      % ("EMPLOYEE", "CALENDAR", "HRS/DAY", "FLEX", "RULESET"))
print("  " + "-" * (WIDTH - 4))
for employee in employees:
    calendar = employee.resource_calendar_id
    version = employee.version_id
    ruleset = version.ruleset_id if 'ruleset_id' in version._fields else None
    print("  %-30s %-26s %-9s %-7s %s"
          % (employee.name[:30], (calendar.name or '-')[:26],
             calendar.hours_per_day,
             'yes' if employee.resource_id._is_flexible() else 'no',
             (ruleset.name if ruleset else 'NONE - no overtime will be made')))

calendar = employees[0].resource_calendar_id
print()
print("  %s, hour by hour:" % (calendar.name or '-'))
for line in calendar.attendance_ids.sorted(lambda a: (a.dayofweek, a.hour_from)):
    print("      %-10s %5.2f - %5.2f   %s"
          % (dict(line._fields['dayofweek'].selection).get(line.dayofweek),
             line.hour_from, line.hour_to,
             'LUNCH' if line.day_period == 'lunch' else line.day_period))

# =====================================================================  3
title("3. THE MEASUREMENT - what Odoo makes of punches we invent")

Attendance = env['hr.attendance'].sudo()

employee = employees[0]
tz = timezone(calendar.tz or 'UTC')


def measure(day, start_hour, span_hours):
    """Create one attendance, read what Odoo made of it, roll it back."""
    local_in = tz.localize(datetime.combine(day, datetime.min.time())
                           + timedelta(hours=start_hour))
    local_out = local_in + timedelta(hours=span_hours)
    values = {
        'employee_id': employee.id,
        'check_in': local_in.astimezone(utc).replace(tzinfo=None),
        'check_out': local_out.astimezone(utc).replace(tzinfo=None),
    }
    try:
        with env.cr.savepoint():
            attendance = Attendance.create(values)
            attendance.invalidate_recordset()
            worked = attendance.worked_hours
            expected = attendance.expected_hours if 'expected_hours' in attendance._fields else -1
            overtime = attendance.overtime_hours
            lines = env['hr.attendance.overtime.line'].search(
                [('employee_id', '=', employee.id), ('date', '=', day)])
            duration = sum(lines.mapped('duration'))
            raise _Rollback(worked, expected, overtime, duration, len(lines))
    except _Rollback as done:
        return done.args
    except Exception as exc:                                    # noqa: BLE001
        return ('ERROR', str(exc)[:60], '', '', '')


class _Rollback(Exception):
    pass


# A working day this employee has NO attendance on. hr.attendance refuses a
# record that overlaps an existing one, so measuring on a day they already
# worked returns "Cannot create new attendance record" instead of a number -
# which is exactly what the first production run did. The import range is
# empty by definition, so look there.
probe_day = None
for offset in range(1, 400):
    day = (datetime.now() - timedelta(days=offset)).date()
    if not calendar.attendance_ids.filtered(lambda a: int(a.dayofweek) == day.weekday()):
        continue
    clash = Attendance.search_count([
        ('employee_id', '=', employees[0].id),
        ('check_in', '>=', datetime.combine(day, datetime.min.time())),
        ('check_in', '<=', datetime.combine(day, datetime.max.time())),
    ])
    if not clash:
        probe_day = day
        break
if not probe_day:
    raise SystemExit("No free working day found to measure on.")
print("  measuring on %s (%s)" % (probe_day, probe_day.strftime('%A')))
print("  employee: %s" % employee.name)
print()
print("  %-8s %-9s %-9s %-9s %-9s %s"
      % ("START", "SPAN", "WORKED", "EXPECTED", "OT HOURS", "OT LINES"))
print("  " + "-" * (WIDTH - 4))
for span in (8.0, 9.0, 10.0, 11.0):
    result = measure(probe_day, 8.0, span)
    print("  %-8s %-9s %-9s %-9s %-9s %s"
          % ("08:00", span,
             round(result[0], 3) if isinstance(result[0], float) else result[0],
             round(result[1], 3) if isinstance(result[1], float) else result[1],
             round(result[2], 3) if isinstance(result[2], float) else result[2],
             result[4]))

print()
print("  Read the WORKED column against SPAN: the gap between them is the lunch")
print("  Odoo took out. Whatever span produces 8.0 worked is the base day, and")
print("  every extra hour of overtime is one more hour on top of THAT span.")
print("  If OT HOURS stays 0 as the span grows, the version has no ruleset and")
print("  no amount of importing will produce overtime for this employee.")

# =====================================================================  4
title("4. THE TIMESHEET SIDE - where a project-hour would go")

# The project on a Studio line is not attendance data at all: hr.attendance has
# no project. Hours against a project are account.analytic.line rows, which is
# a second write per day and a second decision - and this database already has
# a rule about what those rows may carry.
Aal = env['account.analytic.line'].sudo()
# project_id arrives with hr_timesheet. Without it there is no timesheet to
# speak of, and asking would raise rather than answer.
if 'project_id' not in Aal._fields:
    print("  hr_timesheet is not installed - account.analytic.line has no")
    print("  project_id, so there is nowhere for a project-hour to go yet.")
    priced = None
else:
    print("  account.analytic.line rows that are timesheets: %s"
          % Aal.search_count([('project_id', '!=', False)]))
    priced = Aal.search_count([('project_id', '!=', False), ('amount', '!=', 0)])
    print("  of those, carrying a non-zero amount            : %s" % priced)
print()
if priced is None:
    pass
elif priced:
    print("  !! Timesheets here are supposed to carry hours at amount 0 - the money")
    print("     reaches a project through the payroll entry instead. Rows with an")
    print("     amount mean the project is charged twice. Check before adding more.")
else:
    print("  Timesheets carry hours at amount 0, as intended: the money reaches a")
    print("  project through the salary journal entry, not through the timesheet.")
    print("  Anything written here must keep that true, or every site is charged")
    print("  twice for the same day.")
print()
print("  A timesheet row needs: employee_id, project_id, date, unit_amount, and")
print("  amount forced to 0 in a SECOND write - Odoo recomputes it whenever")
print("  unit_amount, employee_id or account_id is among the values written.")

env.cr.rollback()
print()
print("=" * WIDTH)
print("read only - every attendance created here was rolled back")
print("=" * WIDTH)
