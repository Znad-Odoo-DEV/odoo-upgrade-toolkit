"""Let go, in Odoo, of the people who already left.

    odoo-bin shell -d <database> --no-http < tools/close_cancelled_employees.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/close_cancelled_employees.py

Eighty four people are marked cancelled in ssc_payroll and are still live
employees here. They sit in every headcount, they would each be handed a
payslip, and none of them can be paid a gratuity - because End of Service only
computes for somebody archived with a departure reason, and they are neither.

WHEN DID THEY LEAVE

Not on the day the record says. Every one of the eighty five carries a last day
of 31 December 2024, to the day, including three who were paid in July 2026 -
so the field is a default somebody's import wrote once, not a date.

What is left is evidence: the last time they touched a clock, and the last
period they were paid for. Whichever is later is the earliest day they can have
left, since nobody is paid for a month they were not there. It spreads across
March 2025 to July 2026, which is what a real leaving pattern looks like.

Six have neither - never punched, never paid - and are printed and left alone.
A person has to say what happened to them.

WHY THEY LEFT

The data knows in seventy six cases: an approved notice of resignation, so
Resigned. The other eight had a contract cancelled with no notice on file, and
between Fired and Resigned there is no honest guess, so they get a reason that
says only what is known - the contract was cancelled. Under Decree-Law 33 the
gratuity is identical either way, so this changes the record and not the money.

ONE MAN IS NOT IN THIS LIST

Ebrahim Mohamad Alzenad has an approved notice and no cancellation, and he
punched five times since July. He is working out his notice. Cancelling him
would stop the pay of somebody who is still turning up.

WHAT IS WRITTEN

The departure date and reason, an end date on the contract so Out of Contract
stops paying for days after it, and the archive flag that both takes them out
of the lists and lets End of Service compute. Four things, and the gratuity
needs all four.
"""
import os
from datetime import date

APPLY = os.environ.get('SSC_APPLY') == '1'

NEUTRAL_REASON = 'Contract Cancelled'

# Left alone whatever the flags say. This is the employee record behind the
# account running this: archiving it takes that person's attendance, time off
# and everything else hung on the record with it, and no flag is worth that.
KEEP = ['Ebrahim Mohamad Alzenad']

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
))

Employee = env['hr.employee'].sudo()
Attendance = env['hr.attendance'].sudo()
Reason = env['hr.departure.reason'].sudo()
Ssc = env['ssc.employee'].sudo() if 'ssc.employee' in env else None
Slip = env['ssc.payslip'].sudo() if 'ssc.payslip' in env else None


def title(text):
    print()
    print("=" * 98)
    print(text)
    print("=" * 98)


if Ssc is None:
    print("ssc.employee is not on this database - nothing to do")
    raise SystemExit

resigned = Reason.search([('name', '=', 'Resigned')], limit=1)
neutral = Reason.search([('name', '=', NEUTRAL_REASON)], limit=1)
if not resigned:
    print("no 'Resigned' departure reason - stopping")
    raise SystemExit

# ---------------------------------------------------------------------------
title("1. who is in scope")

cancelled = Ssc.with_context(active_test=False).search(
    ['|', ('is_cancelled', '=', True), ('approved_nor', '=', True)])
rows, no_evidence, unlinked, kept = [], [], [], []
for record in cancelled:
    employee = record.hr_employee_id
    if not employee:
        unlinked.append(record)
        continue
    if not employee.active:
        continue
    if employee.name in KEEP:
        kept.append(employee)
        continue

    last_punch = Attendance.search([('employee_id', '=', employee.id)],
                                   order='check_in desc', limit=1)
    punched = last_punch.check_in.date() if last_punch else None

    paid = None
    # `if Slip:` would be false here - an empty recordset is falsy, and this
    # one is empty by construction. The payslip lookup silently never ran.
    if Slip is not None:
        last_slip = Slip.search([('employee_id', '=', record.id),
                                 ('to_date', '!=', False)],
                                order='to_date desc', limit=1)
        paid = last_slip.to_date if last_slip else None

    when = max([d for d in (punched, paid) if d], default=None)
    if not when:
        # Cancelled all the same, because that is what the flag says - but with
        # no date invented for it. Somebody who joined in 2020 and left no
        # trace may still have five years of service, and writing the joining
        # date as the leaving date would erase it.
        no_evidence.append((employee, record))
    rows.append((employee, record, when, punched, paid))

print(f"  cancelled in ssc_payroll     : {len(cancelled)}")
print(f"  still active here            : {len(rows) + len(no_evidence)}")
print(f"  to be closed                 : {len(rows)}")
print(f"  of those, with a leaving date: {len([r for r in rows if r[2]])}")
print(f"  archived with no date         : {len(no_evidence)}")
print(f"  not linked to an employee    : {len(unlinked)}")
if kept:
    print()
    print("  named and left alone:")
    for person in kept:
        print(f"      {person.name}")

# ---------------------------------------------------------------------------
title("2. the reason each one gets")

by_reason = {}
for employee, record, when, _p, _q in rows:
    label = 'Resigned' if record.approved_nor else NEUTRAL_REASON
    by_reason.setdefault(label, []).append((employee, record, when))
for label, people in by_reason.items():
    print(f"  {label:<22} {len(people)}")
if NEUTRAL_REASON in by_reason and not neutral:
    print(f"  ('{NEUTRAL_REASON}' does not exist yet and will be created)")

# ---------------------------------------------------------------------------
title("3. when each one left, and on what evidence")

print(f"  {'employee':<34} {'last punch':<12} {'paid until':<12} "
      f"{'departure':<12} {'reason'}")
for employee, record, when, punched, paid in sorted(
        rows, key=lambda r: (r[2] is None, r[2] or date.min)):
    label = 'Resigned' if record.approved_nor else NEUTRAL_REASON
    print(f"  {employee.name[:34]:<34} {str(punched or '-'):<12} "
          f"{str(paid or '-'):<12} {str(when or 'unknown'):<12} {label}")

# ---------------------------------------------------------------------------
if no_evidence:
    title("4. no evidence at all - left alone, somebody has to say what happened")
    for employee, record in sorted(no_evidence, key=lambda r: r[0].name):
        print(f"  {employee.name[:36]:<36} badge={(employee.barcode or '-'):<10} "
              f"joined {record.joining_date or '-'}  code={record.employee_code or '-'}")

# ---------------------------------------------------------------------------
title("5. what will be written")

print("  on each contract : departure_date, departure_reason_id, contract_date_end")
print("  on each employee : active = False")
print()
print(f"  {len(rows)} employee(s)")

# ---------------------------------------------------------------------------
if APPLY:
    if NEUTRAL_REASON in by_reason and not neutral:
        neutral = Reason.create({'name': NEUTRAL_REASON})
        print(f"created departure reason {neutral.name!r}")

    done, failed = 0, []
    for employee, record, when, _p, _q in rows:
        reason = resigned if record.approved_nor else neutral
        version = employee.current_version_id
        try:
            with env.cr.savepoint():
                vals = {'departure_reason_id': reason.id}
                if when:
                    vals['departure_date'] = when
                    # The database refuses an end date on a contract with no
                    # start, and there are contracts here with no start.
                    if version.contract_date_start:
                        vals['contract_date_end'] = max(
                            when, version.contract_date_start)
                version.write(vals)
                employee.active = False
            done += 1
        except Exception as error:
            failed.append((employee.name, str(error).splitlines()[0][:70]))
    env.cr.commit()

    title("APPLIED")
    print(f"  closed {done} | refused {len(failed)}")
    for name, message in failed:
        print(f"      {name[:32]:<32} {message}")
    print()
    left = Employee.with_context(active_test=True).search_count([])
    print(f"  active employees now: {left}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
