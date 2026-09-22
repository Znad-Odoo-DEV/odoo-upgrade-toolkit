"""Recompute the payslips now that the work entries under them are correct.

    cd ~/src/user

    # report only:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/recompute_payslips.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/recompute_payslips.py

rebuild_overtime_lines.py worked. Kamlesh Ramkaran's August now reads

    2026-08-01  SSC Overtime - Off Day[cancelled] 9.1h,  Attendance[draft] 8.0h
    2026-08-02  Attendance[draft] 8.0h,  SSC Overtime - Off Day[cancelled] 9.0h

- the off-day entries cancelled and real Attendance in their place, with
Parfait even picking up SSC Overtime - Working on the day he did an extra hour.
The classification is right.

The payslips are not. They still read 3.00 days and 198.79 off-day overtime
hours, because the compute_sheet inside that script ran in the same pass that
had just created the entries and read what was there when it started. Work
entries and the payslip that consumes them cannot be fixed in one breath: the
recompute has to come after everything under it has settled.

So this refreshes and recomputes, over draft labour payslips for the period.
Both, in that order, because they do different things: compute_sheet applies the
salary rules to the worked-days lines the payslip already holds, while
action_refresh_from_work_entries - the Recompute Whole Sheet button - rebuilds
those lines from the work entries underneath.

Parfait Uwanshuti proved the difference. His work entries are 21 Attendance in
draft with the off-day ones cancelled, exactly as intended, and his payslip
still carried the old "SSC Overtime - Off Days 24.55 days" line and no
Attendance line whatsoever. Every compute_sheet run over him applied the rules
faithfully to stale input, and the proration floor added afterwards then read
covered = 0 and paid him nothing at all.

active_test=True throughout so no archived rule - LEAVESAL among them - is seen.
Days and net are printed before against after, and a payslip that does not move
is visible as one that did not move rather than counted as done.

Validated and paid payslips are listed and left alone.

Reads only unless SSC_APPLY=1.
"""
import os

from dateutil.relativedelta import relativedelta

WIDTH = 112
APPLY = os.environ.get('SSC_APPLY') == '1'
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
SUFFIX = os.environ.get('SSC_SUFFIX') or 'Labour Pay'
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or 'SAUD,ROYAL ARROW').split(',')
        if n.strip()]

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


Payslip = env['hr.payslip'].sudo()


def days_in_month_of(value):
    first = value.replace(day=1)
    return ((first + relativedelta(months=1)) - first).days


def read(slip):
    parts = {}
    for line in slip.line_ids:
        parts[line.code or '?'] = parts.get(line.code or '?', 0.0) + line.total
    wage = slip.employee_id.sudo().version_id.wage or 0.0
    month_days = days_in_month_of(slip.date_to) if slip.date_to else 0
    days = (parts.get('BASIC', 0.0) / wage * month_days) if wage else 0.0
    return days, parts.get('NET', 0.0)


slips = Payslip.search([]).filtered(
    lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
    and str(s.date_from.year) == str(YEAR)
    and (s.struct_id.name or '').endswith(SUFFIX)
    and s.state != 'cancel'
    and any(p in (s.employee_id.company_id.name or '').upper() for p in ONLY))

draft = slips.filtered(lambda s: s.state == 'draft')
locked = slips - draft

title("%s-%s %s payslips in %s" % (MONTH, YEAR, SUFFIX, ", ".join(ONLY)))
print("  %s payslip(s), %s in draft" % (len(slips), len(draft)))
if locked:
    print("  %s NOT recomputed - not in draft:" % len(locked))
    for slip in locked:
        print("      %-44s %s" % ((slip.employee_id.name or '?')[:44], slip.state))

if not APPLY:
    env.cr.rollback()
    print("")
    print("  report only - nothing written. Re-run with SSC_APPLY=1.")
else:
    moved, still = [], 0
    failures = []
    for index, slip in enumerate(draft, start=1):
        before_days, before_net = read(slip)
        try:
            # compute_sheet reads the worked-days lines that are already
            # on the payslip; it does not rebuild them from the work
            # entries. Parfait Uwanshuti's entries are 21 Attendance in
            # draft with the off-day ones cancelled, and his payslip
            # still carried the old off-day worked-days line and no
            # Attendance line at all. action_refresh_from_work_entries -
            # the Recompute Whole Sheet button - is what re-reads them.
            live = slip.with_context(active_test=True)
            live.action_refresh_from_work_entries()
            live.compute_sheet()
            after_days, after_net = read(slip)
            if (abs(after_days - before_days) > 0.005
                    or abs(after_net - before_net) > 0.005):
                moved.append((slip.employee_id.name or '?', before_days,
                              after_days, before_net, after_net))
            else:
                still += 1
        except Exception as error:  # noqa: BLE001
            failures.append((slip.employee_id.name or '?',
                             str(error).strip().splitlines()[0]))
        if index % 25 == 0:
            env.cr.commit()
            print("  -- committed %s of %s --" % (index, len(draft)))
    env.cr.commit()

    title("what moved")
    print("  %-40s %8s %8s   %12s %12s"
          % ("employee", "days b", "days a", "net before", "net after"))
    print("  " + "-" * (WIDTH - 4))
    for name, days_b, days_a, net_b, net_a in sorted(
            moved, key=lambda r: -abs(r[4] - r[3])):
        print("  %-40s %8.2f %8.2f   %s %s"
              % (name[:40], days_b, days_a, num(net_b), num(net_a)))

    title("summary")
    print("  %s recomputed, %s moved, %s unchanged" % (len(draft), len(moved), still))
    if failures:
        print("  %s refused:" % len(failures))
        for name, reason in failures:
            print("    %-40s %s" % (name[:40], reason[:56]))
    print("")
    print("  Re-run compare_days_overtime.py and reconcile_payrolls.py.")
