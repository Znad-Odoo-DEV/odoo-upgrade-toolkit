"""Turn Studio's attendance days into hr.attendance punches.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http < tools/migrate_studio_attendance.py

    APPLY=1        write. Without it nothing is kept.
    SSC_UNTIL=     last day to move (default 2026-04-30)
    SSC_LIMIT=     stop after N rows, for a trial
    SSC_TIMESHEET=0  skip the timesheet rows (they are written by default)

x_attendance_per_emplo holds no punches. A day says the person was present, how
much overtime they did, and which project they were on - so the punches have to
be invented, and invented such that Odoo arrives back at the same two numbers.

Measured on this database rather than assumed: a nine-hour span produces eight
worked hours, because the calendar's 12:00-13:00 lunch is taken out of anything
that spans it. Ten produces nine worked and one hour of overtime; eleven
produces two. So the day is

    check_in  = 08:00
    check_out = 17:00 + overtime hours

and the overtime follows from the punches, because it cannot be written: every
create runs _update_overtime, which deletes the overtime lines in range and
regenerates them from the punches and the version's ruleset. An employee whose
version carries no ruleset gets none, whatever is imported.

WHAT IS NOT MOVED

The five *_summary buckets hold 78,036 rows and carry no date at all - their
columns are x_studio_total_attendance, x_studio_total_overtime and a project.
They are per-project monthly totals, not days, and nothing in them can become
an attendance. x_studio_staff_project is the same shape.

An absent day is not moved either, because hr.attendance has nowhere to put
one: absence there is the ABSENCE of a row. If the absences must be visible
they belong in hr.leave, which is a different migration with its own rules.
"""
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from pytz import timezone, utc

APPLY = os.environ.get('APPLY') == '1'
UNTIL = os.environ.get('SSC_UNTIL') or '2026-04-30'
LIMIT = int(os.environ.get('SSC_LIMIT') or 0)
# Timesheets are written for the historical period too, by instruction.
TIMESHEET = os.environ.get('SSC_TIMESHEET', '1') == '1'
WRAPPER = 'x_attendance_per_emplo'

# The day, as the calendar draws it.
DAY_START = 8.0          # 08:00
DAY_END = 17.0           # 17:00 - eight worked hours once lunch is removed
WIDTH = 104

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

Wrapper = env.get(WRAPPER)
if Wrapper is None:
    raise SystemExit("%s is not on this database." % WRAPPER)
Attendance = env['hr.attendance'].sudo()
Aal = env['account.analytic.line'].sudo()


def title(text):
    print()
    print("=" * WIDTH)
    print(text)
    print("=" * WIDTH)


# ----------------------------------------------------------------------
# The month buckets. A bucket qualifies when its model carries a real date
# column of its own - which is what separates a day from a monthly total.
# ----------------------------------------------------------------------
MIXIN = ('message_', 'activity_', 'rating_', 'website_message_', 'my_activity_')
AUDIT = ('create_date', 'write_date', '__last_update')

sources = []
for name, meta in Wrapper.fields_get().items():
    if meta.get('type') != 'one2many' or name.startswith(MIXIN):
        continue
    comodel = meta.get('relation')
    if not comodel or comodel not in env:
        continue
    cols = env[comodel].sudo().fields_get()
    datecol = next((n for n, m in sorted(cols.items())
                    if m.get('type') == 'date' and n not in AUDIT
                    and 'related' not in n), None)
    if not datecol:
        continue                        # a monthly total, not a day
    rows = env[comodel].sudo().search_count([(datecol, '!=', False),
                                             (datecol, '<=', UNTIL)])
    if rows:
        sources.append((name, comodel, datecol, rows))

sources.sort(key=lambda row: row[0])
title("1. WHAT WILL BE READ")
print("  up to %s   apply=%s   timesheets=%s" % (UNTIL, APPLY, TIMESHEET))
print()
print("  %-34s %-40s %s" % ("BUCKET", "MODEL", "ROWS IN RANGE"))
print("  " + "-" * (WIDTH - 4))
for name, comodel, datecol, rows in sources:
    print("  %-34s %-40s %s" % (name[:34], comodel[-40:], rows))
print("  " + "-" * (WIDTH - 4))
print("  %-34s %-40s %s" % ("TOTAL", "", sum(r for _, _, _, r in sources)))

# ----------------------------------------------------------------------
# The employee behind a line, resolved once per wrapper rather than per row.
# ----------------------------------------------------------------------
title("2. WHO THE DAYS BELONG TO")

EMP_FIELDS = [n for n, m in Wrapper.fields_get().items()
              if m.get('type') == 'many2one' and 'employee' in n.lower()]
print("  employee link(s) on the wrapper: %s" % (", ".join(EMP_FIELDS) or "NONE"))

hr_by_wrapper = {}
unresolved = []
for wrapper in Wrapper.with_context(active_test=False).search([]):
    target = None
    for field in EMP_FIELDS:
        value = wrapper[field]
        if not value:
            continue
        if value._name == 'hr.employee':
            target = value
            break
        # A Studio employee, or ours: both name their hr.employee.
        for step in ('hr_employee_id', 'x_studio_employee', 'employee_id'):
            if step in value._fields and value[step]:
                candidate = value[step]
                if candidate._name == 'hr.employee':
                    target = candidate
                    break
        if not target and value._name != 'hr.employee':
            match = env['ssc.employee'].with_context(active_test=False).search(
                [('name', '=ilike', value.display_name)], limit=1)
            target = match.hr_employee_id or None
        if target:
            break
    if target:
        hr_by_wrapper[wrapper.id] = target
    else:
        unresolved.append(wrapper.display_name)

print("  %s wrapper(s), %s resolved to an hr.employee, %s not"
      % (Wrapper.search_count([]), len(hr_by_wrapper), len(unresolved)))
for name in unresolved[:15]:
    print("      unresolved: %s" % name)
if len(unresolved) > 15:
    print("      ... and %s more" % (len(unresolved) - 15))
if not hr_by_wrapper:
    raise SystemExit("Nothing resolves to an employee - stopping.")

# Whose version carries a ruleset. Without one the punches import fine and
# produce no overtime at all, which is worth saying before it happens.
no_ruleset = {hr.display_name for hr in set(hr_by_wrapper.values())
              if not ('ruleset_id' in hr.version_id._fields and hr.version_id.ruleset_id)}
print()
print("  employees whose version has NO overtime ruleset: %s" % len(no_ruleset))
for name in sorted(no_ruleset)[:10]:
    print("      %s" % name)
print("  Their days will import; their overtime will come out zero.")

# ----------------------------------------------------------------------
title("3. WHAT THE DAYS SAY")

statuses = Counter()
overtime_seen = Counter()
rows_by_employee = defaultdict(list)
undated = 0
no_owner = 0

for bucket, comodel, datecol, _count in sources:
    Line = env[comodel].sudo()
    cols = Line.fields_get()
    ot_col = next((n for n in ('x_studio_overtime',) if n in cols), None)
    proj_col = next((n for n in ('x_studio_project',) if n in cols), None)
    owner_col = next((n for n, m in cols.items()
                      if m.get('type') == 'many2one'
                      and m.get('relation') == WRAPPER), None)
    for line in Line.search([(datecol, '!=', False), (datecol, '<=', UNTIL)],
                            order='%s asc' % datecol):
        day = line[datecol]
        if not day:
            undated += 1
            continue
        owner = line[owner_col] if owner_col else None
        employee = hr_by_wrapper.get(owner.id) if owner else None
        if not employee:
            no_owner += 1
            continue
        status = (line.x_name or '').strip() if 'x_name' in cols else ''
        statuses[status or '(blank)'] += 1
        hours = float(line[ot_col] or 0) if ot_col else 0.0
        overtime_seen[hours] += 1
        rows_by_employee[employee].append(
            (day, status, hours, line[proj_col] if proj_col else None))

print("  the status on each day (x_name):")
for status, count in statuses.most_common(12):
    print("      %-28s %s" % (status, count))
print()
print("  overtime hours per day:")
for hours, count in sorted(overtime_seen.items())[:12]:
    print("      %-6s %s day(s)" % (hours, count))
print()
print("  %s row(s) with no date, %s whose wrapper resolves to nobody"
      % (undated, no_owner))

# ----------------------------------------------------------------------
class _Undo(Exception):
    """Raised to unwind a savepoint in dry run: the record is really created
    and really validated, then thrown away."""


title("4. WHAT WOULD BE WRITTEN")

# Which statuses mean the person was there. Anything else is reported rather
# than guessed at: a status nobody mapped is days quietly not imported.
PRESENT = {w.strip().lower() for w in
           (os.environ.get('SSC_PRESENT') or 'present').split(',')}
print("  statuses counted as present: %s" % ", ".join(sorted(PRESENT)))
skipped_status = Counter()

# Every day that already has an attendance, so a second run adds nothing.
existing = set()
for att in Attendance.search([('check_in', '<=', UNTIL + ' 23:59:59')]):
    existing.add((att.employee_id.id, att.check_in.date()))
print("  %s (employee, day) pair(s) already in hr.attendance" % len(existing))

made = skipped_present = skipped_dupe = 0
sheets = 0
no_project = 0
errors = []
tz = timezone(env.company.resource_calendar_id.tz or 'Asia/Dubai')

for employee, days in rows_by_employee.items():
    for day, status, hours, project in sorted(days):
        if status.strip().lower() not in PRESENT:
            skipped_status[status or '(blank)'] += 1
            skipped_present += 1
            continue
        if (employee.id, day) in existing:
            skipped_dupe += 1
            continue
        if LIMIT and made >= LIMIT:
            break
        check_in = tz.localize(datetime.combine(day, datetime.min.time())
                               + timedelta(hours=DAY_START))
        check_out = tz.localize(datetime.combine(day, datetime.min.time())
                                + timedelta(hours=DAY_END + hours))
        values = {
            'employee_id': employee.id,
            'check_in': check_in.astimezone(utc).replace(tzinfo=None),
            'check_out': check_out.astimezone(utc).replace(tzinfo=None),
        }
        try:
            with env.cr.savepoint():
                Attendance.create(values)
                if TIMESHEET and project and 'project_id' in Aal._fields:
                    native = project if project._name == 'project.project' else                         env['project.project'].search(
                            [('name', '=ilike', project.display_name)], limit=1)
                    if native:
                        line = Aal.create({
                            'name': 'Attendance %s' % day,
                            'employee_id': employee.id,
                            'project_id': native.id,
                            'date': day,
                            'unit_amount': 8.0 + hours,
                        })
                        # A second write with amount ALONE. Odoo recomputes it
                        # whenever unit_amount, employee_id or account_id is
                        # among the values written - and a priced timesheet
                        # charges the site the payroll entry already charged.
                        line.write({'amount': 0.0})
                        sheets += 1
                    else:
                        no_project += 1
                if not APPLY:
                    raise _Undo()
        except _Undo:
            pass
        except Exception as exc:                                # noqa: BLE001
            # Its own savepoint has already unwound it, so the transaction is
            # intact and the rest can go on. One row Odoo will not take is not
            # a reason to throw away seven thousand it would have.
            errors.append("%s %s: %s"
                          % (employee.display_name, day,
                             " ".join(str(exc).split())[:150]))
            continue
        made += 1
        existing.add((employee.id, day))
        if made % 250 == 0:
            print("      ... %s written, %s refused" % (made, len(errors)), flush=True)
    if LIMIT and made >= LIMIT:
        break

print()
print("  %-44s %s" % ("attendances %s" % ("written" if APPLY else "validated"), made))
print("  %-44s %s" % ("timesheet rows", sheets))
print("  %-44s %s" % ("days already in hr.attendance, skipped", skipped_dupe))
print("  %-44s %s" % ("days not counted as present", skipped_present))
print("  %-44s %s" % ("days whose project has no project.project", no_project))
if skipped_status:
    print()
    print("  the statuses that were skipped - check none of these is a working day:")
    for status, count in skipped_status.most_common(10):
        print("      %-28s %s" % (status, count))
if errors:
    print()
    print("  %s row(s) Odoo refused:" % len(errors))
    for line in errors[:25]:
        print("      %s" % line)
    if len(errors) > 25:
        print("      ... and %s more" % (len(errors) - 25))

print()
print("=" * WIDTH)
if APPLY:
    env.cr.commit()
    print("Committed %s attendance(s) and %s timesheet row(s)." % (made, sheets))
    if errors:
        print("%s row(s) Odoo refused are listed above and were NOT written."
              % len(errors))
        print("They are skipped by name and day - fix them and run again; the")
        print("rows already in are keyed on (employee, day) and will not double.")
else:
    env.cr.rollback()
    print("Nothing was kept.")
print("=" * WIDTH)
