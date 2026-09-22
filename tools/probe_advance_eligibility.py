"""Which of the three flags is holding has_advance down, per employee.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_advance_eligibility.py

The Advance Days wizard refuses to write when the summary carries
has_advance = False, and the refusal is deliberate: advance_granted is computed
from that flag, so any number written under it stays worth zero. But the wizard
can only say the flag is down; it cannot say WHY, and "NOR approved, on leave,
or cancellation submitted" is three different situations with three different
answers.

The flag is not typed on the summary. ssc_attendance_sheet._employee_profile
derives it once, when the sheet is generated:

    has_advance = not (ssc.approved_nor or ssc.on_leave
                       or ssc.submitted_cancellation)

So it is a photograph of three booleans on ssc.employee taken at generation
time, and it can be stale in both directions - somebody whose NOR was cancelled
last week still carries the flag the sheet saw. This lists, for every August
summary with has_advance = False, which of the three is set on the employee
master TODAY, so a stale photograph is visible as a disagreement rather than
mistaken for a decision.

Read-only.
"""
import os

WIDTH = 122
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value, width=10):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


FLAGS = (
    ('approved_nor', 'Approved NOR'),
    ('on_leave', 'On Leave'),
    ('submitted_cancellation', 'Submitted Cancellation'),
)

SscSlip = env['ssc.payslip'].sudo()
slips = SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR))])

rows = []
for slip in slips:
    summary = slip.summary_id
    if not summary:
        continue
    ssc = summary.ssc_employee_id
    set_now = [label for name, label in FLAGS
               if name in ssc._fields and ssc[name]]
    rows.append({
        'slip': slip, 'summary': summary, 'ssc': ssc,
        'name': slip.employee_id.display_name or '?',
        'has_advance': summary.has_advance,
        'ratio': summary.attendance_ratio or 0.0,
        'days': summary.advance_days or 0,
        'set_now': set_now,
        'would_be': not set_now,
        'money': (summary.advance_days or 0) * (slip.rate_per_day or 0.0),
    })

blocked = [r for r in rows if not r['has_advance']]

title("%s-%s   %s summary(ies), %s with has_advance = False"
      % (MONTH, YEAR, len(rows), len(blocked)))

if not blocked:
    print("  nobody is blocked on eligibility.")
else:
    print("  %-44s %7s %6s  %s" % ("employee", "ratio", "days", "flags set on ssc.employee TODAY"))
    print("  " + "-" * (WIDTH - 4))
    for row in sorted(blocked, key=lambda r: -r['ratio']):
        print("  %-44s %6.1f%% %6s  %s"
              % (row['name'][:44], row['ratio'], row['days'],
                 ", ".join(row['set_now']) or "NONE - see below"))

# ------------------------------------------------- the photograph disagreeing
title("where the sheet's photograph and the employee master disagree")
stale_open = [r for r in blocked if r['would_be']]
stale_shut = [r for r in rows if r['has_advance'] and r['set_now']]

print("""
  has_advance was worked out when the sheet was generated. These are the rows
  where re-deriving it from ssc.employee right now gives a different answer.
""")
if stale_open:
    print("  %s blocked, but NONE of the three flags is set any more:"
          % len(stale_open))
    for row in stale_open:
        print("      %-44s ratio %5.1f%%  %s day(s) worth %s"
              % (row['name'][:44], row['ratio'], row['days'], num(row['money'])))
    print("")
    print("      The block is a photograph of a state that has since been")
    print("      cleared. Nothing here changes it - regenerating the sheet")
    print("      would, and so would writing has_advance on the summary.")
else:
    print("  none blocked by a flag that is no longer set.")

print("")
if stale_shut:
    print("  %s eligible on the sheet, but a flag IS set now:" % len(stale_shut))
    for row in stale_shut:
        print("      %-44s %s" % (row['name'][:44], ", ".join(row['set_now'])))
    print("")
    print("      These were eligible when the sheet ran and would not be if it")
    print("      ran today. Their advance has already been granted.")
else:
    print("  nobody eligible on the sheet carries a flag now.")

# ------------------------------------------------------------- what to do
title("what changes each case")
print("""
  a flag that is correct        the block is correct too. The employee is
                                leaving, on leave, or has an approved NOR, and
                                an advance is money paid for days after a period
                                they may not be here for. Leave it.

  a flag that is out of date    fix it on the employee master (Employees ->
                                the three booleans: Approved NOR, On Leave,
                                Submitted Cancellation), then either regenerate
                                the attendance sheet or set has_advance on the
                                summary line. The wizard will then open.

  the flag is right but the     that is a decision to pay somebody the sheet
  advance is wanted anyway      says is not eligible. It has to be made on the
                                summary, on purpose, not slipped past the
                                wizard - which is why the wizard refuses.
""")

env.cr.rollback()
title("read only - nothing was written")
