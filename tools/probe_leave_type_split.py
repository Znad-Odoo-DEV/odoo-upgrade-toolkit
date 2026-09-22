"""Which Time Off types will mark a day on leave, and which lines can be reached.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_leave_type_split.py

ssc.attendance.line.on_leave now reads hr.leave: an APPROVED leave of any type
except sick leave makes its days leave days. Two things decide whether that
works, and neither is visible from the code alone.

1. THE SPLIT IS BY NAME

   hr.leave.type offers no flag saying "this is sick leave", so the exclusion
   matches on the type's name, lower-cased and stripped, against

       SICK_LEAVE_TYPE_NAMES = ('sick time off', 'sick leave 50%')

   Renaming a type therefore moves it to the other side silently. This prints
   every type that exists and the side it lands on, so the list is confirmed
   once against the database rather than assumed.

2. A LINE WITHOUT hr_employee_id CANNOT BE MATCHED

   The rule joins hr.leave to the line through hr_employee_id. A line that
   never resolved its badge to an Odoo employee has no key, so it can never be
   marked on leave no matter how many leaves the person has. That is not a
   silent partial success - it is a population that has to be known.

It also shows what the change will actually do from ON_LEAVE_FROM_DATE onward,
against what the old permanent tick was giving.

Read-only.
"""
import os
from collections import defaultdict
from datetime import date

WIDTH = 122
SHOW = int(os.environ.get('SSC_SHOW') or 30)

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

module = env['ir.module.module'].sudo().search(
    [('name', '=', 'ssc_attendance')], limit=1)
print("ssc_attendance installed version: %s   (2.20 is the one that links a"
      " line at creation)" % (module.latest_version or '?'))


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


try:
    from odoo.addons.ssc_attendance.models.ssc_attendance import (
        SICK_LEAVE_TYPE_NAMES, APPROVED_LEAVE_STATE, ON_LEAVE_FROM_DATE)
except Exception as exc:                                        # noqa: BLE001
    print("Could not import the constants (module not upgraded yet?): %s" % exc)
    SICK_LEAVE_TYPE_NAMES = ('sick time off', 'sick leave 50%')
    APPROVED_LEAVE_STATE = 'validate'
    ON_LEAVE_FROM_DATE = date(2026, 8, 31)

# ------------------------------------------------------------------ 1
title("1. every Time Off type, and the side it falls on")
print("  excluded names: %s" % ", ".join(SICK_LEAVE_TYPE_NAMES))
print("  a type NOT in that list marks its approved days as on leave")
print("")
Type = env['hr.leave.type'].sudo()
Leave = env['hr.leave'].sudo()
types = Type.search([])
print("  %-40s %-10s %-12s %9s  %s"
      % ("leave type", "company", "side", "approved", "days approved"))
print("  " + "-" * (WIDTH - 4))
for leave_type in types.sorted(lambda t: (t.name or '')):
    name = (leave_type.name or '').strip().lower()
    sick = name in SICK_LEAVE_TYPE_NAMES
    approved = Leave.search([('holiday_status_id', '=', leave_type.id),
                             ('state', '=', APPROVED_LEAVE_STATE)])
    print("  %-40s %-10s %-12s %9s  %13.1f"
          % ((leave_type.name or '?')[:40],
             (leave_type.company_id.name or 'all')[:10],
             "SICK - skip" if sick else "ON LEAVE",
             len(approved), sum(approved.mapped('number_of_days'))))
print("")
print("  Anything reading ON LEAVE above will take people off the roster for")
print("  those days. Check the list before this is relied on.")

# ------------------------------------------------------------------ 2
title("2. can the lines be reached? hr_employee_id coverage")
Line = env['ssc.attendance.line'].sudo()
total = Line.search_count([])
linked = Line.search_count([('hr_employee_id', '!=', False)])
print("  %s attendance line(s) in total" % total)
print("  %s carry an hr_employee_id  (%.1f%%)"
      % (linked, (100.0 * linked / total) if total else 0.0))
print("  %s do NOT - unreachable by any leave, whatever the employee has"
      % (total - linked))

recent = [('date', '>=', ON_LEAVE_FROM_DATE)]
recent_total = Line.search_count(recent)
recent_linked = Line.search_count(recent + [('hr_employee_id', '!=', False)])
print("")
print("  from %s onward, which is all the new rule governs:" % ON_LEAVE_FROM_DATE)
print("      %s line(s), %s linked (%.1f%%)"
      % (recent_total, recent_linked,
         (100.0 * recent_linked / recent_total) if recent_total else 0.0))
if recent_total and recent_linked < recent_total:
    print("")
    print("  employees behind the unlinked lines:")
    holes = defaultdict(int)
    for line in Line.search(recent + [('hr_employee_id', '=', False)], limit=5000):
        holes[line.employee_id.display_name or '(no employee at all)'] += 1
    for name, count in sorted(holes.items(), key=lambda kv: -kv[1])[:SHOW]:
        print("      %-50s %s line(s)" % (name[:50], count))
    if len(holes) > SHOW:
        print("      ... and %s more" % (len(holes) - SHOW))

# ------------------------------------------------------------------ 3
title("3. what the change would mark, against what is stored now")
print("""
  A line only reaches hr.leave through hr_employee_id, and that link is written
  when the line is created (2.20) or by the day's sync. Lines made before
  either had run carry no link yet, so filtering on the stored column measures
  how far the sync has got, not what the rule would do.

  So the link is resolved here the same way the module resolves it - badge
  first, then name, through _hr_employee_lookup - and the answer below is what
  the rule marks once every line is linked.
""")
Attendance = env['ssc.attendance'].sudo()
try:
    from odoo.addons.ssc_attendance.models.ssc_attendance import (
        _normalize_badge, _normalize_name, _is_studio_off_roster)
    lookup = Attendance._hr_employee_lookup()
except Exception as exc:                                        # noqa: BLE001
    print("  could not build the lookup (%s); falling back to the stored"
          " column only" % exc)
    lookup = None


def resolve(line):
    if line.hr_employee_id:
        return line.hr_employee_id
    if not lookup:
        return None
    badge = _normalize_badge(line.attendance_id)
    found = lookup['by_badge'].get(badge) if badge else None
    if not found and line.employee_id:
        found = lookup['by_name'].get(
            _normalize_name(line.employee_id.sudo().display_name))
    return found


lines = Line.search(recent)
resolved = {}
for line in lines:
    employee = resolve(line)
    if employee:
        resolved[line.id] = employee.id
print("  %s line(s) from %s onward, %s of them resolve to an hr.employee"
      % (len(lines), ON_LEAVE_FROM_DATE, len(resolved)))
print("      (%s carried the link already, %s were resolved here)"
      % (Line.search_count(recent + [('hr_employee_id', '!=', False)]),
         len(resolved) - Line.search_count(
             recent + [('hr_employee_id', '!=', False)])))
lines = lines.filtered(lambda r: r.id in resolved)
if lines:
    dates = lines.mapped('date')
    leaves = Leave.search([
        ('employee_id', 'in', list(set(resolved.values()))),
        ('state', '=', APPROVED_LEAVE_STATE),
        ('request_date_from', '<=', max(dates)),
        ('request_date_to', '>=', min(dates)),
    ])
    spans = defaultdict(list)
    skipped_sick = 0
    for leave in leaves:
        if (leave.holiday_status_id.name or '').strip().lower() \
                in SICK_LEAVE_TYPE_NAMES:
            skipped_sick += 1
            continue
        if leave.request_date_from and leave.request_date_to:
            spans[leave.employee_id.id].append(
                (leave.request_date_from, leave.request_date_to))
    print("  %s approved leave(s) overlap the range, %s of them sick and skipped"
          % (len(leaves), skipped_sick))

    would, stored = set(), set()
    for line in lines:
        if line.on_leave:
            stored.add(line.id)
        if any(a <= line.date <= b
               for a, b in spans.get(resolved[line.id], ())):
            would.add(line.id)
    print("")
    print("  %-46s %s" % ("marked on leave now (the old permanent tick)", len(stored)))
    print("  %-46s %s" % ("would be marked by the new rule", len(would)))
    print("  %-46s %s" % ("gained - really on approved leave", len(would - stored)))
    print("  %-46s %s" % ("lost - ticked but no approved leave", len(stored - would)))
    print("")
    print("  'lost' is the point of the change, not a regression: those are")
    print("  days somebody was carrying a permanent tick with no leave record")
    print("  behind it. on_leave feeds _compute_absent, so each one becomes a")
    print("  day that now counts as attended or absent on its own evidence.")

    Employee = env['hr.employee'].sudo()
    gained = Line.browse(sorted(would - stored))
    if gained:
        print("")
        print("  GAINED - on approved leave, not marked until now:")
        for line in gained[:SHOW]:
            print("      %-42s %s  %s" % (
                (Employee.browse(resolved[line.id]).name or '?')[:42], line.date,
                ", ".join(
                    "%s %s..%s" % (lv.holiday_status_id.name,
                                   lv.request_date_from, lv.request_date_to)
                    for lv in leaves
                    if lv.employee_id.id == resolved[line.id]
                    and lv.request_date_from <= line.date <= lv.request_date_to)))
        if len(gained) > SHOW:
            print("      ... and %s more" % (len(gained) - SHOW))

    lost = Line.browse(sorted(stored - would))
    if lost:
        print("")
        print("  LOST - carrying the permanent tick with no approved leave"
              " behind it.")
        print("")
        print("  Losing the on_leave mark is NOT the same as becoming absent."
              " _compute_absent")
        print("  exempts a line when ANY of these holds, and only the first is"
              " the field")
        print("  this change touches:")
        print("")
        print("      on_leave                      <- now from hr.leave")
        print("      no attendance_id (badge)")
        print("      _is_studio_off_roster(emp)    <- x_studio_cancelled,"
              " x_studio_ON_LEAVE,")
        print("                                       x_studio_approved_nor,")
        print("                                       x_studio_submitted_cancellation")
        print("      the day is a Friday")
        print("")
        print("  x_studio_on_leave is still IN that second list. So the same"
              " tick that")
        print("  no longer marks the day on leave still exempts it from"
              " absence, by a")
        print("  different route. The column below applies the whole rule, not"
              " just the")
        print("  punch.")
        print("")
        print("      %-40s %-11s %-8s %-9s %s"
              % ("employee", "date", "punched", "absent now", "absent after"))
        print("      " + "-" * (WIDTH - 10))
        becomes_absent = 0
        for line in lost[:SHOW]:
            emp = line.employee_id
            other_exempt = (
                not line.attendance_id
                or _is_studio_off_roster(emp)
                or (line.date and line.date.weekday() == 4))
            after = (not other_exempt) and not bool(line.first_punch)
            if after:
                becomes_absent += 1
            print("      %-40s %-11s %-8s %-9s %s" % (
                (Employee.browse(resolved[line.id]).name or '?')[:40],
                line.date, "yes" if line.first_punch else "no",
                "yes" if line.absent else "no",
                "ABSENT" if after else "still exempt"))
        if len(lost) > SHOW:
            print("      ... and %s more" % (len(lost) - SHOW))
        print("")
        print("  %s of the %s shown actually become absent." % (
            becomes_absent, min(len(lost), SHOW)))
        if not becomes_absent:
            print("  None of them do: every one is held by x_studio_on_leave"
                  " through")
            print("  _is_studio_off_roster. Until that flag comes out of"
                  " _STUDIO_INACTIVE_FLAGS")
            print("  as well, this change moves the on-leave MARK and nothing"
                  " else - no")
            print("  absence, no deduction, no money.")

unresolved = [line for line in Line.search(recent) if line.id not in resolved]
if unresolved:
    print("")
    print("  %s line(s) resolve to nobody at all - no badge match and no name"
          " match:" % len(unresolved))
    for line in unresolved[:SHOW]:
        print("      %-42s badge %-12s %s" % (
            (line.employee_id.display_name or '?')[:42],
            line.attendance_id or '-', line.date))

env.cr.rollback()
title("read only - nothing was written")
