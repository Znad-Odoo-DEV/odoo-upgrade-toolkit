"""Payslips for people who left: no punch, no attendance, and ssc pays nothing.

    cd ~/src/user

    # report only:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/stop_paying_leavers.py

    # cancel the payslips (reversible - a cancelled payslip goes back to draft):
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/stop_paying_leavers.py

    # and close their contracts at their last punch (NOT reversible by a click):
    SSC_APPLY=1 SSC_END=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/stop_paying_leavers.py

Mandeep Singh Raj Singh's August payslip pays 96.77 - 1,000 x 3/31, three days.
He holds seven Attendance work entries, every one cancelled, totalling 0.0
hours, and no worked-days lines at all. ssc_payroll made him no payslip because
he has no attendance. Odoo made him one because his contract is open and a pay
run never consults ssc.employee.

Three days on zero attendance is the part that is actually wrong. It is the
same 3.00 that Kamlesh, Parfait and Ahmad Ali Sameu showed before their
overtime lines were rebuilt, so it is what the proration rule returns when it
finds nothing to read - a floor, not a calculation.

WHO THIS SELECTS

  A native labour payslip for the period whose employee has NO live work entry
  in it - cancelled ones do not count - AND no ssc payslip for the month, AND
  whose last punch anywhere is before the period starts.

  The third condition was missing on the first run and it matters. Ahmad Badri
  Khaled satisfied both of the others and last punched 2026-08-26, the day
  before. Cancelling his payslip would have been recoverable; closing his
  contract at that date would have cut off his pay. A punch on or after the
  period start outranks every other signal, and those employees are listed and
  skipped.

TWO ACTIONS, DELIBERATELY SEPARATE

  SSC_APPLY cancels the payslips. A cancelled payslip is set back to draft in
  one click, so this is the safe half and it stops the money this month.

  SSC_END additionally writes contract_date_end, and only for somebody who has
  punched at some point - their last punch is the date. It is the structural
  fix and it stops them appearing next month too, but a wrong end date on
  somebody still employed cuts off their pay, so it is opt-in and it never
  invents a date for a person with no punch in the record at all.

Reads only unless SSC_APPLY=1.
"""
import os

WIDTH = 118
APPLY = os.environ.get('SSC_APPLY') == '1'
END = os.environ.get('SSC_END') == '1'
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


def num(value, width=10):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


Payslip = env['hr.payslip'].sudo()
WorkEntry = env['hr.work.entry'].sudo()
Attendance = env['hr.attendance'].sudo()
SscEmployee = env.get('ssc.employee')
SscSlip = env.get('ssc.payslip')

rows = []
still_here = []
for slip in Payslip.search([]):
    if not (slip.date_from and slip.date_from.strftime('%b').upper() == MONTH
            and str(slip.date_from.year) == str(YEAR)):
        continue
    if not (slip.struct_id.name or '').endswith(SUFFIX):
        continue
    employee = slip.employee_id
    if ONLY and not any(p in (employee.company_id.name or '').upper()
                        for p in ONLY):
        continue

    live = WorkEntry.search_count([
        ('employee_id', '=', employee.id),
        ('date', '>=', str(slip.date_from)), ('date', '<=', str(slip.date_to)),
        ('state', '!=', 'cancelled')])
    if live:
        continue

    profile = SscEmployee.sudo().search(
        [('hr_employee_id', '=', employee.id)], limit=1) \
        if SscEmployee is not None else None
    paid_by_ssc = bool(SscSlip.sudo().search_count(
        [('employee_id', '=', profile.id), ('month', '=', MONTH),
         ('year', '=', str(YEAR))])) if (SscSlip is not None and profile) else False
    if paid_by_ssc:
        continue

    last = Attendance.search([('employee_id', '=', employee.id)],
                             order='check_in desc', limit=1)
    last_punch = last.check_in.date() if last else None
    # A punch on or after the period start contradicts having left before it.
    # Ahmad Badri Khaled last punched 2026-08-26 - the day before this ran -
    # with no entries inside 1..25 August and no ssc payslip, so both of the
    # original signals were true of him and he has plainly not left.
    if last_punch and str(last_punch) >= str(slip.date_from):
        still_here.append((employee, last_punch, slip))
        continue
    version = employee.sudo().version_id
    rows.append({
        'slip': slip, 'employee': employee, 'version': version,
        'net': sum(l.total for l in slip.line_ids if l.code == 'NET'),
        'last_punch': last_punch,
        'cancelled_entries': WorkEntry.search_count([
            ('employee_id', '=', employee.id),
            ('date', '>=', str(slip.date_from)),
            ('date', '<=', str(slip.date_to))]),
        'is_cancelled': profile.is_cancelled if (
            profile and 'is_cancelled' in profile._fields) else None,
        'contract_end': version.contract_date_end,
    })

rows.sort(key=lambda r: -r['net'])

title("%s-%s %s: paid by Odoo, no live work entry, no ssc payslip"
      % (MONTH, YEAR, SUFFIX))
print("  %s payslip(s), %s in total" % (len(rows), num(sum(r['net'] for r in rows))))
print("")
print("  %-38s %10s %12s %9s %11s %s"
      % ("employee", "net", "last punch", "entries", "ssc cancel", "contract end"))
print("  " + "-" * (WIDTH - 4))
for row in rows:
    print("  %-38s %s %12s %9s %11s %s"
          % ((row['employee'].name or '?')[:38], num(row['net']),
             row['last_punch'] or 'never', row['cancelled_entries'],
             row['is_cancelled'], row['contract_end'] or 'open'))

if still_here:
    title("excluded - punched on or after %s, so they have not left"
          % (still_here[0][2].date_from), '-')
    for employee, punch, slip in still_here:
        print("  %-42s last punch %s   net %s"
              % ((employee.name or '?')[:42], punch,
                 num(sum(l.total for l in slip.line_ids if l.code == 'NET'))))
    print("")
    print("  Both original signals were true of these - no live work entry in")
    print("  the period and no ssc payslip - and they are here anyway. A punch")
    print("  after the period start outranks both.")

datable = [r for r in rows if r['last_punch']]
undatable = [r for r in rows if not r['last_punch']]
title("summary")
print("  %s payslip(s) would be cancelled, worth %s"
      % (len(rows), num(sum(r['net'] for r in rows))))
print("  %s of them have a last punch to close the contract at" % len(datable))
if undatable:
    print("  %s have never punched at all - no end date will be invented:"
          % len(undatable))
    for row in undatable[:12]:
        print("      %-42s net %s" % ((row['employee'].name or '?')[:42],
                                      num(row['net'])))
    if len(undatable) > 12:
        print("      ... and %s more" % (len(undatable) - 12))
print("")
print("  Note: three days on zero attendance is what the proration rule returns")
print("  when it finds nothing to read. Cancelling these stops the money now;")
print("  the rule's floor is a separate question and still open.")

if not APPLY:
    env.cr.rollback()
    print("")
    print("  report only - nothing written. SSC_APPLY=1 cancels the payslips,")
    print("  SSC_END=1 as well closes the contracts at the last punch.")
else:
    cancelled = ended = 0
    failures = []
    for row in rows:
        slip = row['slip']
        try:
            with env.cr.savepoint():
                if slip.state != 'cancel':
                    slip.action_payslip_cancel()
                    cancelled += 1
                if END and row['last_punch'] and not row['contract_end']:
                    row['version'].write(
                        {'contract_date_end': row['last_punch']})
                    ended += 1
        except Exception as error:  # noqa: BLE001
            failures.append((row['employee'].name or '?',
                             str(error).strip().splitlines()[0]))
    env.cr.commit()
    title("done")
    print("  %s payslip(s) cancelled" % cancelled)
    print("  %s contract(s) closed at the last punch" % ended)
    if not END:
        print("  contracts untouched - re-run with SSC_END=1 to close them, or")
        print("  they will be offered again next month")
    if failures:
        print("  %s refused:" % len(failures))
        for name, reason in failures:
            print("    %-42s %s" % (name[:42], reason[:56]))
