"""Study both sides of the attendance move and say what can actually cross.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/study_attendance_migration.py > /tmp/study.txt

    # narrow it:
    SSC_UNTIL=2026-04-30 SSC_SAMPLE=800 odoo-bin shell ... < tools/study_attendance_migration.py

Self-contained: it discovers the Studio side rather than reading the month-field
map in models/utils.py, because that map covers 2025 and 2026 and says "add new
years as needed" - it records what somebody once needed, not what the database
holds, and the request is for everything from the first record ever.

WHAT A MIGRATION NEEDS TO KNOW, AND THE SECTION THAT ANSWERS IT

    2  which month fields exist, and for which years
    3  what a daily line carries, how often each column is even filled, and
       what the values look like - a column that is 4% filled is not a source
    4  how a line reaches an hr.employee, counted per path, because a mapping
       that resolves 60% of rows is a different project from one that resolves
       all of them
    5  what hr.attendance already holds in the range, and what it will refuse:
       check_in is required and overlapping attendances raise
    6  where the two would collide - (employee, day) pairs that already exist
    7  what is wrong with the source data before it is anybody's problem:
       no check-in, no check-out, check-out before check-in, two rows for one
       day, a date outside the month field holding it

THE PART THAT IS NOT A MAPPING PROBLEM

hr.attendance stores a check-in and a check-out and nothing else. It has no
column for an absence - an absent day is the ABSENCE of a row - and no column
for overtime, because hr.attendance.overtime.line is rebuilt by _update_overtime
from the punches and the version's ruleset. So of attendance, absence and
overtime, only the first is a copy. Section 8 says what that leaves.

Read-only. Nothing here writes, and it ends on a rollback.
"""
import os
from collections import defaultdict

WIDTH = 122
WRAPPER = os.environ.get('SSC_WRAPPER') or 'x_attendance_per_emplo'
UNTIL = os.environ.get('SSC_UNTIL') or '2026-04-30'
SAMPLE = int(os.environ.get('SSC_SAMPLE') or 1000)
SHOW = int(os.environ.get('SSC_SHOW') or 25)

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


def short(value, width=58):
    if hasattr(value, '_name'):
        value = "%s(%s)" % (value._name, ",".join(str(i) for i in value.ids[:3]))
    text = str(value).replace("\n", " ")
    return text[:width]


# =====================================================================  1
title("1. the two models")
if WRAPPER not in env:
    print("  %s is NOT in the registry. Nothing to study." % WRAPPER)
    env.cr.rollback()
    raise SystemExit
Wrapper = env[WRAPPER].sudo()
Att = env['hr.attendance'].sudo()
print("  source  %-34s %s record(s)" % (WRAPPER, Wrapper.search_count([])))
print("  target  %-34s %s record(s)" % ('hr.attendance', Att.search_count([])))

wrap_meta = Wrapper.fields_get()
print("")
print("  the wrapper's many2one fields - one of these names the employee:")
for name, meta in sorted(wrap_meta.items()):
    if meta.get('type') == 'many2one':
        print("      %-44s -> %-26s %s"
              % (name, meta.get('relation'), meta.get('string') or ''))

# =====================================================================  2
title("2. the monthly buckets, discovered from the model itself")

# Every model that inherits mail.thread carries these, and they are not month
# buckets. Left in, mail.message wins the count - Studio gives each month field
# its own comodel, so the real ones have one field each while mail.message has
# two - and the whole study then describes the chatter instead of the
# attendance. That is exactly what happened the first time this was run.
MIXIN = ('message_', 'activity_', 'rating_', 'website_message_', 'my_activity_')
buckets = {name: meta for name, meta in wrap_meta.items()
           if meta.get('type') in ('one2many', 'many2many')
           and not name.startswith(MIXIN)}
dropped = [n for n, m in wrap_meta.items()
           if m.get('type') in ('one2many', 'many2many') and n.startswith(MIXIN)]
if dropped:
    print("  ignoring %s mail/activity mixin field(s): %s"
          % (len(dropped), ", ".join(sorted(dropped))))

by_comodel = defaultdict(list)
for name, meta in buckets.items():
    by_comodel[meta.get('relation')].append(name)
for comodel, names in sorted(by_comodel.items()):
    print("")
    print("  %s   <- %s bucket field(s)" % (comodel, len(names)))
    for name in sorted(names):
        print("      %-46s %s" % (name, buckets[name].get('string') or ''))

known = set()
try:
    from odoo.addons.ssc_payroll.models.utils import STUDIO_MONTH_FIELDS
    known = {f for months in STUDIO_MONTH_FIELDS.values() for f in months.values()}
except Exception as exc:                                        # noqa: BLE001
    print("")
    print("  (STUDIO_MONTH_FIELDS unreadable: %s)" % exc)
if known:
    extra = sorted(set(buckets) - known)
    gone = sorted(known - set(buckets))
    print("")
    print("  the module's map names %s field(s)." % len(known))
    if extra:
        print("  !! %s bucket(s) the map has never heard of - if any hold rows,"
              " those years would be lost by anything built on the map:" % len(extra))
        for name in extra:
            print("        %-46s %s" % (name, buckets[name].get('string') or ''))
    if gone:
        print("  !! %s field(s) in the map but not on the model:" % len(gone))
        for name in gone:
            print("        %s" % name)
    if not extra and not gone:
        print("  map and model agree exactly.")

# Choosing the daily-line model. Not by counting bucket fields - Studio gives
# each month its own comodel, so counting picks whatever mixin survived. A
# daily line is recognised by what it holds: a date, and something that reads
# like a punch. Every candidate is printed with its score so the choice is
# visible rather than trusted.
PUNCH_WORDS = ('check', 'punch', 'in_time', 'out_time', 'time_in', 'time_out',
               'first', 'last', 'entry', 'exit')
print("")
print("  candidates, scored on what they hold:")
print("  %-42s %-8s %-7s %-7s %-6s" % ("MODEL", "BUCKETS", "DATE", "PUNCH", "ROWS"))
scored = []
for comodel, names in sorted(by_comodel.items()):
    if not comodel or comodel not in env:
        continue
    cols = env[comodel].sudo().fields_get()
    has_date = any(m.get('type') in ('date', 'datetime') for m in cols.values())
    punch = sum(1 for n in cols if any(w in n.lower() for w in PUNCH_WORDS))
    try:
        rows = env[comodel].sudo().search_count([])
    except Exception:                                           # noqa: BLE001
        rows = -1
    score = (2 if has_date else 0) + min(punch, 6) + (1 if rows > 0 else 0)
    scored.append((score, comodel, len(names), has_date, punch, rows))
    print("  %-42s %-8s %-7s %-7s %-6s"
          % (comodel[:42], len(names), 'yes' if has_date else 'no', punch, rows))

LINE = os.environ.get('SSC_LINE')
if LINE:
    print("")
    print("  SSC_LINE overrides the choice: %s" % LINE)
elif scored:
    scored.sort(key=lambda row: (-row[0], -row[5]))
    LINE = scored[0][1]
    print("")
    print("  chosen: %s" % LINE)
if not LINE or LINE not in env:
    print("")
    print("  !! could not identify a daily-line model. Set SSC_LINE=<model>"
          " and run it again.")
    env.cr.rollback()
    raise SystemExit
Line = env[LINE].sudo()

# =====================================================================  3
title("3. %s - every column, how often it is filled, what it looks like" % LINE)
total_lines = Line.search_count([])
print("  %s row(s) in total" % total_lines)
sample = Line.search([], limit=SAMPLE, order='id desc')
line_meta = Line.fields_get()
print("  fill rates measured on the newest %s row(s)" % len(sample))
print("")
print("  %-40s %-11s %6s  %s" % ("field", "type", "filled", "examples"))
print("  " + "-" * (WIDTH - 4))
filled = {}
for name in sorted(line_meta):
    if name in ('display_name', '__last_update'):
        continue
    kind = line_meta[name].get('type')
    seen, examples = 0, []
    for rec in sample:
        try:
            value = rec[name]
        except Exception:                                       # noqa: BLE001
            break
        if value or value == 0.0 and kind in ('float', 'integer'):
            if value:
                seen += 1
                if len(examples) < 3 and short(value) not in examples:
                    examples.append(short(value, 22))
    filled[name] = seen
    pct = (100.0 * seen / len(sample)) if sample else 0.0
    rel = line_meta[name].get('relation')
    print("  %-40s %-11s %5.0f%%  %s%s"
          % (name, kind, pct, " | ".join(examples),
             ("  -> %s" % rel) if rel else ''))

dates = [n for n, m in line_meta.items()
         if m.get('type') in ('date', 'datetime')
         and n not in ('create_date', 'write_date')]
print("")
print("  date/datetime columns: %s" % (", ".join(sorted(dates)) or "NONE"))
for name in sorted(dates):
    rows = Line.read_group([(name, '!=', False)], [name], ["%s:year" % name])
    if not rows:
        continue
    print("")
    print("  %s by year:" % name)
    for row in rows:
        print("      %-10s %8s row(s)"
              % (row.get("%s:year" % name), row.get('__count') or 0))

DATE = dates[0] if dates else None

# =====================================================================  4
title("4. how a daily line reaches an hr.employee")
back = [n for n, m in line_meta.items()
        if m.get('type') == 'many2one' and m.get('relation') == WRAPPER]
emp_links = [n for n, m in line_meta.items()
             if m.get('type') == 'many2one'
             and (m.get('relation') or '') in ('hr.employee', 'ssc.employee',
                                               'x_employeeslist')]
print("  back-reference to the wrapper : %s" % (", ".join(back) or "NONE"))
print("  employee-ish links on the line: %s" % (", ".join(emp_links) or "NONE"))

wrap_emp = [n for n, m in wrap_meta.items()
            if m.get('type') == 'many2one'
            and (m.get('relation') or '') in ('hr.employee', 'ssc.employee',
                                              'x_employeeslist')]
print("  employee-ish links on wrapper : %s" % (", ".join(wrap_emp) or "NONE"))

print("")
print("  resolving the newest %s line(s) to an hr.employee:" % len(sample))
paths = defaultdict(int)
unresolved = []
for rec in sample:
    target = None
    path = None
    for name in emp_links:
        value = rec[name]
        if value:
            path = "line.%s -> %s" % (name, value._name)
            target = value
            break
    if target is None and back:
        wrapper = rec[back[0]]
        for name in wrap_emp:
            value = wrapper[name] if wrapper else None
            if value:
                path = "line.%s -> wrapper.%s -> %s" % (back[0], name, value._name)
                target = value
                break
    if target is None:
        unresolved.append(rec)
        paths["NO LINK AT ALL"] += 1
        continue
    if target._name == 'hr.employee':
        paths[path + " (already hr.employee)"] += 1
    else:
        hr = target.hr_employee_id if 'hr_employee_id' in target._fields \
            else None
        paths[path + (" -> hr_employee_id" if hr else " -> NO hr_employee_id")] += 1
for path, count in sorted(paths.items(), key=lambda kv: -kv[1]):
    print("      %6s  %s" % (count, path))

# =====================================================================  5
title("5. hr.attendance - what it demands and what it already holds")
att_meta = Att.fields_get()
required = [n for n, m in att_meta.items() if m.get('required')]
print("  required fields: %s" % ", ".join(sorted(required)))
print("")
print("  python constraints on the model:")
for name in sorted(getattr(Att, '_constraint_methods', []) and
                   [m.__name__ for m in Att._constraint_methods] or []):
    print("      %s" % name)
print("")
first = Att.search([], order='check_in', limit=1)
last = Att.search([], order='check_in desc', limit=1)
print("  earliest check_in : %s" % (first.check_in or '-'))
print("  latest   check_in : %s" % (last.check_in or '-'))
print("")
print("  rows up to %s, by year:" % UNTIL)
for row in Att.read_group([('check_in', '<=', UNTIL + ' 23:59:59')],
                          ['check_in'], ['check_in:year']):
    print("      %-10s %8s row(s)" % (row.get('check_in:year'),
                                      row.get('__count') or 0))
open_rows = Att.search_count([('check_out', '=', False)])
print("")
print("  %s row(s) with no check_out - an open attendance. hr.attendance"
      " allows" % open_rows)
print("  only one of these per employee at a time, so importing a second one")
print("  for an employee who already has one will raise.")

# =====================================================================  6
title("6. where the two would collide")
if not DATE:
    print("  no date column on the line model - collisions cannot be checked.")
else:
    src = Line.search([(DATE, '!=', False), (DATE, '<=', UNTIL)])
    print("  %s source line(s) dated on or before %s" % (len(src), UNTIL))
    days = defaultdict(set)
    for rec in src[:SAMPLE * 5]:
        wrapper = rec[back[0]] if back else None
        emp = None
        for name in emp_links:
            if rec[name]:
                emp = rec[name]
                break
        if emp is None and wrapper is not None:
            for name in wrap_emp:
                if wrapper[name]:
                    emp = wrapper[name]
                    break
        if emp is None:
            continue
        hr = emp if emp._name == 'hr.employee' else (
            emp.hr_employee_id if 'hr_employee_id' in emp._fields else None)
        if hr:
            days[hr.id].add(rec[DATE])
    pairs = sum(len(v) for v in days.values())
    print("  %s (employee, day) pair(s) resolved from the first %s line(s)"
          % (pairs, min(len(src), SAMPLE * 5)))
    clash = 0
    checked = 0
    for emp_id, dates_set in list(days.items())[:200]:
        for day in list(dates_set)[:40]:
            checked += 1
            if Att.search_count([
                    ('employee_id', '=', emp_id),
                    ('check_in', '>=', "%s 00:00:00" % day),
                    ('check_in', '<=', "%s 23:59:59" % day)]):
                clash += 1
    print("  of %s pair(s) actually checked, %s already have an hr.attendance"
          " row" % (checked, clash))
    print("")
    print("  Anything built from this has to key on (employee, day) and skip")
    print("  what is there. An empty-looking year is not proof of an empty year.")

# =====================================================================  7
title("7. what is wrong with the source before it is anybody's problem")
if DATE:
    checks = []
    ins = [n for n in line_meta
           if 'check_in' in n or n.endswith('_in') or 'checkin' in n]
    outs = [n for n in line_meta
            if 'check_out' in n or n.endswith('_out') or 'checkout' in n]
    print("  columns that look like a check-in : %s" % (", ".join(ins) or "NONE"))
    print("  columns that look like a check-out: %s" % (", ".join(outs) or "NONE"))
    scope = [(DATE, '!=', False), (DATE, '<=', UNTIL)]
    checks.append(("lines in scope", Line.search_count(scope)))
    for name in ins:
        checks.append(("  %s empty" % name,
                       Line.search_count(scope + [(name, '=', False)])))
    for name in outs:
        checks.append(("  %s empty" % name,
                       Line.search_count(scope + [(name, '=', False)])))
    print("")
    for label, count in checks:
        print("      %-46s %8s" % (label, count))

    print("")
    print("  two rows for one (wrapper, day):")
    if back:
        groups = Line.read_group(scope, [], [back[0], DATE], lazy=False)
        dupes = [g for g in groups if (g.get('__count') or 0) > 1]
        print("      %s pair(s) carry more than one row" % len(dupes))
        for group in dupes[:SHOW]:
            print("        %-52s %s  x%s"
                  % (short(group.get(back[0]), 52), group.get(DATE),
                     group.get('__count')))
        if len(dupes) > SHOW:
            print("        ... and %s more" % (len(dupes) - SHOW))

# =====================================================================  8
title("8. what this means for the three things asked for")
print("""
  attendance   a copy, once the employee link and the check-in/check-out
               columns above are confirmed. check_in is required; a line with
               no check-in cannot become an hr.attendance row at all.

  overtime     NOT copied. hr.attendance has no overtime column: overtime
               lives in hr.attendance.overtime.line, which _update_overtime
               rebuilds from the punches and the version's ruleset. Import the
               punches and the overtime follows - and it will follow the CURRENT
               rules, which is not necessarily what Studio recorded at the time.
               If the Studio figure is the one that must survive, it has to go
               somewhere else, and that is a different decision.

  absence      has no home here. An absent day in hr.attendance is the absence
               of a row. If the absences must be visible as records they belong
               in hr.leave, with a leave type, and that is a second migration
               with its own rules - not a column on this one.
""")

env.cr.rollback()
title("read only - nothing was written")
