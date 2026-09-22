"""Add the Select Employees domain one leaf at a time and watch where it drops.

    cd ~/src/user
    SSC_COMPANIES="ROYAL ARROW" odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/probe_valid_version_domain.py

_get_valid_version_ids is now read, and its loop cannot be the cause: every
branch either adds a version or falls through to the next one, and the
'employee_versions[-1] == version' arm guarantees the last version is taken.
Whatever removes fifty five labourers removes them in the DOMAIN, before the
loop ever runs.

That domain is nine leaves. Rather than pick the likely one, this rebuilds it
in the source's own order and counts the surviving versions after each:

    company_id                    structure_type_id != False
    employee_id != False          structure_type_id = the run's type
    active_employee = True        schedule_pay = the run's
    contract_date_start <= date_end
    contract_date_end = False or >= date_start
    date_version <= date_end

The leaf that takes the count from sixty odd to two is the answer, and the
employees it dropped are printed with the value that failed - so the fix is
whatever that column says, not whatever seemed likely.

date_version is worth naming in advance: it is required, it defaults to today,
and it is compared against the pay run's END date. A version stamped after the
period is invisible to a pay run for that period, however correct its contract
dates are.

Read-only.
"""
import os
from collections import defaultdict

WIDTH = 116
FROM = os.environ.get('SSC_FROM') or '2026-08-01'
TO = os.environ.get('SSC_TO') or '2026-08-25'
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or 'ROYAL ARROW').split(',') if n.strip()]
SHOW = int(os.environ.get('SSC_SHOW') or 12)

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


Run = env['hr.payslip.run'].sudo()
Version = env['hr.version'].sudo()

runs = [r for r in Run.search([('date_start', '<=', TO), ('date_end', '>=', FROM)])
        if not ONLY or any(p in (r.company_id.name or '').upper() for p in ONLY)]

for run in runs:
    if not run.structure_id:
        continue
    structure = run.structure_id
    if not (structure.name or '').endswith('Labour Pay'):
        continue

    title("[%s] %s" % (run.id, run.name or '?'))
    print("  structure %s   type %s   schedule %s   dates %s .. %s"
          % (structure.name, structure.type_id.name, run.schedule_pay,
             run.date_start, run.date_end))

    date_start, date_end = run.date_start, run.date_end
    leaves = [
        ("company_id = the run's",
         [('company_id', '=', run.company_id.id)]),
        ("employee_id != False",
         [('employee_id', '!=', False)]),
        ("active_employee = True",
         [('active_employee', '=', True)]),
        ("contract_date_start <= %s" % date_end,
         [('contract_date_start', '<=', date_end)]),
        ("contract_date_end = False or >= %s" % date_start,
         ['|', ('contract_date_end', '=', False),
          ('contract_date_end', '>=', date_start)]),
        ("date_version <= %s" % date_end,
         [('date_version', '<=', date_end)]),
        ("structure_type_id != False",
         [('structure_type_id', '!=', False)]),
        ("structure_type_id = %s" % structure.type_id.name,
         [('structure_type_id', '=', structure.type_id.id)]),
        ("schedule_pay = %s" % run.schedule_pay,
         [('schedule_pay', '=', run.schedule_pay)]),
    ]

    print("\n  %-52s %8s %8s" % ("after adding this leaf", "versions", "people"))
    print("  " + "-" * (WIDTH - 4))
    cumulative = []
    previous = None
    culprit = None
    for label, leaf in leaves:
        candidate = cumulative + leaf
        found = Version.search(candidate)
        people = len(set(found.mapped('employee_id').ids))
        drop = "" if previous is None else "   -%s" % (previous - people)
        print("  %-52s %8s %8s%s" % (label, len(found), people, drop))
        if previous is not None and culprit is None and previous - people >= 10:
            culprit = (label, cumulative, leaf)
        cumulative = candidate
        previous = people

    # Name the people the biggest leaf dropped, with the value that failed.
    if culprit:
        label, before_domain, leaf = culprit
        title("the leaf that dropped them: %s" % label, '-')
        before = Version.search(before_domain)
        after = Version.search(before_domain + leaf)
        lost = before - after
        field = leaf[-1][0] if isinstance(leaf[-1], (list, tuple)) else None
        by_value = defaultdict(list)
        for version in lost:
            value = version[field] if field and field in version._fields else '?'
            by_value[str(value)].append(version.employee_id.name or '?')
        print("  %s version(s) dropped, %s employee(s)"
              % (len(lost), len(set(lost.mapped('employee_id').ids))))
        print("  grouped by %s:" % field)
        for value, names in sorted(by_value.items(), key=lambda kv: -len(kv[1])):
            print("\n    %-24s %s employee(s)" % (value, len(names)))
            for name in sorted(set(names))[:SHOW]:
                print("        %s" % name)
            if len(set(names)) > SHOW:
                print("        ... and %s more" % (len(set(names)) - SHOW))

    # date_version is the one that can be true of every version at once, so
    # show its spread whether or not it was the culprit.
    title("date_version across this company's versions", '-')
    spread = defaultdict(int)
    for version in Version.search([('company_id', '=', run.company_id.id)]):
        spread[str(version.date_version)] += 1
    for value, count in sorted(spread.items()):
        mark = "  <-- after the run's end date" if value > str(date_end) else ""
        print("    %-14s %4s version(s)%s" % (value, count, mark))

env.cr.rollback()
title("read only - the transaction was rolled back")
