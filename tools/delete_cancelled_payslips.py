"""Delete the cancelled payslips, rather than leaving them in the list.

    cd ~/src/user

    # report only:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/delete_cancelled_payslips.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/delete_cancelled_payslips.py

stop_paying_leavers.py cancelled thirty three payslips for people who left. A
cancelled payslip pays nothing - it cannot be validated and never reaches the
WPS file - but it stays in the list, it is still counted by anything that
selects on structure and date, and it is one more record between somebody and
the payslip they are looking for.

WHAT IT DELETES, AND WHAT IT WILL NOT

  Only payslips already in state 'cancel', only for the period, only in the
  named companies, only on the named structure. A draft payslip is somebody's
  unfinished work and a validated or paid one is a record of money; neither is
  touched, and both are counted in the report so the difference is visible.

  Deleting is not reversible. Cancelling was - that is why it came first, and
  why this is a separate command run after the list has been read. If the wrong
  person was cancelled, set that payslip back to draft before running this.

THIS DOES NOT NEED THE PAY RUN REDONE

  Regenerating the run would discard every input moved, every rule fixed and
  every payslip recomputed today. The run itself is sound; these thirty three
  records are the only thing wrong with it, and removing them is the whole job.

Reads only unless SSC_APPLY=1.
"""
import os

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

in_scope = Payslip.search([]).filtered(
    lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
    and str(s.date_from.year) == str(YEAR)
    and (s.struct_id.name or '').endswith(SUFFIX)
    and any(p in (s.employee_id.company_id.name or '').upper() for p in ONLY))

cancelled = in_scope.filtered(lambda s: s.state == 'cancel')
by_state = {}
for slip in in_scope:
    by_state[slip.state] = by_state.get(slip.state, 0) + 1

title("%s-%s %s in %s" % (MONTH, YEAR, SUFFIX, ", ".join(ONLY)))
print("  %s payslip(s) in scope, by state:" % len(in_scope))
for state, count in sorted(by_state.items(), key=lambda kv: -kv[1]):
    mark = "   <-- to be deleted" if state == 'cancel' else "   kept"
    print("      %-14s %5s%s" % (state, count, mark))

title("the cancelled ones, in full")
print("  %-46s %12s %s" % ("employee", "net", "pay run"))
print("  " + "-" * (WIDTH - 4))
for slip in cancelled.sorted(lambda s: s.employee_id.name or ''):
    net = sum(line.total for line in slip.line_ids if line.code == 'NET')
    print("  %-46s %s %s"
          % ((slip.employee_id.name or '?')[:46], num(net),
             (slip.payslip_run_id.name or '-')[:34]
             if 'payslip_run_id' in slip._fields else '-'))

title("summary")
print("  %s cancelled payslip(s) would be deleted" % len(cancelled))
print("  %s draft, validated or paid payslip(s) are kept"
      % (len(in_scope) - len(cancelled)))
print("")
print("  Deleting is not reversible. Cancelling was, which is why it came")
print("  first. Anybody cancelled by mistake should be set back to draft")
print("  before this runs.")

if not APPLY:
    env.cr.rollback()
    print("")
    print("  report only - nothing written. Re-run with SSC_APPLY=1.")
elif not cancelled:
    env.cr.rollback()
    print("")
    print("  nothing to delete")
else:
    names = [(s.employee_id.name or '?') for s in cancelled]
    deleted, failures = 0, []
    for slip in cancelled:
        name = slip.employee_id.name or '?'
        try:
            with env.cr.savepoint():
                slip.unlink()
            deleted += 1
        except Exception as error:  # noqa: BLE001
            failures.append((name, str(error).strip().splitlines()[0]))
    env.cr.commit()
    title("done")
    print("  %s payslip(s) deleted of %s" % (deleted, len(names)))
    if failures:
        print("  %s refused - Odoo would not delete them:" % len(failures))
        for name, reason in failures:
            print("    %-42s %s" % (name[:42], reason[:56]))
        print("")
        print("  A payslip Odoo refuses to delete is usually one that is no")
        print("  longer in cancel state, or one an accounting entry points at.")
    print("")
    print("  The pay run itself is untouched and does not need regenerating.")
