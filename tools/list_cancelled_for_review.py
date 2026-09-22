"""The cancelled employees, one line each, for a person to go through.

    odoo-bin shell -d <database> --no-http < tools/list_cancelled_for_review.py

Read only. Nothing is written, ever. Nothing is archived.

85 employees carry is_cancelled and 84 of them are still active, so replacing
the flag with archiving would archive 84 people in one go. That is not being
done. This prints them instead, newest first, so each can be decided on its
own.

Every date that could say when somebody left is here, because they disagree:
last_day is filled on all 466 employees and therefore says nothing;
end_of_service_date is filled on 40; and the end of service record - the actual
document, with a request date and a last day of duty - is the only one raised
by a person for this purpose.

Beside them, what the payroll knows: how many payslips, when the last one was,
what state it is in and what it was worth. The paid state is not maintained on
this database - all 645 payslips of these 84 read as unpaid across eighteen
months - so it is printed but must not be read as money owed. The date is the
signal. Somebody last paid in 2025 is a different question from somebody paid
last month.
"""
from datetime import date

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

Ssc = env['ssc.employee']
Payslip = env['ssc.payslip']
EndOfService = env.get('ssc.end.of.service')

CUTOFF = date(2026, 1, 1)

employees = Ssc.with_context(active_test=False).search([('is_cancelled', '=', True)])
print("%s employee(s) flagged cancelled - %s of them still active\n"
      % (len(employees), len(employees.filtered('active'))))

# The end of service documents, by employee. This is the only date a person
# actually raised for the purpose.
eos_by_employee = {}
if EndOfService is not None:
    for eos in EndOfService.with_context(active_test=False).search([]):
        current = eos_by_employee.get(eos.employee_id.id)
        if not current or (eos.last_day_of_duty or date.min) > (
                current.last_day_of_duty or date.min):
            eos_by_employee[eos.employee_id.id] = eos

# Payslips, newest first, grouped once.
slips_by_employee = {}
for slip in Payslip.search([('employee_id', 'in', employees.ids)],
                           order='to_date desc, id desc'):
    slips_by_employee.setdefault(slip.employee_id.id, []).append(slip)

rows = []
for employee in employees:
    slips = slips_by_employee.get(employee.id, [])
    latest = slips[0] if slips else None
    eos = eos_by_employee.get(employee.id)
    rows.append({
        'employee': employee,
        'last_slip': latest.to_date if latest else False,
        'last_state': latest.state if latest else '-',
        'last_net': round(latest.net_amount, 2) if latest else 0.0,
        'slips': len(slips),
        'total': round(sum(s.net_amount for s in slips), 2),
        'eos': eos,
    })

# Newest payslip first: whoever was paid most recently needs deciding first.
rows.sort(key=lambda r: r['last_slip'] or date.min, reverse=True)

HEAD = ("%-38s %-12s %-6s %-11s %-11s %-11s %-11s %-5s %-11s %-9s %-10s"
        % ("NAME", "BADGE", "ACTIVE", "JOINED", "EOS DATE", "EOS REQUEST",
           "EOS LAST DAY", "SLIPS", "LAST SLIP", "STATE", "LAST NET"))
print(HEAD)
print("-" * len(HEAD))


def show(value):
    return str(value) if value else "-"


def band(last_slip):
    if not last_slip:
        return "no date"
    if last_slip >= CUTOFF:
        return "2026"
    return "2025 or older"


current_band = None
for row in rows:
    employee = row['employee']
    this_band = band(row['last_slip'])
    if this_band != current_band:
        current_band = this_band
        print()
        print("--- last paid: %s ---" % this_band)
    eos = row['eos']
    print("%-38s %-12s %-6s %-11s %-11s %-11s %-11s %-5s %-11s %-9s %-10s"
          % (employee.name[:38],
             show(employee.employee_code),
             'yes' if employee.active else 'no',
             show(employee.joining_date),
             show(employee.end_of_service_date),
             show(eos.date_of_request if eos else False),
             show(eos.last_day_of_duty if eos else False),
             row['slips'],
             show(row['last_slip']),
             row['last_state'],
             row['last_net']))

# ----------------------------------------------------------------------
print()
print("=" * 104)
print("SUMMARY")
print("=" * 104)
bands = {}
for row in rows:
    bands.setdefault(band(row['last_slip']), []).append(row)
for name in ('2026', 'no date', '2025 or older'):
    group = bands.get(name, [])
    if not group:
        continue
    print("%-16s %s employee(s), %s payslip(s)"
          % (name, len(group), sum(r['slips'] for r in group)))

with_eos = [r for r in rows if r['eos']]
print()
print("%s of the %s have an end of service record; %s do not."
      % (len(with_eos), len(rows), len(rows) - len(with_eos)))
print("An employee flagged cancelled with no end of service document is a flag")
print("somebody ticked and a document nobody raised.")

no_date = [r for r in rows if not r['last_slip']]
if no_date:
    print()
    print("%s carry payslips with NO period at all - broken data before they "
          "are a decision:" % len(no_date))
    for row in no_date:
        print("    %-38s %s slip(s), %s AED total"
              % (row['employee'].name[:38], row['slips'], row['total']))

print()
print("Nothing was archived. Decide each one, then archive by hand or say")
print("which band to archive and it can be done in a single reviewed pass.")
