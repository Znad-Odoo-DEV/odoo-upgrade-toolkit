"""Re-run on_leave and absent on the lines the new rule governs.

    cd ~/src/user

    # report only:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/recompute_attendance_absence.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/recompute_attendance_absence.py

Both fields are stored computes, and Odoo re-runs a stored compute only when
something in its own @api.depends changes. Neither of the two changes that
matter here is such a thing:

    on_leave stopped reading x_studio_on_leave and started reading hr.leave
    absent stopped treating x_studio_on_leave as an exemption

Nothing on the lines themselves moved, so every row keeps the value the old
rules gave it until something touches it. New lines are born correct; the ones
already in the table are not, and the difference is invisible - a stale True
looks exactly like a fresh one.

So this recomputes both, over the lines dated on or after ON_LEAVE_FROM_DATE.
Earlier days are never touched: they belong to months that have been paid, and
the floor in the compute exists for the same reason.

Order matters. on_leave is recomputed and flushed first, because absent reads
it - doing both in one pass would settle absence against the on_leave that was
there when the pass began.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

WIDTH = 122
APPLY = os.environ.get('SSC_APPLY') == '1'
SHOW = int(os.environ.get('SSC_SHOW') or 30)

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


from odoo.addons.ssc_attendance.models.ssc_attendance import (  # noqa: E402
    ON_LEAVE_FROM_DATE)

Line = env['ssc.attendance.line'].sudo()
FROM = os.environ.get('SSC_FROM') or str(ON_LEAVE_FROM_DATE)

module = env['ir.module.module'].sudo().search(
    [('name', '=', 'ssc_attendance')], limit=1)
title("ssc_attendance %s   -   lines from %s onward"
      % (module.latest_version or '?', FROM))
print("  2.21 is the version that takes x_studio_on_leave out of the absence")
print("  rules. On anything earlier this tool recomputes the OLD rule and")
print("  changes nothing, which is not an error but is not the point either.")

lines = Line.search([('date', '>=', FROM)], order='date, id')
print("")
print("  %s line(s) in scope" % len(lines))
if not lines:
    env.cr.rollback()
    title("nothing to do")
    raise SystemExit

before = {line.id: (line.on_leave, line.absent) for line in lines}

# Recompute on_leave first and let it settle, then absent, which reads it.
env.add_to_compute(Line._fields['on_leave'], lines)
lines.flush_recordset(['on_leave'])
env.add_to_compute(Line._fields['absent'], lines)
lines.flush_recordset(['absent'])

moved_leave, moved_absent = [], []
for line in lines:
    was_leave, was_absent = before[line.id]
    if line.on_leave != was_leave:
        moved_leave.append((line, was_leave, line.on_leave))
    if line.absent != was_absent:
        moved_absent.append((line, was_absent, line.absent))

title("what moves")
print("  %-46s %s" % ("on_leave changes", len(moved_leave)))
print("      %-42s %s" % ("gains the mark (False -> True)",
                          len([m for m in moved_leave if m[2]])))
print("      %-42s %s" % ("loses the mark (True -> False)",
                          len([m for m in moved_leave if not m[2]])))
print("")
print("  %-46s %s" % ("absent changes", len(moved_absent)))
print("      %-42s %s" % ("becomes ABSENT (False -> True)",
                          len([m for m in moved_absent if m[2]])))
print("      %-42s %s" % ("stops being absent (True -> False)",
                          len([m for m in moved_absent if not m[2]])))
print("")
print("  Every new absent day is a deduction the payroll will pick up. This is")
print("  the number to read before applying, not after.")

if moved_absent:
    title("who becomes absent, and on which days", '-')
    by_employee = defaultdict(list)
    for line, _was, now in moved_absent:
        if now:
            by_employee[line.hr_employee_id.name
                        or line.employee_id.display_name or '?'].append(line.date)
    for name, days in sorted(by_employee.items(), key=lambda kv: -len(kv[1]))[:SHOW]:
        shown = ", ".join(str(d) for d in sorted(days)[:6])
        more = "  (+%s more)" % (len(days) - 6) if len(days) > 6 else ""
        print("  %-44s %2s day(s)   %s%s"
              % (name[:44], len(days), shown, more))
    if len(by_employee) > SHOW:
        print("  ... and %s more employee(s)" % (len(by_employee) - SHOW))

if not APPLY:
    env.cr.rollback()
    title("report only - nothing written")
    print("  The recompute above ran inside the transaction and was rolled")
    print("  back, so the numbers are real and the table is untouched.")
    print("  SSC_APPLY=1 keeps them.")
else:
    env.cr.commit()
    title("done")
    print("  %s line(s) recomputed: %s on_leave change(s), %s absent change(s)"
          % (len(lines), len(moved_leave), len(moved_absent)))
