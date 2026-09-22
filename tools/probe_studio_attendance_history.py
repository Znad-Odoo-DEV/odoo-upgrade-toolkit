"""What the Studio attendance history actually looks like, before moving it.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_studio_attendance_history.py

x_attendance_per_emplo is one record per employee holding the daily lines in a
SEPARATE one2many field per (year, month) - x_studio_apr_2025, x_studio_may_2025
and so on, with the naming changing between years. models/utils.py maps 2025 and
2026 by hand and says "add new years as needed", so that map is a record of what
somebody needed once, not of what the database holds. "Everything from the first
record ever" cannot be read off it.

So nothing here is assumed. The month fields are discovered from the model, the
line model is discovered from those fields, and its columns are discovered from
the line model - then the dates in the data say where the history really starts.

WHAT THIS HAS TO SETTLE BEFORE ANY MIGRATION IS WRITTEN

    which month fields exist        including years the map never mentions
    what a daily line carries       check in/out? a status? overtime hours?
                                    one row per day, or one per punch?
    how a line reaches an employee  through the wrapper, or by its own field
    what hr.attendance already has  the range to import must not double up
                                    what is already there

ONE THING IT WILL PROBABLY SHOW, AND IT MATTERS

hr.attendance stores a check-in and a check-out. It has nowhere to put an
absence: a day off is the ABSENCE of a row, not a row saying "absent". And
overtime is not stored on the attendance either - hr.attendance.overtime.line
is rebuilt by _update_overtime from the punches and the ruleset. So of the three
things asked for, only attendance is a direct copy; the other two are
consequences of it, or belong somewhere else entirely.

Read-only.
"""
import os
from collections import defaultdict

WIDTH = 122
WRAPPER = os.environ.get('SSC_WRAPPER') or 'x_attendance_per_emplo'
UNTIL = os.environ.get('SSC_UNTIL') or '2026-04-30'
SAMPLES = int(os.environ.get('SSC_SAMPLES') or 3)

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


# ------------------------------------------------------------- the wrapper
title("1. %s" % WRAPPER)
if WRAPPER not in env:
    print("  NOT in the registry - nothing to migrate from this database.")
    env.cr.rollback()
    raise SystemExit

Wrapper = env[WRAPPER].sudo()
wrappers = Wrapper.search([])
print("  %s wrapper record(s)" % len(wrappers))

info = Wrapper.fields_get()
relational = {name: meta for name, meta in info.items()
              if meta.get('type') in ('one2many', 'many2many')}
scalar_links = {name: meta for name, meta in info.items()
                if meta.get('type') == 'many2one'}

print("")
print("  many2one fields (how a wrapper names its employee):")
for name, meta in sorted(scalar_links.items()):
    print("      %-42s -> %-28s %s"
          % (name, meta.get('relation'), meta.get('string') or ''))

# ------------------------------------------------- the month buckets
title("2. the monthly one2many buckets, as the model actually has them")
by_comodel = defaultdict(list)
for name, meta in relational.items():
    by_comodel[meta.get('relation')].append(name)

for comodel, names in sorted(by_comodel.items()):
    print("")
    print("  %s   <- %s field(s)" % (comodel, len(names)))
    for name in sorted(names):
        print("      %-46s %s" % (name, relational[name].get('string') or ''))

known = set()
try:
    from odoo.addons.ssc_payroll.models.utils import STUDIO_MONTH_FIELDS
    known = {field for months in STUDIO_MONTH_FIELDS.values()
             for field in months.values()}
except Exception as exc:                                      # noqa: BLE001
    print("")
    print("  (could not read STUDIO_MONTH_FIELDS: %s)" % exc)

if known:
    on_model = set(relational)
    missing = sorted(known - on_model)
    extra = sorted(on_model - known)
    print("")
    print("  the module's map names %s field(s)" % len(known))
    if missing:
        print("  !! %s in the map but NOT on this model:" % len(missing))
        for name in missing:
            print("        %s" % name)
    if extra:
        print("  !! %s on the model but NOT in the map - these are the years"
              " the map never learned:" % len(extra))
        for name in extra:
            print("        %-46s %s" % (name, relational[name].get('string') or ''))
    if not missing and not extra:
        print("  the map and the model agree exactly.")

# --------------------------------------------------- the daily line model
for comodel in sorted(by_comodel):
    if not comodel or comodel not in env:
        continue
    title("3. %s - what one daily line carries" % comodel)
    Line = env[comodel].sudo()
    total = Line.search_count([])
    print("  %s row(s) in total" % total)
    meta = Line.fields_get()
    print("")
    print("  %-44s %-12s %s" % ("field", "type", "label"))
    print("  " + "-" * (WIDTH - 4))
    for name in sorted(meta):
        kind = meta[name].get('type')
        rel = meta[name].get('relation')
        print("  %-44s %-12s %s%s"
              % (name, kind, meta[name].get('string') or '',
                 (" -> %s" % rel) if rel else ''))

    dates = [n for n, m in meta.items()
             if m.get('type') in ('date', 'datetime') and n not in (
                 'create_date', 'write_date')]
    print("")
    print("  date-ish fields: %s" % (", ".join(sorted(dates)) or "NONE"))

    for name in sorted(dates):
        rows = Line.read_group([(name, '!=', False)], [name], ["%s:year" % name])
        if not rows:
            continue
        print("")
        print("  %s by year:" % name)
        for row in rows:
            print("      %-14s %s row(s)"
                  % (row.get("%s:year" % name), row.get('__count')
                     or row.get(name + '_count') or 0))

    print("")
    print("  %s sample row(s):" % SAMPLES)
    for line in Line.search([], limit=SAMPLES, order='id'):
        print("")
        for name in sorted(meta):
            if name in ('display_name',):
                continue
            try:
                value = line[name]
            except Exception:                                 # noqa: BLE001
                continue
            if not value:
                continue
            if hasattr(value, '_name'):
                value = "%s(%s) %s" % (value._name, value.id or '',
                                       value.display_name or '')
            print("        %-40s %s" % (name, str(value)[:70]))

# ------------------------------------------------------- what is already there
title("4. hr.attendance as it stands")
Att = env['hr.attendance'].sudo()
print("  %s row(s) in total" % Att.search_count([]))
first = Att.search([], order='check_in', limit=1)
last = Att.search([], order='check_in desc', limit=1)
print("  earliest check_in: %s" % (first.check_in or '-'))
print("  latest   check_in: %s" % (last.check_in or '-'))
print("")
print("  up to %s, by year:" % UNTIL)
for row in Att.read_group([('check_in', '<=', UNTIL + ' 23:59:59')],
                          ['check_in'], ['check_in:year']):
    print("      %-14s %s row(s)"
          % (row.get('check_in:year'), row.get('__count') or 0))
print("")
print("  Whatever is already in this range must not be imported twice. The")
print("  migration has to key on (employee, day) and skip what is there, not")
print("  trust that an empty-looking year is empty.")

env.cr.rollback()
title("read only - nothing was written")
