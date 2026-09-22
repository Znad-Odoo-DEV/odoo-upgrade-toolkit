"""Who has attendance lines but no ssc.employee, and what the old record said.

    odoo-bin shell --no-http --shell-interface=python < tools/check_unmirrored_attendance_employees.py

Reads only. The roster flags on an attendance line come from ssc.employee now,
so an employee with no ssc.employee record reads as present, on the roster, and
liable to be marked absent for every day they did not punch.

That is right for somebody still working and wrong for somebody cancelled, and
the only place the answer survives is the Studio row the line used to point at.
This finds them, walks back to that row through the id map, and prints what it
said - flag by flag - next to what the lines currently hold. Nothing is written:
the decision of whether to mirror them onto ssc.employee is a decision about
people, not about columns.
"""
import json

LEGACY_MODEL = 'x_employeeslist'
ID_MAP_KEY = 'ssc.employee_migration.id_map'
LEGACY_FLAGS = ('x_studio_cancelled', 'x_studio_on_leave',
                'x_studio_approved_nor', 'x_studio_submitted_cancellation',
                'x_studio_engineeroffice_staff')

param = env['ir.config_parameter'].sudo()                        # noqa: F821
Line = env['ssc.attendance.line'].sudo()                         # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# --- 1. who ------------------------------------------------------------------

title("1. employees with lines but no ssc.employee")

lines = Line.search([('employee_id', '!=', False), ('ssc_employee_id', '=', False)])
by_employee = {}
for line in lines:
    by_employee.setdefault(line.employee_id, Line)
    by_employee[line.employee_id] |= line

print("  %s line(s) across %s employee(s)" % (len(lines), len(by_employee)))

# The legacy row each one came from, read backwards through the map.
id_map = {int(k): int(v) for k, v in
          json.loads(param.get_param(ID_MAP_KEY) or '{}').items()}
back = {}
for old_id, new_id in id_map.items():
    back.setdefault(new_id, []).append(old_id)

Legacy = env.get(LEGACY_MODEL)                                   # noqa: F821
if Legacy is not None:
    Legacy = Legacy.sudo().with_context(active_test=False)


# --- 2. what the old record said ---------------------------------------------

title("2. each of them, and what the Studio row said")

for employee, employee_lines in sorted(by_employee.items(),
                                       key=lambda kv: -len(kv[1])):
    dates = sorted(l.date for l in employee_lines if l.date)
    punched = employee_lines.filtered('first_punch')
    print("\n  %-40s  %s line(s)" % (employee.display_name[:40], len(employee_lines)))
    print("      badge          %s" % (employee.barcode or '-'))
    print("      company        %s" % (employee.company_id.display_name or '-'))
    print("      active         %s" % employee.active)
    print("      days           %s -> %s" % (dates[0] if dates else '-',
                                             dates[-1] if dates else '-'))
    print("      punched on     %s of them" % len(punched))
    print("      stored absent  %s line(s)" % len(employee_lines.filtered('absent')))

    rows = Legacy.browse(back.get(employee.id, [])).exists() if Legacy is not None else None
    if not rows:
        print("      Studio row     none - this one never was on the list")
        continue
    for row in rows:
        flags = [flag for flag in LEGACY_FLAGS if getattr(row, flag, False)]
        print("      Studio row     %s  %s"
              % (row.id, ', '.join(flags) if flags else 'no flag set'))


# --- 3. and the ones naming nobody -------------------------------------------

title("3. lines naming no employee at all")

orphans = Line.search([('employee_id', '=', False)])
print("  %s line(s)" % len(orphans))
if orphans:
    dates = sorted(l.date for l in orphans if l.date)
    print("  %s -> %s" % (dates[0] if dates else '-', dates[-1] if dates else '-'))
    print("  %s of them carry a punch" % len(orphans.filtered('first_punch')))
    badges = sorted({l.attendance_id for l in orphans if l.attendance_id})
    print("  badges on them: %s" % (', '.join(badges[:12]) or 'none'))

title("summary")
print("""  A flagged Studio row means the lines below it were exempt from the absence
  rules and are no longer. Mirror that employee onto ssc.employee with the same
  flags before recomputing, or those days turn into absences.""")
