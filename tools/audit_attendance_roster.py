"""Compare the stored roster fields against what today's employee record says.

    odoo-bin shell --no-http --shell-interface=python < tools/audit_attendance_roster.py

Reads only, and it must stay that way. Five stored fields on ssc.attendance.line
- company_id, staff, on_leave, absent, head_office_staff - are worked out from
the employee when the line is made and never again: the employee's own flags
have never been in their dependency list, so the value is the one that was true
the day the line was written.

That is the right behaviour and it was arrived at by accident. A man on leave
this August was at work in May, and the May lines say so. Recomputing them would
put this August's roster onto every month behind it and change the absences
under payslips that are closed.

So this compares rather than corrects. A difference means the employee's record
has moved since the line was made, which is ordinary and expected; a great many
differences on one employee means somebody changed their status and that is
worth knowing before a payslip is generated. Nothing here writes.
"""
FIELDS = ('company_id', 'staff', 'on_leave', 'absent', 'head_office_staff')
INACTIVE = ('is_cancelled', 'on_leave')
LEAVING = ('approved_nor', 'submitted_cancellation')

cr = env.cr                                                      # noqa: F821
Line = env['ssc.attendance.line'].sudo()                         # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def flagged(employee, names):
    return bool(employee) and any(getattr(employee, name, False) for name in names)


def expected(line):
    """What the computes would say if they ran now - worked out here, not by
    asking the ORM, so that asking cannot accidentally write."""
    employee = line.employee_id
    ssc = line.ssc_employee_id
    off_roster = flagged(ssc, INACTIVE) or flagged(ssc, LEAVING)
    on_leave = bool(ssc.on_leave)
    friday = bool(line.external_id.date and line.external_id.date.weekday() == 4)
    absent = False
    if not (on_leave or not line.attendance_id or off_roster or friday):
        absent = not bool(line.first_punch)
    return {
        'company_id': employee.company_id.id or False,
        'staff': bool(ssc.is_engineer_office),
        'on_leave': on_leave,
        'absent': absent,
        'head_office_staff': (not line.attendance_id) and not (on_leave or off_roster),
    }


def stored(records):
    cr.execute(
        'SELECT id, %s FROM ssc_attendance_line WHERE id IN %%s'
        % ', '.join('"%s"' % f for f in FIELDS), (tuple(records.ids),))
    return {row[0]: dict(zip(FIELDS, row[1:])) for row in cr.fetchall()}


title("0. what is here")

lines = Line.search([], order='id')
print("  %s attendance line(s)" % len(lines))
print("  %s naming no employee" % len(lines.filtered(lambda l: not l.employee_id)))
print("  %s whose employee has no ssc.employee"
      % len(lines.filtered(lambda l: l.employee_id and not l.ssc_employee_id)))


title("1. comparing")

differences = {name: [] for name in FIELDS}
for index in range(0, len(lines), 5000):
    chunk = lines[index:index + 5000]
    have = stored(chunk)
    for line in chunk:
        want = expected(line)
        old = have.get(line.id) or {}
        for name in FIELDS:
            was = old.get(name)
            now = want[name]
            if name != 'company_id':
                was = bool(was)
            else:
                was = was or False
            if was != now:
                differences[name].append((line, was, now))
    print("  %s / %s" % (min(index + 5000, len(lines)), len(lines)))


title("2. where the stored value and today's record disagree")

for name in FIELDS:
    print("  %-20s %s line(s)" % (name, len(differences[name])))


def name_of(line):
    return (line.employee_id.display_name or '(no employee)')[:40]


for name in FIELDS:
    rows = differences[name]
    if not rows:
        continue
    title("3. %s, by employee" % name)
    by_employee = {}
    for line, was, now in rows:
        by_employee.setdefault(name_of(line), []).append((line, was, now))
    for who, entries in sorted(by_employee.items(), key=lambda kv: -len(kv[1]))[:20]:
        dates = sorted(l.date for l, _w, _n in entries if l.date)
        was_values = sorted({str(w) for _l, w, _n in entries})
        now_values = sorted({str(n) for _l, _w, n in entries})
        print("  %-40s %5s line(s)  %s -> %s   %s .. %s"
              % (who, len(entries), '/'.join(was_values), '/'.join(now_values),
                 dates[0] if dates else '-', dates[-1] if dates else '-'))
    if len(by_employee) > 20:
        print("  ... and %s more employee(s)" % (len(by_employee) - 20))

title("summary")
print("  %s line(s) read, nothing written"
      % len(lines))
print("""
  A difference is history, not a fault: the line holds what was true the day it
  was made and the employee has moved since. Correct one only if you know that
  day's answer was wrong, and correct it on the line.""")
