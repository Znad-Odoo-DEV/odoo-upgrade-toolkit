"""Carry one month of ssc.attachment onto the native payslips as Salary Inputs.

    cd ~/src/user

    # report only, writes nothing:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/move_attachments_to_inputs.py

    # a different month:
    SSC_MONTH=AUG SSC_YEAR=2026 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/move_attachments_to_inputs.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/move_attachments_to_inputs.py

    # write, and take the attachment off its ssc payslip as it goes:
    SSC_APPLY=1 SSC_DETACH=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/move_attachments_to_inputs.py

One month only. The older attachments are not being moved and the default stays
on August 2026 for that reason - there are 2871 unpaid attachments in total and
almost none of them have a native payslip to land on.

NO NEW INPUT TYPES

Every destination already exists and already has a rule paying it, on all eight
SSC structures. That was the constraint and it is met without creating one.

THE SIGN, WHICH IS THE PART THAT BITES

hr.payslip.input.amount is fed positive and the rule decides the direction.
Read off the live rules:

    SALARY_DEDUCTIONS / ADVREC / OTHER_DEDUCTIONS / DEDUCTION
        result = -inputs[CODE].amount          <- they negate

    OTHER_EARNINGS / BONUS / AIRFARE_ALLOWANCE  amount_select = input
    REIMBURSEMENT                               result = inputs[CODE].amount

ssc.attachment.signed_value is already negative for a deduction. Passing it
through would negate a negative and pay the deduction out. So every input is
written as abs(value), always, whichever way it is going.

WHAT IS DELIBERATELY NOT MOVED

  Pension for Emirati Employees   SICC and SIEC already compute the social
                                  insurance natively. Moving these would charge
                                  it twice. 53 records, and the type is marked
                                  addition while its values are negative, which
                                  is its own thing to sort out.

  Leave Salary                    LEAVESAL already computes annual leave salary
                                  from hr.leave. Same double, 11 records.

  400 / 75 / bou                  types the Studio bridge invented from bad
                                  names. Nothing carries them.

Anything whose type is not in the map is reported, never guessed at.

IDEMPOTENCY

The input's description carries the attachment id - "[SSC-1234] ..." - so a
second run finds its own work and skips it. It also means anybody reading the
payslip can see where the figure came from.

DOUBLE PAYMENT, WHICH THIS DOES NOT DECIDE

An attachment that has become an input is still on its ssc payslip, still
counted in ssc.payslip.salary_adjustment. If both payslips are validated the
same money goes out twice, and nothing here prevents that. SSC_DETACH=1 takes
the attachment off its ssc payslip as it moves, which removes it from that sum;
without the flag the report just says how many are in that position.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

WIDTH = 100

APPLY = os.environ.get('SSC_APPLY') == '1'
DETACH = os.environ.get('SSC_DETACH') == '1'
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def hr_employee_of(record):
    """The hr.employee behind an ssc record, whichever generation it is.

    ssc.employee retired on production on 2026-09-08 and every payroll document
    names hr.employee directly since. This tool still walked the old chain -
    employee_id.hr_employee_id - and hr.employee has no such field, so it died
    on the first record with the traceback hidden behind 2>/dev/null.
    """
    employee = record.employee_id
    if not employee or employee._name == 'hr.employee':
        return employee
    return employee.hr_employee_id

# ssc.attachment.type name -> the input type code that already pays it.
DESTINATION = {
    'Salary Addition': 'OTHER_EARNINGS',
    'Salary Advance': 'OTHER_EARNINGS',
    'Sick Leave Reimbursement': 'OTHER_EARNINGS',
    'Salary Bonus': 'BONUS',
    'Air Ticket Reimbursement': 'AIRFARE_ALLOWANCE',
    'Phone Bill Reimbursement': 'REIMBURSEMENT',
    'Medical Bill Reimbursement': 'REIMBURSEMENT',
    'Salary Deductions': 'SALARY_DEDUCTIONS',
    'Salary Advance-Deduction': 'ADVREC',
    'Penalty Fine': 'OTHER_DEDUCTIONS',
}

# Named rather than silently absent, so the report says why.
WITHHELD = {
    'Pension for Emirati Employees': 'SICC and SIEC compute this natively',
    'Leave Salary': 'LEAVESAL computes this natively from hr.leave',
}


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


title("moving %s-%s%s" % (MONTH, YEAR, "" if APPLY else "  (report only)"))

Attachment = env.get('ssc.attachment')
Payslip = env.get('hr.payslip')
InputType = env.get('hr.payslip.input.type')
if not (Attachment is not None and Payslip is not None and InputType is not None):
    print("  ssc_payroll or hr_payroll is not installed here")
    raise SystemExit

codes = {}
for code in set(DESTINATION.values()):
    found = InputType.sudo().search([('code', '=', code)], limit=1)
    if not found:
        print("  !! no input type with code %s - refusing to guess" % code)
        raise SystemExit
    codes[code] = found

attachments = Attachment.sudo().search([
    ('month', '=', MONTH), ('year', '=', str(YEAR)),
    ('state', '!=', 'paid'),
])
print("  %s unpaid attachment(s) in the period" % len(attachments))

# --- the native payslip each one would land on -------------------------------
slips = {}
for slip in Payslip.sudo().search([
        ('date_from', '<=', '%s-12-31' % YEAR),
        ('date_to', '>=', '%s-01-01' % YEAR)]):
    if slip.date_from and slip.date_from.strftime('%b').upper() == MONTH:
        slips.setdefault(slip.employee_id.id, []).append(slip)


def payslip_for(attachment):
    """The draft native payslip this attachment belongs on, if there is one."""
    hr_employee = hr_employee_of(attachment)
    if not hr_employee:
        return None, "the ssc.employee has no hr.employee"
    candidates = slips.get(hr_employee.id) or []
    if not candidates:
        return None, "no native payslip for this employee in the period"
    draft = [s for s in candidates if s.state == 'draft']
    if not draft:
        return None, "the native payslip is no longer draft"
    return draft[0], None


planned, skipped = [], defaultdict(list)
for attachment in attachments:
    name = attachment.type_id.name or '?'
    if name in WITHHELD:
        skipped[WITHHELD[name]].append(attachment)
        continue
    code = DESTINATION.get(name)
    if not code:
        skipped["type is not in the map - decide before moving it"].append(attachment)
        continue
    if not attachment.value:
        skipped["value is zero"].append(attachment)
        continue
    slip, why = payslip_for(attachment)
    if not slip:
        skipped[why].append(attachment)
        continue
    marker = "[SSC-%s]" % attachment.id
    if any(marker in (line.name or '') for line in slip.input_line_ids):
        skipped["already carried onto the payslip"].append(attachment)
        continue
    planned.append((attachment, slip, codes[code], marker))

title("what would move", '-')
by_code = defaultdict(lambda: [0, 0.0])
for attachment, _slip, input_type, _marker in planned:
    by_code[input_type.code][0] += 1
    by_code[input_type.code][1] += abs(attachment.value)
if not planned:
    print("  nothing")
for code, (count, total) in sorted(by_code.items()):
    print("  %-20s %5s input(s)   %s  (written positive; the rule signs it)"
          % (code, count, "{:>12,.2f}".format(total)))

title("what would not, and why", '-')
if not skipped:
    print("  nothing left behind")
for why, records in sorted(skipped.items(), key=lambda kv: -len(kv[1])):
    print("  %5s  %s" % (len(records), why))
    names = sorted({r.type_id.name or '?' for r in records})
    print("         types: %s" % ", ".join(names)[:80])

# --- the double this does not solve ------------------------------------------
still_on_ssc = [a for a, _s, _t, _m in planned if a.payslip_id]
title("the same money on two payslips", '-')
if not still_on_ssc:
    print("  none of the moving attachments is attached to an ssc payslip")
else:
    print("  %s of them are attached to an ssc payslip and still counted in its"
          % len(still_on_ssc))
    print("  salary_adjustment. Validate both and the money goes out twice.")
    print("  SSC_DETACH=1 takes them off as they move." if not DETACH
          else "  SSC_DETACH is on: they will be taken off as they move.")

# --- write --------------------------------------------------------------------
title("summary")
if not APPLY:
    env.cr.rollback()
    print("  report only - nothing written. Re-run with SSC_APPLY=1.")
else:
    Input = env['hr.payslip.input'].sudo()
    written, detached = 0, 0
    for attachment, slip, input_type, marker in planned:
        Input.create({
            'payslip_id': slip.id,
            'input_type_id': input_type.id,
            # Always positive: every destination rule signs it itself.
            'amount': abs(attachment.value),
            'name': "%s %s" % (marker, attachment.name or input_type.name),
        })
        written += 1
        if DETACH and attachment.payslip_id:
            attachment.write({'payslip_id': False, 'state': 'new'})
            detached += 1
    env.cr.commit()
    print("  %s input(s) written%s"
          % (written, ", %s attachment(s) detached" % detached if detached else ""))
    print("  Recompute those payslips - an input does not reach a payslip that "
          "is already computed.")
