"""Give back the advance days the August sheets were generated without.

    cd ~/src/user

    # report only:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/grant_advance_days.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/grant_advance_days.py

    # and approve the ones the sheet flagged for review:
    SSC_APPLY=1 SSC_APPROVE=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/grant_advance_days.py

The advance is not a number to invent. ssc_attendance_sheet.py computes it:

    def _advance_days(self, profile, month_end):
        first = self.last_date + timedelta(days=1)
        joining = profile['joining_date']
        if joining and joining > first:
            first = joining
        return max((month_end - first).days + 1, 0)

For a sheet running to 25 August in a 31 day month that is the 26th to the
31st - six days, which is the six being asked for. It came out zero because
the sheet carries no_advance_days, and line 516 writes 0 when it is set.

So this recomputes each employee's advance by that same rule rather than
writing a flat six, because somebody who joined on the 28th is owed four days
and not six, and the module already knows that.

WHAT CAN STOP IT REACHING THE MONEY, ALL OF WHICH IS COUNTED FIRST

    summary_id missing on the payslip   the payslip reads the advance through
        summary_id; without one it cannot see it whatever the summary says
    attendance_sheet_id missing         _keeps_stored_figures holds the figures
        of a payslip made by hand
    state = paid                        same guard: the money already left
    has_advance = False                 not eligible - NOR approved, on leave,
        or cancellation submitted. This is the sheet's own judgement and is not
        overridden here
    needs_review                        attended under half the period, so the
        advance waits for a decision. SSC_APPROVE approves those; without it
        they are written and left pending, which grants nothing.

        The flag cannot be read before the write. needs_review is has_advance
        AND advance_days AND ratio under half, so while advance_days is zero it
        is False for everybody: the first run reported none to review and ten
        came back ungranted afterwards. It is now derived from the attendance
        ratio and the days about to be written, which is what the sheet
        concludes once they are there.

SSC_ONLY - APPROVING SOME AND NOT ALL

    SSC_APPROVE on its own approves every flagged line. That is the wrong
    instrument once the flagged set stops being one kind of case. The August
    ten are three kinds: two whose approved leave covers the whole absence, two
    where it covers part, three whose only leave record falls in JULY and so
    explains nothing about August, and one with no record at all.

    SSC_ONLY takes a comma separated list of substrings matched against the
    employee's display name, and approves only the flagged lines that match.
    Everybody else is still written and still left pending. A token matching no
    employee, or more than one, is reported before anything is written - a typo
    that quietly approves nobody is the failure worth guarding against here.

  The money is the point, so the report prices it: advance days times the day
  rate, per employee and in total, before anything is written.

Reads only unless SSC_APPLY=1.
"""
import calendar
import os
from collections import defaultdict
from datetime import timedelta

# ssc_attendance_sheet.py: an advance-eligible employee who attended less
# than this share of the period has the advance held for a decision.
ADVANCE_REVIEW_RATIO = 50.0

WIDTH = 122
APPLY = os.environ.get('SSC_APPLY') == '1'
APPROVE = os.environ.get('SSC_APPROVE') == '1'
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
SHOW = int(os.environ.get('SSC_SHOW') or 25)
ONLY = [t.strip().lower() for t in (os.environ.get('SSC_ONLY') or '').split(',')
        if t.strip()]

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


def num(value, width=11):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


def picked(row):
    """Is this flagged line one SSC_ONLY names? No filter means all of them."""
    if not ONLY:
        return True
    name = (row['slip'].employee_id.display_name or '').lower()
    return any(token in name for token in ONLY)


SscSlip = env['ssc.payslip'].sudo()

slips = SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR))])

title("%s-%s   %s ssc payslip(s)" % (MONTH, YEAR, len(slips)))

rows, blocked = [], defaultdict(list)
for slip in slips:
    summary = slip.summary_id
    sheet = slip.attendance_sheet_id
    if not summary:
        blocked["no summary on the payslip - it cannot read an advance"].append(slip)
        continue
    if not sheet:
        blocked["no attendance sheet - the payslip keeps its stored figures"].append(slip)
        continue
    if slip.state == 'paid':
        blocked["already paid - the figures stand"].append(slip)
        continue
    if slip.studio_ref_id:
        blocked["imported from Studio - no daily lines to derive from"].append(slip)
        continue
    if not summary.has_advance:
        blocked["not advance-eligible on the sheet (has_advance is False)"].append(slip)
        continue

    # The module's own rule, not a flat six.
    last = sheet.last_date
    month_days = calendar.monthrange(last.year, last.month)[1]
    month_end = last.replace(day=month_days)
    first = last + timedelta(days=1)
    joining = summary.ssc_employee_id.joining_date \
        if 'ssc_employee_id' in summary._fields else None
    if joining and joining > first:
        first = joining
    days = max((month_end - first).days + 1, 0)

    # needs_review is has_advance AND advance_days AND ratio under half the
    # period. While advance_days is still zero it reads False for everybody, so
    # the stored flag predicts nothing: the first run reported none to review
    # and ten came back ungranted. Work it out from the days about to be
    # written instead.
    would_review = bool(days and summary.attendance_ratio < ADVANCE_REVIEW_RATIO)
    rows.append({
        'slip': slip, 'summary': summary, 'sheet': sheet, 'days': days,
        'current': summary.advance_days or 0,
        'needs_review': would_review,
        'ratio': summary.attendance_ratio,
        'state': summary.advance_state,
        'rate': slip.rate_per_day or 0.0,
        'money': days * (slip.rate_per_day or 0.0),
    })

# ------------------------------------------------------------------ blocked
title("payslips that cannot take an advance")
if not blocked:
    print("  none")
for reason, group in sorted(blocked.items(), key=lambda kv: -len(kv[1])):
    print("\n  %4s  %s" % (len(group), reason))
    for slip in group[:SHOW]:
        print("        %-44s %s"
              % ((slip.employee_id.display_name or '?')[:44],
                 "staff" if slip.is_staff else "labour"))
    if len(group) > SHOW:
        print("        ... and %s more" % (len(group) - SHOW))

# ------------------------------------------------------------------- to write
title("payslips that would take one")
by_days = defaultdict(list)
for row in rows:
    by_days[row['days']].append(row)
print("  advance days that the sheet's own rule gives:")
for days, group in sorted(by_days.items(), key=lambda kv: -kv[0]):
    print("      %2s day(s)   %4s employee(s)   %s"
          % (days, len(group), num(sum(r['money'] for r in group))))

already = [r for r in rows if r['current'] == r['days']]
changing = [r for r in rows if r['current'] != r['days']]
review = [r for r in changing if r['needs_review']]
print("")
print("  %s already carry the right number and are left alone" % len(already))
print("  %s would change" % len(changing))
print("  %s of those the sheet flagged for review (attended under half the"
      " period)" % len(review))
if review:
    print("      without SSC_APPROVE they are written and stay pending, which")
    print("      grants nothing - advance_granted stays False")
    for row in sorted(review, key=lambda r: -r['money'])[:SHOW]:
        print("        %-40s %s day(s)  %s  attended %.1f%%  state=%s"
              % ((row['slip'].employee_id.display_name or '?')[:40],
                 row['days'], num(row['money']), row['ratio'], row['state']))
    if len(review) > SHOW:
        print("        ... and %s more" % (len(review) - SHOW))

if review and ONLY:
    title("SSC_ONLY - which flagged lines the filter picks")
    for token in ONLY:
        hits = [r for r in review
                if token in (r['slip'].employee_id.display_name or '').lower()]
        if not hits:
            print("  !! %-30s matches NO flagged employee" % token)
        elif len(hits) > 1:
            print("  !! %-30s matches %s of them:" % (token, len(hits)))
            for row in hits:
                print("       %s" % row['slip'].employee_id.display_name)
        else:
            print("  %-30s -> %s" % (token, hits[0]['slip'].employee_id.display_name))
    chosen = [r for r in review if picked(r)]
    held = [r for r in review if not picked(r)]
    print("")
    print("  %s flagged line(s) would be approved, %s left pending"
          % (len(chosen), len(held)))
    print("  approving:  %s day(s)  %s"
          % (sum(r['days'] for r in chosen), num(sum(r['money'] for r in chosen))))
    print("  leaving:    %s day(s)  %s"
          % (sum(r['days'] for r in held), num(sum(r['money'] for r in held))))
    if not chosen:
        print("")
        print("  !! nothing matches - SSC_APPROVE would approve nobody. Check the"
              " spelling before running with SSC_APPLY.")

granting = [r for r in changing
            if not r['needs_review'] or (APPROVE and picked(r))]
title("what it costs")
print("  %-46s %10s %12s" % ("", "days", "money"))
print("  " + "-" * (WIDTH - 4))
print("  %-46s %10s %12s"
      % ("would be granted straight away",
         sum(r['days'] for r in changing if not r['needs_review']),
         num(sum(r['money'] for r in changing if not r['needs_review']), 12)))
print("  %-46s %10s %12s"
      % ("waiting on a review decision",
         sum(r['days'] for r in review), num(sum(r['money'] for r in review), 12)))
print("  " + "-" * (WIDTH - 4))
print("  %-46s %10s %12s"
      % ("total if everything is granted", sum(r['days'] for r in changing),
         num(sum(r['money'] for r in changing), 12)))
print("")
print("  Priced as advance days x the payslip's own rate per day. The payslip")
print("  recomputes total_attendance from the summary, so this is what lands.")

if not APPLY:
    env.cr.rollback()
    print("")
    print("  report only - nothing written. SSC_APPLY=1 writes the advance,")
    print("  SSC_APPROVE=1 as well approves the flagged ones, and SSC_ONLY")
    print("  narrows that approval to the names it lists.")
else:
    written = approved = 0
    sheets = set()
    for row in changing:
        row['summary'].advance_days = row['days']
        written += 1
        sheets.add(row['sheet'])
        if row['needs_review'] and APPROVE and picked(row):
            row['summary'].advance_state = 'approved'
            approved += 1
    # So a later regeneration of the sheet does not write zero again.
    for sheet in sheets:
        if 'no_advance_days' in sheet._fields and sheet.no_advance_days:
            sheet.no_advance_days = False
    env.cr.commit()

    title("done")
    print("  %s summary(ies) given their advance days" % written)
    print("  %s flagged line(s) approved" % approved)
    print("  %s sheet(s) had no_advance_days switched off so a regeneration"
          " keeps it" % len(sheets))

    granted = [r for r in changing
               if r['summary'].advance_granted]
    print("")
    print("  %s of %s now read advance_granted = True"
          % (len(granted), len(changing)))
    print("  landed: %s day(s), %s"
          % (sum(r['days'] for r in granted),
             num(sum(r['money'] for r in granted))))
    still = [r for r in changing if not r['summary'].advance_granted]
    if still:
        print("")
        print("  %s still not granted - they are the flagged ones and need"
              " a decision:" % len(still))
        for row in sorted(still, key=lambda r: -r['money'])[:SHOW]:
            print("      %-44s %s day(s)  %s"
                  % ((row['slip'].employee_id.display_name or '?')[:44],
                     row['days'], num(row['money'])))
