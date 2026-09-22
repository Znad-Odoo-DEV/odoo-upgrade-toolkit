"""Rebuild the work entries for anybody whose contract dates changed.

    cd ~/src/user

    # report only:
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/regenerate_work_entries.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/regenerate_work_entries.py

reconcile_payrolls.py has the adjustments matching to a fils on Royal Arrow and
four employees out on Saud, three of them annual leave salary. What is left in
the money is days, and the three worst cases are the three whose contract end
dates were cleared this morning:

    Parfait Uwanshuti    ssc 24.98 days   native  3.00   +3,262
    Kamlesh Ramkaran     ssc 24.99        native  3.00   +1,210
    Ahmad Ali Sameu      ssc 16.00        native  3.00   +1,194

Parfait's payslip carries no worked-days lines at all. Odoo generated his work
entries while his contract still ended in July, so it made three days and
stopped, and Compute Sheet will not fix that: it computes the entries that
exist, it does not create the ones that should. hr.version.generate_work_entries
does, and nothing has called it since the dates were repaired.

WHY THE FIRST RUN CHANGED NOTHING

  generate_work_entries(date_start, date_stop) without force compares the range
  against date_generated_from and date_generated_to on the version, decides
  August is already covered, and returns. All fifty four came back with the day
  count and the net unchanged, including the three that hold no work entry at
  all - Odoo had recorded the period as generated even though the contract
  dates at the time produced almost nothing.

  hr_version._generate_work_entries takes force=True, which nullifies the
  existing entries over the range and rebuilds them. It skips any entry in
  state='validated', so approved time is not silently rewritten.

  Note also, from the same method:

      if not version.contract_date_start:
          continue

  A version with no contract start date generates no work entry whatsoever,
  which is why Kamlesh, Parfait and Ahmad Ali Sameu had none: their contracts
  were ended, then dateless, when Odoo last generated for them.

WHAT IT DOES

  For every employee whose ssc day count and native day count disagree by more
  than SSC_TOLERANCE days, calls generate_work_entries over the pay period on
  their version, then recomputes the payslip, and reports the days and the net
  before and against after.

  It works from the day gap rather than from a list of names, because the three
  known cases are not necessarily all of them - anybody given a contract start
  date this morning is in the same position and was never named.

DRAFT PAYSLIPS ONLY

  A validated or paid payslip is not recomputed. Its numbers have been agreed
  and possibly posted, and quietly changing them under a reconciliation script
  is not a repair. Those are listed instead.

Reads only unless SSC_APPLY=1.
"""
import os

from dateutil.relativedelta import relativedelta

WIDTH = 116
APPLY = os.environ.get('SSC_APPLY') == '1'
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
TOL = float(os.environ.get('SSC_TOLERANCE') or 0.5)
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or 'SAUD,ROYAL ARROW').split(',')
        if n.strip()]

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

BASE_CODES = ('BASIC', 'HOUALLOW', 'TRAALLOW', 'OTALLOW')


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value):
    return "{:>11,.2f}".format(value or 0.0)


NativeSlip = env['hr.payslip'].sudo()
SscSlip = env['ssc.payslip'].sudo()
WorkEntry = env['hr.work.entry'].sudo()


def days_in_month_of(value):
    first = value.replace(day=1)
    return ((first + relativedelta(months=1)) - first).days


# ------------------------------------------------------------- pair them up
rows = []
for slip in SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR)),
                            ('is_staff', '=', False)]):
    employee = slip.employee_id.hr_employee_id
    if not employee:
        continue
    if ONLY and not any(p in (employee.company_id.name or '').upper()
                        for p in ONLY):
        continue
    native = NativeSlip.search([('employee_id', '=', employee.id)]).filtered(
        lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
        and str(s.date_from.year) == str(YEAR)
        and (s.struct_id.name or '').endswith('Labour Pay'))
    if not native:
        continue
    native = native[0]
    wage = employee.sudo().version_id.wage or 0.0
    parts = {}
    for line in native.line_ids:
        parts[line.code or '?'] = line.total
    month_days = days_in_month_of(native.date_to) if native.date_to else 0
    basic = parts.get('BASIC', 0.0)
    native_days = (basic / wage * month_days) if wage else 0.0
    gap = (slip.total_attendance or 0.0) - native_days
    if abs(gap) <= TOL:
        continue
    rows.append({'employee': employee, 'native': native, 'ssc': slip,
                 'native_days': native_days, 'gap': gap,
                 'net': parts.get('NET', 0.0),
                 'entries': WorkEntry.search_count([
                     ('employee_id', '=', employee.id),
                     ('date', '>=', str(native.date_from)),
                     ('date', '<=', str(native.date_to))])})

rows.sort(key=lambda r: -abs(r['gap']))

title("employees whose two day counts disagree by more than %s day(s)" % TOL)
print("  %s of them" % len(rows))
print("")
print("  %-38s %8s %8s %8s %7s %8s %s"
      % ("employee", "ssc days", "nat days", "gap", "entries", "state", "net"))
print("  " + "-" * (WIDTH - 4))
for row in rows:
    print("  %-38s %8.2f %8.2f %8.2f %7s %8s %s"
          % ((row['employee'].name or '?')[:38],
             row['ssc'].total_attendance or 0.0, row['native_days'],
             row['gap'], row['entries'], row['native'].state,
             num(row['net'])))

draft = [r for r in rows if r['native'].state == 'draft']
locked = [r for r in rows if r['native'].state != 'draft']
title("summary")
print("  %s draft payslip(s) would be rebuilt" % len(draft))
if locked:
    print("  %s NOT touched - not in draft:" % len(locked))
    for row in locked:
        print("      %-40s %s" % ((row['employee'].name or '?')[:40],
                                  row['native'].state))
print("  %s employee(s) hold no work entry at all in the period"
      % len([r for r in rows if not r['entries']]))

if not APPLY:
    env.cr.rollback()
    print("")
    print("  report only - nothing written. Re-run with SSC_APPLY=1.")
else:
    rebuilt = 0
    failures = []
    for row in draft:
        native = row['native']
        employee = row['employee']
        before_days, before_net = row['native_days'], row['net']
        try:
            with env.cr.savepoint():
                version = employee.sudo().version_id
                # force=True is the whole point. Without it the method
                # compares the range against date_generated_from /
                # date_generated_to on the version and returns having
                # done nothing - which is what the first run did, on all
                # fifty four. With it, hr_version._generate_work_entries
                # nullifies the existing entries in the range and rebuilds
                # them, and it excludes state='validated' while doing so.
                version.generate_work_entries(
                    native.date_from, native.date_to, force=True)
                native.with_context(active_test=True).compute_sheet()
            rebuilt += 1
            after = {l.code or '?': l.total for l in native.line_ids}
            wage = employee.sudo().version_id.wage or 0.0
            month_days = days_in_month_of(native.date_to)
            after_days = (after.get('BASIC', 0.0) / wage * month_days) \
                if wage else 0.0
            print("  %-38s days %6.2f -> %6.2f   net %s -> %s"
                  % ((employee.name or '?')[:38], before_days, after_days,
                     num(before_net), num(after.get('NET'))))
        except Exception as error:  # noqa: BLE001
            failures.append((employee.name or '?',
                             str(error).strip().splitlines()[0]))
    env.cr.commit()
    title("done")
    print("  %s payslip(s) rebuilt" % rebuilt)
    if failures:
        print("  %s refused:" % len(failures))
        for name, reason in failures:
            print("    %-40s %s" % (name[:40], reason[:56]))
    print("")
    print("  Re-run reconcile_payrolls.py - the day column is the one to watch.")
