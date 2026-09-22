"""Who is holding an ungranted advance, why, and who has leave on record.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_advance_holdbacks.py

Ten employees came back with their advance written and not granted, worth
3,716.10 between them. The stated reason is the sheet's review threshold -
attended under half the period - and that claim is worth checking rather than
repeating, because the same ten names have been at the top of the day-gap
column all along and a second explanation would be easy to miss.

So the first section lists every August summary by attendance ratio with the
grant flag beside it, and then states plainly whether the ungranted set and the
under-half set are the same set. If they are not, the difference is the finding.

The second answers the other question: who has a leave record touching any day
up to 31 August, in ANY state. Not only approved - a refused or still-draft
request is exactly what explains somebody attending eight days out of
twenty-five, and a leave that was never approved leaves no trace in the
attendance while still being the reason for it.

Read-only.
"""
import os
from collections import defaultdict

WIDTH = 122
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
UNTIL = os.environ.get('SSC_UNTIL') or '2026-08-31'
FROM = os.environ.get('SSC_FROM') or '2026-07-01'
THRESHOLD = float(os.environ.get('SSC_THRESHOLD') or 50.0)
SHOW = int(os.environ.get('SSC_SHOW') or 40)

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value, width=10):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


SscSlip = env['ssc.payslip'].sudo()
Leave = env['hr.leave'].sudo()

slips = SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR))])

rows = []
for slip in slips:
    summary = slip.summary_id
    if not summary:
        continue
    rows.append({
        'slip': slip, 'summary': summary,
        'name': slip.employee_id.display_name or '?',
        'ratio': summary.attendance_ratio or 0.0,
        'attended': summary.attended_days or 0.0,
        'period': summary.period_days or 0,
        'days': summary.advance_days or 0,
        'granted': summary.advance_granted,
        'has_advance': summary.has_advance,
        'state': summary.advance_state,
        'money': (summary.advance_days or 0) * (slip.rate_per_day or 0.0),
        'employee': slip.employee_id.hr_employee_id,
    })

# ------------------------------------------------- 1. the claim, checked
title("1. every August summary by attendance ratio")
print("  threshold is %.1f%% of the period - under it the sheet holds the"
      " advance" % THRESHOLD)
print("")
print("  %-42s %8s %8s %8s %6s %8s %-9s %s"
      % ("employee", "attended", "period", "ratio %", "adv", "worth",
         "granted", "state"))
print("  " + "-" * (WIDTH - 4))
for row in sorted(rows, key=lambda r: r['ratio'])[:SHOW]:
    print("  %-42s %8.2f %8s %8.1f %6s %s %-9s %s"
          % (row['name'][:42], row['attended'], row['period'], row['ratio'],
             row['days'], num(row['money']), row['granted'], row['state']))
if len(rows) > SHOW:
    print("  ... %s more, all with a higher ratio" % (len(rows) - SHOW))

ungranted = {r['name'] for r in rows if r['days'] and not r['granted']}
under = {r['name'] for r in rows if r['has_advance'] and r['days']
         and r['ratio'] < THRESHOLD}

title("2. is the ungranted set the same as the under-half set?")
print("  %s with an advance written but not granted" % len(ungranted))
print("  %s advance-eligible and under %.1f%%" % (len(under), THRESHOLD))
if ungranted == under:
    print("")
    print("  The same set. Attendance under half the period is the whole")
    print("  reason, and there is no second cause hiding in it.")
else:
    only_ungranted = ungranted - under
    only_under = under - ungranted
    if only_ungranted:
        print("")
        print("  !! %s ungranted for some OTHER reason:" % len(only_ungranted))
        for name in sorted(only_ungranted):
            row = next(r for r in rows if r['name'] == name)
            print("      %-44s ratio %.1f%%  has_advance=%s  state=%s"
                  % (name[:44], row['ratio'], row['has_advance'], row['state']))
    if only_under:
        print("")
        print("  !! %s under the threshold and granted anyway:" % len(only_under))
        for name in sorted(only_under):
            row = next(r for r in rows if r['name'] == name)
            print("      %-44s ratio %.1f%%  state=%s"
                  % (name[:44], row['ratio'], row['state']))

not_eligible = [r for r in rows if not r['has_advance']]
if not_eligible:
    print("")
    print("  %s carry has_advance = False - the sheet's own eligibility, a"
          " separate matter:" % len(not_eligible))
    for row in not_eligible:
        print("      %-44s ratio %.1f%%" % (row['name'][:44], row['ratio']))

# --------------------------------------------------------- 3. the leave
title("3. leave on record up to %s, in ANY state" % UNTIL)
print("  A refused or still-draft request explains a low attendance just as")
print("  well as an approved one, and leaves no mark on the attendance while")
print("  doing it. Everything from %s is listed." % FROM)

employees = {r['employee'].id: r for r in rows if r['employee']}
leaves = Leave.search([
    ('employee_id', 'in', list(employees)),
    ('date_from', '<=', UNTIL + ' 23:59:59'),
    ('date_to', '>=', FROM + ' 00:00:00'),
], order='employee_id, date_from')

by_employee = defaultdict(list)
for leave in leaves:
    by_employee[leave.employee_id.id].append(leave)

print("")
print("  %s leave record(s) across %s employee(s)"
      % (len(leaves), len(by_employee)))

held = [r for r in rows if r['days'] and not r['granted']]
if held:
    title("the ten holding an ungranted advance, with their leave", '-')
    for row in sorted(held, key=lambda r: -r['money']):
        employee = row['employee']
        print("")
        print("  %-44s ratio %.1f%%   attended %.2f of %s   worth %s"
              % (row['name'][:44], row['ratio'], row['attended'],
                 row['period'], num(row['money'])))
        records = by_employee.get(employee.id if employee else 0, [])
        if not records:
            print("      no leave record at all - the absence is unexplained")
        for leave in records:
            print("      %-28s %s .. %s  %5.1f day(s)  state=%s"
                  % ((leave.holiday_status_id.name or '?')[:28],
                     leave.request_date_from or (leave.date_from
                                                 and leave.date_from.date()),
                     leave.request_date_to or (leave.date_to
                                               and leave.date_to.date()),
                     leave.number_of_days or 0.0, leave.state))

title("everybody else with leave on record", '-')
others = [(eid, records) for eid, records in by_employee.items()
          if eid not in {r['employee'].id for r in held if r['employee']}]
print("  %s employee(s)" % len(others))
by_state = defaultdict(lambda: [0, 0.0])
for _eid, records in others:
    for leave in records:
        by_state[(leave.holiday_status_id.name or '?', leave.state)][0] += 1
        by_state[(leave.holiday_status_id.name or '?', leave.state)][1] += \
            leave.number_of_days or 0.0
print("")
print("  %-40s %-12s %7s %9s" % ("leave type", "state", "count", "days"))
print("  " + "-" * (WIDTH - 4))
for (name, state), (count, days) in sorted(by_state.items()):
    mark = "   <-- not approved, so no work entry" \
        if state in ('draft', 'confirm', 'refuse', 'cancel') else ""
    print("  %-40s %-12s %7s %9.1f%s" % (name[:40], state, count, days, mark))

env.cr.rollback()
title("read only - nothing was written")
