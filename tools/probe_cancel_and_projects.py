"""What archiving the cancelled employees would actually do, and who uses the
staff project distribution.

    odoo-bin shell -d <database> --no-http < tools/probe_cancel_and_projects.py

Read only. Nothing is written, ever.

Two changes are proposed and both are hard to walk back, so both get measured
first.

is_cancelled is to be replaced by archiving: an archived employee drops out of
attendance and out of payroll, which is the whole point. 85 employees carry the
flag and 46 are already archived, so the two sets are not the same and the
difference is people who would be archived by this change. If any of them is
still being paid, archiving stops it - and that is either the correction the
change exists to make, or a wage that stops arriving. The payslips say which.

staff_project_ids is to be dropped in favour of the fallback that already
exists: an equal split over every on-going project. That is right only if
nobody is relying on an uneven split. So count who has one, and show what they
would get instead.
"""
from datetime import date
from collections import Counter, defaultdict

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

Ssc = env['ssc.employee']
Payslip = env['ssc.payslip']
StaffProject = env['ssc.staff.project']
Project = env['project.project']


def title(text):
    print()
    print("=" * 104)
    print(text)
    print("=" * 104)


employees = Ssc.with_context(active_test=False).search([])
print("%s ssc.employee record(s), %s active"
      % (len(employees), len(employees.filtered('active'))))

# ----------------------------------------------------------------------
title("1. is_cancelled AGAINST active - who would actually be archived")
# ----------------------------------------------------------------------
cross = Counter((bool(e.is_cancelled), bool(e.active)) for e in employees)
print("%-14s %-10s %s" % ("is_cancelled", "active", "count"))
print("-" * 44)
for (cancelled, active), count in sorted(cross.items(), key=lambda kv: -kv[1]):
    note = ""
    if cancelled and active:
        note = "  <-- WOULD BE ARCHIVED by this change"
    elif not cancelled and not active:
        note = "  <-- already archived without the flag"
    print("%-14s %-10s %s%s" % (cancelled, active, count, note))

would_archive = employees.filtered(lambda e: e.is_cancelled and e.active)
print()
print("%s employee(s) would be newly archived." % len(would_archive))

# ----------------------------------------------------------------------
title("2. ARE ANY OF THEM STILL BEING PAID")
# ----------------------------------------------------------------------
# The only question that matters before archiving anybody: is money still
# moving for these people. A payslip in the last few months means archiving
# them stops a wage.
recent = Payslip.search([('employee_id', 'in', would_archive.ids)],
                        order='to_date desc, id desc')
print("%s payslip(s) belong to the %s who would be archived"
      % (len(recent), len(would_archive)))

by_employee = defaultdict(list)
for slip in recent:
    by_employee[slip.employee_id].append(slip)

if by_employee:
    print()
    print("%-40s %-8s %-12s %-12s %s"
          % ("NAME", "SLIPS", "LATEST", "STATE", "NET"))
    # to_date is empty on some slips, so sort on a real date either way -
    # comparing a date with an empty string is a crash, not an ordering.
    for employee, slips in sorted(by_employee.items(),
                                  key=lambda kv: kv[1][0].to_date or date.min,
                                  reverse=True):
        latest = slips[0]
        print("%-40s %-8s %-12s %-12s %s"
              % (employee.name[:40], len(slips), latest.to_date or '-',
                 latest.state, round(latest.net_amount, 2)))
else:
    print("None of them has a payslip at all - archiving stops nothing.")

unpaid = recent.filtered(lambda s: s.state != 'paid')
print()
print("Of those payslips, %s are NOT yet paid." % len(unpaid))
for slip in unpaid[:20]:
    print("    %-40s %-12s %-10s %s"
          % (slip.employee_id.name[:40], slip.to_date or '-', slip.state,
             round(slip.net_amount, 2)))
print()
print("An unpaid payslip on somebody about to be archived is money owed to a")
print("person who is about to disappear from the payroll screens.")

# ----------------------------------------------------------------------
title("3. AND THE OTHER WAY - archived but NOT cancelled")
# ----------------------------------------------------------------------
# These stay archived either way; worth naming because the flag was supposed
# to mean the same thing and does not.
odd = employees.filtered(lambda e: not e.is_cancelled and not e.active)
print("%s employee(s) are archived without the cancelled flag." % len(odd))
for employee in odd[:15]:
    print("    %-40s [%s]" % (employee.name[:40], employee.employee_code or '-'))
if len(odd) > 15:
    print("    ... and %s more" % (len(odd) - 15))

# ----------------------------------------------------------------------
title("4. WHO USES THE STAFF PROJECT DISTRIBUTION")
# ----------------------------------------------------------------------
lines = StaffProject.search([])
owners = lines.mapped('employee_id')
print("%s distribution line(s) across %s employee(s)" % (len(lines), len(owners)))

ongoing = Project.search([])
print("%s project(s) exist - an equal split would give each %.2f%%"
      % (len(ongoing), 100.0 / len(ongoing) if ongoing else 0))
print()
print("Dropping the field means everybody below gets that equal split instead")
print("of what they have now:")
print()
for employee in owners:
    own = lines.filtered(lambda l: l.employee_id == employee)
    total = sum(own.mapped('percentage'))
    spread = ", ".join("%s %.0f%%" % (l.project_id.name[:26], l.percentage)
                       for l in own)
    flag = "" if abs(total - 100) < 0.5 else "   (totals %.1f%%)" % total
    print("  %-34s %s%s" % (employee.name[:34], spread, flag))

print()
single = [e for e in owners
          if len(lines.filtered(lambda l: l.employee_id == e)) == 1]
print("%s of them sit on ONE project only. An equal split would move their"
      % len(single))
print("whole cost off that project and spread it over every other one.")

print()
office = employees.filtered('is_engineer_office')
print("Office/engineer staff: %s, of whom %s have a distribution and %s do not."
      % (len(office), len(office & owners), len(office - owners)))
print("The ones with none already get the equal split today, so for them")
print("nothing changes.")

print("\nDone. Read only - nothing was written.")
