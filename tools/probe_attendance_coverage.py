"""What would be lost by deleting x_attendance_per_emplo. Reads only.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http < tools/probe_attendance_coverage.py

Every day in the Studio source, month by month, split three ways: already on
hr.attendance, not there and never could be (Absent and Sick Leave carry no
punch), and not there and would simply be gone. The last column is the answer
to "is it safe to delete this" - and it is the only column that matters.

The bucket rule and the owner resolution are the ones migrate_studio_attendance
uses, so this measures the same rows that migration would have moved, not a
second opinion about which rows those are.
"""
from collections import Counter, defaultdict

WIDTH = 100
WRAPPER = 'x_attendance_per_emplo'

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

if WRAPPER not in env:
    print("  %s is not on this database - nothing to measure." % WRAPPER)
else:
    Wrapper = env[WRAPPER].sudo()

    # The employee behind each wrapper, resolved once.
    hr_by_wrapper = {}
    for wrapper in Wrapper.search([]):
        employee = None
        for field, meta in Wrapper.fields_get().items():
            if meta.get('type') == 'many2one' and meta.get('relation') == 'hr.employee':
                employee = wrapper[field]
                if employee:
                    break
        if not employee:
            name = (wrapper.x_name or '').strip() if 'x_name' in Wrapper._fields else ''
            if name:
                employee = env['hr.employee'].sudo().with_context(
                    active_test=False).search([('name', '=', name)], limit=1)
        if employee:
            hr_by_wrapper[wrapper.id] = employee[:1]

    # The month buckets: a comodel qualifies when it carries a real date column
    # of its own, which is what separates a day from a monthly total.
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
        if datecol:
            sources.append((name, comodel, datecol))

    # Every (employee, day) already on hr.attendance, once.
    covered = set()
    Attendance = env['hr.attendance'].sudo().with_context(active_test=False)
    for row in Attendance.search_read([], ['employee_id', 'check_in']):
        if row['employee_id'] and row['check_in']:
            covered.add((row['employee_id'][0], row['check_in'].date()))

    # A day with no punch cannot become an hr.attendance, so it was never going
    # to be moved and deleting it loses nothing that could have been kept.
    UNPUNCHED = ('absent', 'sick leave')

    per_month = defaultdict(Counter)
    orphan = 0
    for bucket, comodel, datecol in sources:
        Line = env[comodel].sudo()
        cols = Line.fields_get()
        owner_col = next((n for n, m in cols.items()
                          if m.get('type') == 'many2one' and m.get('relation') == WRAPPER),
                         None)
        for line in Line.search([(datecol, '!=', False)]):
            day = line[datecol]
            owner = line[owner_col] if owner_col else None
            employee = hr_by_wrapper.get(owner.id) if owner else None
            if not employee:
                orphan += 1
                continue
            month = day.strftime('%Y-%m')
            status = (line.x_name or '').strip().lower() if 'x_name' in cols else ''
            per_month[month]['days'] += 1
            if (employee.id, day) in covered:
                per_month[month]['on hr'] += 1
            elif status in UNPUNCHED:
                per_month[month]['unpunched'] += 1
            else:
                per_month[month]['LOST'] += 1

    print()
    print("=" * WIDTH)
    print("EVERY DAY IN %s, AND WHAT DELETING IT WOULD COST" % WRAPPER)
    print("=" * WIDTH)
    print("  %-10s %9s %9s %11s %9s" % ("MONTH", "DAYS", "ON HR", "UNPUNCHED", "LOST"))
    print("  " + "-" * (WIDTH - 4))
    total = Counter()
    for month in sorted(per_month):
        row = per_month[month]
        total.update(row)
        print("  %-10s %9s %9s %11s %9s"
              % (month, row['days'], row['on hr'], row['unpunched'], row['LOST']))
    print("  " + "-" * (WIDTH - 4))
    print("  %-10s %9s %9s %11s %9s"
          % ("TOTAL", total['days'], total['on hr'], total['unpunched'], total['LOST']))
    if orphan:
        print()
        print("  %s row(s) whose wrapper resolves to no employee - they were never"
              % orphan)
        print("  attributable to anybody and are not counted above.")
    print()
    if total['LOST']:
        print("  %s day(s) would be gone and nothing else holds them." % total['LOST'])
    else:
        print("  Nothing would be lost: every punched day is already on hr.attendance.")
    print("=" * WIDTH)

env.cr.rollback()
