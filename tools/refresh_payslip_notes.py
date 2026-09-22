"""Rewrite the auto note on the August payslips so it matches the summary.

    cd ~/src/user

    # report only:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/refresh_payslip_notes.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/refresh_payslip_notes.py

auto_note is built once, at generation, from the summary as it stood then. Two
things have moved under it since:

    the advance days were written afterwards, so 253 payslips still carry
        "No advance days paid for this period" while their summary says six

    the withheld ten now get the leave on record appended - which leave, in
        which state, and whether it covers any day of the period at all. That
        text did not exist when the notes were written.

So this asks the sheet to build each note again and writes back only the ones
that actually changed. The note is a description of the summary, not a figure
of its own, so rebuilding it cannot move any money: nothing here writes to a
summary, a sheet, or a payslip line.

A payslip with no summary or no attendance sheet is skipped rather than
blanked - _build_payslip_note has nothing to read for it, and an empty note is
worse than a stale one.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

WIDTH = 122
APPLY = os.environ.get('SSC_APPLY') == '1'
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
SHOW = int(os.environ.get('SSC_SHOW') or 40)

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


def num(value, width=10):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


def plain(html):
    """The note as lines, with the markup taken back off."""
    if not html:
        return []
    text = html.replace('<br/>', '\n').replace('<br>', '\n')
    while '<' in text and '>' in text:
        start = text.index('<')
        end = text.index('>', start) if '>' in text[start:] else len(text)
        text = text[:start] + text[end + 1:]
    text = (text.replace('&amp;', '&').replace('&lt;', '<')
                .replace('&gt;', '>').replace('&quot;', '"')
                .replace('&#39;', "'"))
    return [line.rstrip() for line in text.split('\n') if line.strip()]


SscSlip = env['ssc.payslip'].sudo()

slips = SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR))])
title("%s-%s   %s ssc payslip(s)" % (MONTH, YEAR, len(slips)))

skipped = defaultdict(list)
changed, same = [], 0
for slip in slips:
    summary = slip.summary_id
    sheet = slip.attendance_sheet_id
    if not summary:
        skipped["no summary - nothing to describe"].append(slip)
        continue
    if not sheet:
        skipped["no attendance sheet - the note has no builder"].append(slip)
        continue
    try:
        note = sheet._build_payslip_note(summary)
    except Exception as exc:                      # noqa: BLE001
        skipped["the note could not be built: %s" % exc].append(slip)
        continue
    if (note or False) == (slip.auto_note or False):
        same += 1
        continue
    changed.append({
        'slip': slip, 'summary': summary, 'note': note,
        'was': plain(slip.auto_note), 'now': plain(note),
        'withheld': bool(summary.advance_days and not summary.advance_granted),
        'money': (summary.advance_days or 0) * (slip.rate_per_day or 0.0),
    })

for reason, group in sorted(skipped.items(), key=lambda kv: -len(kv[1])):
    print("  %4s skipped: %s" % (len(group), reason))
print("  %4s already correct" % same)
print("  %4s would be rewritten" % len(changed))

# --------------------------------------------- the withheld ones, in full
withheld = [row for row in changed if row['withheld']]
if withheld:
    title("advance withheld - the note now carries the reason")
    for row in sorted(withheld, key=lambda r: -r['money']):
        print("")
        print("  %-46s  %s day(s) withheld, worth %s"
              % ((row['slip'].employee_id.display_name or '?')[:46],
                 row['summary'].advance_days, num(row['money'])))
        for line in row['now']:
            if 'Advance' in line or line.startswith('  '):
                print("      %s" % line.strip())

# ------------------------------------------------------- everybody else
others = [row for row in changed if not row['withheld']]
if others:
    title("the rest - the note was written before the advance was")
    for row in others[:SHOW]:
        before = [ln for ln in row['was'] if 'dvance' in ln] or ['(no advance line)']
        after = [ln for ln in row['now'] if 'dvance' in ln] or ['(no advance line)']
        print("  %-40s %-34s -> %s"
              % ((row['slip'].employee_id.display_name or '?')[:40],
                 before[0][:34], after[0][:44]))
    if len(others) > SHOW:
        print("  ... and %s more" % (len(others) - SHOW))

if not APPLY:
    env.cr.rollback()
    title("report only - nothing written")
    print("  SSC_APPLY=1 writes the notes. No summary, sheet or payslip line is")
    print("  touched either way - auto_note is the only field this writes.")
else:
    for row in changed:
        row['slip'].auto_note = row['note']
    env.cr.commit()
    title("done")
    print("  %s note(s) rewritten, %s of them carrying a withheld advance"
          % (len(changed), len(withheld)))
