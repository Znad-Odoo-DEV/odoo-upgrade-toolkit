"""Give a contract the dates it is missing, and never write one that has expired.

    cd ~/src/user

    # report only:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/fix_contract_gaps.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/fix_contract_gaps.py

WHAT hr.version DOES, AND WHY THE FIRST TWO ATTEMPTS AT THIS WERE WRONG

  hr/models/hr_version.py::_check_dates walks every other version of the same
  employee looking for an overlapping contract period, and allows exactly one:

      if date_start == version.contract_date_start and date_to == contract_date_end:
          contract_period_exists = True   # two versions of one contract

  So contract dates belong to the CONTRACT, not the version - every version of
  one contract carries the identical pair. Writing a joining date onto a version
  whose siblings already hold a period invents a second, overlapping contract,
  and the first attempt died on the first employee it reached.

  Copying the sibling's period verbatim satisfies the constraint - and would
  have been the second mistake. Those periods end 2026-06-06, 2026-07-13 and
  2026-07-14: three dates shared by fifty four people, an import artefact,
  and all of them before the pay period. Copying them writes fifty four
  contracts that expired last month, which is precisely the defect section 3
  exists to clear.

  THE INVARIANT, THEREFORE: this never writes a contract that ends before the
  period. Not from a sibling, not from a renewal, not from a joining date.
  A tool that manufactures the fault it was written to remove is worse than no
  tool, because the report afterwards says it succeeded.

WHERE A DATE COMES FROM, IN ORDER

  1. a sibling version's period, copied exactly, WHEN IT IS STILL CURRENT.
  2. a sibling version's period, RENEWED, when it expired before the period and
     the employee shows they are still here - a punch inside the period, or a
     payslip from either payroll this month. Same evidence standard as section
     3, because it is the same question: did this person leave?

     A renewal rewrites every version of that contract in ONE write, which is
     what makes it legal - the check excludes ('id', 'not in', self.ids), so
     versions written together are invisible to each other. Written one at a
     time they would collide on the intermediate state.
  3. ssc.employee.joining_date - the field the leave allocations were built from.
  4. the first punch in hr.attendance. Not a hiring date; a day they were
     provably at work, which beats an empty field, because Odoo generates no
     work day whatsoever for a contract with no start.

  A stale sibling period with no sign the employee is still here is left alone
  and reported. So is anybody with no sibling, no joining date and no punch.

  Invented and renewed periods run SSC_TERM_MONTHS (24 by default), rolled in
  whole terms until they land after the period.

ALSO

  A structure type belonging to another company, moved to the same suffix under
  the employee's own company, so their population is preserved.

  An end date on somebody plainly still here - punching in the period AND paid
  by ssc. Both signals or neither.

EVERY WRITE IS ITS OWN SAVEPOINT

  One employee whose dates cannot be reconciled must not cost the rest theirs.
  Failures are printed with the ORM's own reason instead of aborting the run.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

from dateutil.relativedelta import relativedelta

WIDTH = 116
APPLY = os.environ.get('SSC_APPLY') == '1'
PERIOD_FROM = os.environ.get('SSC_FROM') or '2026-08-01'
PERIOD_TO = os.environ.get('SSC_TO') or '2026-08-25'
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
TERM_MONTHS = int(os.environ.get('SSC_TERM_MONTHS') or 24)

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


Employee = env['hr.employee'].sudo()
Version = env['hr.version'].sudo()
StructureType = env['hr.payroll.structure.type'].sudo()
Attendance = env['hr.attendance'].sudo()
NativeSlip = env.get('hr.payslip')
SscEmployee = env.get('ssc.employee')
SscSlip = env.get('ssc.payslip')

types_by_name = {(t.name or '').strip(): t for t in StructureType.search([])}
employees = Employee.search([])


def renewed_end(start):
    """Roll a term forward until the contract is current rather than expired."""
    end = start + relativedelta(months=TERM_MONTHS)
    while str(end) <= PERIOD_TO:
        end = end + relativedelta(months=TERM_MONTHS)
    return end


def still_here(employee):
    """The evidence that somebody did not leave, and which of it was found."""
    signals = []
    if Attendance.search_count([('employee_id', '=', employee.id),
                                ('check_in', '>=', PERIOD_FROM + ' 00:00:00'),
                                ('check_in', '<=', PERIOD_TO + ' 23:59:59')]):
        signals.append('punch')
    if NativeSlip is not None and NativeSlip.sudo().search_count(
            [('employee_id', '=', employee.id),
             ('date_from', '<=', PERIOD_TO), ('date_to', '>=', PERIOD_FROM)]):
        signals.append('native slip')
    if SscSlip is not None and SscEmployee is not None:
        profile = SscEmployee.sudo().search(
            [('hr_employee_id', '=', employee.id)], limit=1)
        if profile and SscSlip.sudo().search_count(
                [('employee_id', '=', profile.id),
                 ('month', '=', MONTH), ('year', '=', str(YEAR))]):
            signals.append('ssc slip')
    return signals


# ------------------------------------------------------- 1. the wrong company
title("1. employees on another company's structure type")

wrong_type = []
for employee in employees:
    company = employee.company_id
    structure_type = employee.sudo().structure_type_id
    if not (company and structure_type):
        continue
    name = (structure_type.name or '').strip()
    company_name = (company.name or '').strip()
    if name.startswith(company_name):
        continue
    # Keep whichever population they are in; only the company is wrong.
    suffix = name.rsplit(' ', 1)[-1] if ' ' in name else ''
    target = types_by_name.get("%s %s" % (company_name, suffix))
    wrong_type.append((employee, structure_type, target, suffix))

if not wrong_type:
    print("  none")
by_move = defaultdict(list)
for employee, current, target, suffix in wrong_type:
    key = (current.name or '?', target.name if target else "NO MATCHING TYPE")
    by_move[key].append(employee.name or '?')
for (current, target), names in sorted(by_move.items()):
    print("\n  %s  ->  %s   (%s)" % (current, target, len(names)))
    for name in sorted(names)[:20]:
        print("      %s" % name)
    if len(names) > 20:
        print("      ... and %s more" % (len(names) - 20))

# --------------------------------------------------- 2. no contract start date
title("2. contracts with no start date, and where a date comes from")

plans = []
for employee in employees:
    version = employee.sudo()
    if version.contract_date_start:
        continue
    current = version.version_id

    siblings = Version.search(
        [('employee_id', '=', employee.id),
         ('id', '!=', current.id),
         ('contract_date_start', '!=', False)],
        order='contract_date_start desc')

    if siblings:
        sibling = siblings[0]
        start, end = sibling.contract_date_start, sibling.contract_date_end

        if not end or str(end) >= PERIOD_FROM:
            plans.append({
                'employee': employee, 'source': 'sibling version - still current',
                'start': start, 'end': end, 'versions': current, 'note': ''})
            continue

        # Expired. Renewing is a claim that they are still here - so prove it.
        signals = still_here(employee)
        if not signals:
            last = Attendance.search([('employee_id', '=', employee.id)],
                                     order='check_in desc', limit=1)
            plans.append({
                'employee': employee,
                'source': 'sibling version EXPIRED %s - no sign they are here' % end,
                'start': None, 'end': None, 'versions': None,
                'note': 'last punch %s' % (last.check_in.date() if last
                                           else 'never')})
            continue

        # Every version of this contract, rewritten together or not at all.
        same_contract = Version.search([
            ('employee_id', '=', employee.id),
            ('contract_date_start', '=', start),
            ('contract_date_end', '=', end)])
        plans.append({
            'employee': employee,
            'source': 'sibling version RENEWED (was %s)' % end,
            'start': start, 'end': renewed_end(end),
            'versions': current | same_contract,
            'note': "+".join(signals)})
        continue

    joining = False
    if SscEmployee is not None:
        profile = SscEmployee.sudo().search(
            [('hr_employee_id', '=', employee.id)], limit=1)
        joining = profile.joining_date if profile else False
    if joining:
        plans.append({
            'employee': employee, 'source': 'joining date',
            'start': joining, 'end': renewed_end(joining),
            'versions': current, 'note': ''})
        continue

    first = Attendance.search(
        [('employee_id', '=', employee.id)], order='check_in asc', limit=1)
    if first:
        punched = first.check_in.date()
        plans.append({
            'employee': employee, 'source': 'first punch',
            'start': punched, 'end': renewed_end(punched),
            'versions': current, 'note': ''})
        continue

    plans.append({
        'employee': employee, 'source': 'NOTHING TO USE',
        'start': None, 'end': None, 'versions': None, 'note': 'left alone'})

if not plans:
    print("  none")
by_source = defaultdict(list)
for plan in plans:
    by_source[plan['source'].split(' - ')[0] if plan['start'] is None
              else plan['source']].append(plan)
for source, rows in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
    print("\n  %s   (%s)" % (source, len(rows)))
    for plan in sorted(rows, key=lambda p: p['employee'].name or ''):
        employee = plan['employee']
        if plan['start']:
            versions = len(plan['versions'])
            print("      %-44s %-28s %s -> %s%s%s"
                  % ((employee.name or '?')[:44],
                     (employee.company_id.name or '-')[:28],
                     plan['start'], plan['end'] or 'open',
                     "   [%s]" % plan['note'] if plan['note'] else '',
                     "   %s versions" % versions if versions > 1 else ''))
        else:
            print("      %-44s %-28s %s"
                  % ((employee.name or '?')[:44],
                     (employee.company_id.name or '-')[:28], plan['note']))

# A control for the three queries behind "no sign they are here". Fifty two
# employees with no evidence at all is either the truth or a broken domain, and
# the report reads identically either way - so count the same signals across
# the whole company and let the numbers say which it is.
title("2b. do the evidence queries find anything at all?", '-')
punchers = set(Attendance.search(
    [('check_in', '>=', PERIOD_FROM + ' 00:00:00'),
     ('check_in', '<=', PERIOD_TO + ' 23:59:59')]).mapped('employee_id').ids)
print("  %5s employee(s) punched between %s and %s"
      % (len(punchers), PERIOD_FROM, PERIOD_TO))
if NativeSlip is not None:
    print("  %5s native payslip(s) cover the period"
          % NativeSlip.sudo().search_count(
              [('date_from', '<=', PERIOD_TO), ('date_to', '>=', PERIOD_FROM)]))
if SscSlip is not None:
    print("  %5s ssc payslip(s) for %s-%s"
          % (SscSlip.sudo().search_count(
              [('month', '=', MONTH), ('year', '=', str(YEAR))]), MONTH, YEAR))
stale = [p for p in plans if 'EXPIRED' in p['source']]
if stale:
    overlap = len([p for p in stale if p['employee'].id in punchers])
    print("")
    print("  of the %s with an expired sibling period, %s punched in the period"
          % (len(stale), overlap))
    print("  (that number must be 0 for them all to read 'no sign they are here')")

# The invariant, checked rather than asserted.
expired = [p for p in plans if p['end'] and str(p['end']) < PERIOD_FROM]
print("\n  contracts this would write ending before %s: %s"
      % (PERIOD_FROM, len(expired)))
if expired:
    print("  !! REFUSING TO WRITE THESE - the invariant is broken, fix the tool")
    for plan in expired:
        print("     %s -> %s" % (plan['employee'].name, plan['end']))

# The same person twice is a data problem no date can fix; say so.
seen = defaultdict(list)
for plan in plans:
    seen[(plan['employee'].name or '?').strip().lower()].append(plan['employee'])
duplicates = {name: people for name, people in seen.items() if len(people) > 1}
if duplicates:
    print("\n  !! the same name on more than one hr.employee - punches and leave")
    print("     are split between the records, and dating both does not merge them:")
    for name, people in sorted(duplicates.items()):
        print("       %s  (ids %s)" % (people[0].name,
                                       ", ".join(str(p.id) for p in people)))

# ------------------------------------------- 3. ended contracts: evidence only
title("3. contracts that ended before the period")

ended = []
for employee in employees:
    version = employee.sudo()
    end = version.contract_date_end
    if not (end and str(end) < PERIOD_FROM):
        continue
    punches = Attendance.search(
        [('employee_id', '=', employee.id)], order='check_in desc', limit=1)
    last = punches.check_in.date() if punches else None
    paid_by_ssc = False
    if SscSlip is not None and SscEmployee is not None:
        profile = SscEmployee.sudo().search(
            [('hr_employee_id', '=', employee.id)], limit=1)
        if profile:
            paid_by_ssc = bool(SscSlip.sudo().search_count([
                ('employee_id', '=', profile.id),
                ('month', '=', MONTH), ('year', '=', str(YEAR))]))
    ended.append((employee, end, last, paid_by_ssc))

if not ended:
    print("  none")
else:
    print("  %-40s %-26s %-12s %-12s %s"
          % ("employee", "company", "ended", "last punch", "ssc paid this month"))
    print("  " + "-" * (WIDTH - 4))
    for employee, end, last, paid in sorted(ended, key=lambda r: str(r[2] or '')):
        flag = ""
        if last and str(last) >= PERIOD_FROM and paid:
            flag = "   <-- WILL BE CLEARED: punching in the period and paid by ssc"
        elif last and str(last) >= PERIOD_FROM:
            flag = "   <-- punching, but ssc did not pay - left alone"
        elif paid:
            flag = "   <-- ssc paid them, but no punch since - left alone"
        print("  %-40s %-26s %-12s %-12s %-5s%s"
              % ((employee.name or '?')[:40], (employee.company_id.name or '-')[:26],
                 end, last or '-', "yes" if paid else "no", flag))
    print("""
  Both signals or neither. A punch inside the period says they are here; an ssc
  payslip says the company thinks so too. One without the other is left alone,
  because clearing an end date on somebody who left puts them back on the
  payroll.""")

# ----------------------------------------------------------------------- write
title("summary")
datable = [p for p in plans if p['start'] and not (
    p['end'] and str(p['end']) < PERIOD_FROM)]
print("  %s employee(s) on another company's structure type" % len(wrong_type))
print("  %s contract(s) with no start date, %s of them datable"
      % (len(plans), len(datable)))
for source, rows in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
    print("        %4s  %s" % (len(rows), source))
renewals = [p for p in datable if 'RENEWED' in p['source']]
if renewals:
    print("  %s of those are RENEWALS - they also rewrite the end date on %s"
          % (len(renewals), sum(len(p['versions']) for p in renewals)))
    print("        existing version(s) of the same contract, in one write each")
dated_here = {p['employee'].id for p in datable}
to_clear = [row for row in ended
            if row[2] and str(row[2]) >= PERIOD_FROM and row[3]
            and row[0].id not in dated_here]
print("  %s contract(s) ended before the period, %s of them to be cleared"
      % (len(ended), len(to_clear)))
print("  renewal term: %s months, rolled until the contract lands after %s"
      % (TERM_MONTHS, PERIOD_TO))

if not APPLY:
    env.cr.rollback()
    print("\n  report only - nothing written. Re-run with SSC_APPLY=1.")
else:
    moved = dated = cleared = 0
    failures = []

    def attempt(name, what, write):
        """One write, one savepoint. A record that refuses costs only itself."""
        try:
            with env.cr.savepoint():
                write()
            return True
        except Exception as error:  # noqa: BLE001
            failures.append((name, what, str(error).strip().splitlines()[0]))
            return False

    for employee, _current, target, _suffix in wrong_type:
        if not target:
            continue
        if attempt(employee.name or '?', "structure type",
                   lambda e=employee, t=target: e.sudo().write(
                       {'structure_type_id': t.id})):
            moved += 1

    for plan in datable:
        values = {'contract_date_start': plan['start']}
        if plan['end']:
            values['contract_date_end'] = plan['end']
        if attempt(plan['employee'].name or '?',
                   plan['source'].split(' (')[0].split(' - ')[0],
                   lambda v=plan['versions'], d=values: v.write(d)):
            dated += 1

    for employee, _end, _last, _paid in to_clear:
        if attempt(employee.name or '?', "clear end date",
                   lambda e=employee: e.sudo().write({'contract_date_end': False})):
            cleared += 1

    env.cr.commit()
    print("\n  %s moved onto their own company's structure type" % moved)
    print("  %s contract(s) given dates" % dated)
    print("  %s end date(s) cleared - punching in the period and paid by ssc"
          % cleared)

    if failures:
        print("\n  %s record(s) refused the write, and were left as they were:"
              % len(failures))
        for name, what, reason in failures:
            print("    %-40s %-26s %s" % (name[:40], what[:26], reason[:42]))

    print("\n  A contract date does not reach a payslip that is already computed."
          "\n  Regenerate the work entries for anybody whose dates changed, then"
          "\n  recompute their payslip.")
