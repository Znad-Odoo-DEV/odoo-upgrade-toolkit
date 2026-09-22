"""Show the raw employee, month and year on both sides, before trusting a zero.

    odoo-bin shell --no-http --shell-interface=python < tools/show_payslip_keys.py

Reads only. The overlap check said no payslip exists on both sides. That is
either the truth - the 189 native payslips are months the Studio master never
had - or it is two date formats failing to meet: MAY-2025 against may, a year
held as text against a year held as a number, an employee named on ssc.employee
on one side and on hr.employee on the other.

The difference between those two readings is the difference between a clean
import and four and a half thousand duplicates, so the values are printed raw
rather than compared. Whatever the answer is, it should be visible.
"""
SOURCE = 'x_all_payslips'
TARGET = 'ssc.payslip'

cr = env.cr                                                      # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821
Target = env[TARGET].sudo().with_context(active_test=False)      # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


title("1. ours, raw")

ours = Target.search([], order='id desc', limit=12)
for slip in ours:
    employee = slip.employee_id
    hr = employee.hr_employee_id if employee else False
    print("  id=%-6s employee=%-28s hr=%-6s month=%-10r year=%-8r net=%s"
          % (slip.id, (employee.name or '')[:28] if employee else '-',
             hr.id if hr else '-', slip.month, slip.year,
             slip.net_amount if 'net_amount' in slip._fields else '?'))

print("\n  distinct (month, year) on our side:")
pairs = {}
for slip in Target.search([]):
    pairs[(slip.month, slip.year)] = pairs.get((slip.month, slip.year), 0) + 1
for pair, count in sorted(pairs.items(), key=lambda kv: str(kv[0])):
    print("      %-22s %s slip(s)" % (str(pair), count))


title("2. theirs, raw")

theirs = Source.search([], order='id desc', limit=12)
for record in theirs:
    employee = record.x_studio_employee
    print("  id=%-6s employee=%-28s model=%-14s month=%-12r year=%-8r net=%s"
          % (record.id, (employee.display_name or '')[:28] if employee else '-',
             employee._name if employee else '-',
             record.x_studio_month, record.x_studio_year,
             record.x_studio_net_amount))

print("\n  distinct (month, year) on their side:")
pairs = {}
for record in Source.search([]):
    key = (record.x_studio_month, record.x_studio_year)
    pairs[key] = pairs.get(key, 0) + 1
for pair, count in sorted(pairs.items(), key=lambda kv: str(kv[0])):
    print("      %-22s %s slip(s)" % (str(pair), count))


title("3. do the employees even meet")

our_people = set()
for slip in Target.search([]):
    hr = slip.employee_id.hr_employee_id if slip.employee_id else False
    if hr:
        our_people.add(hr.id)
their_people = {r.x_studio_employee.id for r in Source.search([])
                if r.x_studio_employee}
print("  employees on our payslips     %s" % len(our_people))
print("  employees on their payslips   %s" % len(their_people))
print("  in both                       %s" % len(our_people & their_people))
if not our_people:
    print("\n  None of our payslips resolves to an hr.employee. That alone would")
    print("  make every comparison miss, whatever the months say.")


title("what to read from this")
print("""  If the months and years are written the same way on both sides and the
  employees overlap, then a zero really is a zero: the 189 are months the
  Studio master does not have, and importing 4,584 rows adds to them rather
  than duplicating them.

  If they are written differently, the zero is an artefact and the import must
  match on something both sides agree on before it creates anything.""")
