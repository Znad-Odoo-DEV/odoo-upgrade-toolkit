"""Give an ssc.employee to the people who have attendance lines but none.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/mirror_missing_attendance_employees.py

The roster states live on ssc.employee now. An employee with attendance lines
and no record there reads as present, on the roster and nobody's leaver, which
is right for somebody still working and wrong for anybody else - and the wrong
answer is the one that pays.

So each of them gets a record, carrying the states off the Studio row the line
used to point at, reached backwards through the migration id map. Only the
states and the identity: no salary, no allowances, nothing that would look like
a payroll decision made by a script. What is created is deliberately minimal and
printed in full.

Employees with no Studio row behind them get a record with every state false,
which is what they already read as - the record only makes that explicit and
gives somebody a place to correct it.
"""
import json
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

LEGACY_MODEL = 'x_employeeslist'
ID_MAP_KEY = 'ssc.employee_migration.id_map'

# Studio flag -> the field on ssc.employee that means the same thing.
FLAGS = {
    'x_studio_cancelled': 'is_cancelled',
    'x_studio_on_leave': 'on_leave',
    'x_studio_approved_nor': 'approved_nor',
    'x_studio_submitted_cancellation': 'submitted_cancellation',
    'x_studio_engineeroffice_staff': 'is_engineer_office',
    'x_studio_staff': 'is_staff',
}

cr = env.cr                                                      # noqa: F821
param = env['ir.config_parameter'].sudo()                        # noqa: F821
Line = env['ssc.attendance.line'].sudo()                         # noqa: F821
Ssc = env['ssc.employee'].sudo().with_context(active_test=False)  # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# --- 1. who is missing -------------------------------------------------------

title("1. employees with lines and no ssc.employee")

lines = Line.search([('employee_id', '!=', False), ('ssc_employee_id', '=', False)])
employees = lines.mapped('employee_id')
counts = {}
for line in lines:
    counts[line.employee_id.id] = counts.get(line.employee_id.id, 0) + 1

id_map = {int(k): int(v) for k, v in
          json.loads(param.get_param(ID_MAP_KEY) or '{}').items()}
back = {}
for old_id, new_id in id_map.items():
    back.setdefault(new_id, []).append(old_id)

Legacy = env.get(LEGACY_MODEL)                                   # noqa: F821
if Legacy is not None:
    Legacy = Legacy.sudo().with_context(active_test=False)

plan = []
for employee in employees:
    rows = Legacy.browse(back.get(employee.id, [])).exists() if Legacy is not None else None
    vals = {
        'name': employee.name or employee.display_name,
        'hr_employee_id': employee.id,
        'company_id': employee.company_id.id or env.company.id,   # noqa: F821
        'attendance_code': employee.barcode or False,
        'active': bool(employee.active),
    }
    source = None
    if rows:
        # The newest row wins where a person somehow has two: a later record is
        # a later decision about them.
        source = rows.sorted(lambda r: r.id)[-1]
        vals['studio_ref_id'] = source.id
        for studio_name, native_name in FLAGS.items():
            if native_name in Ssc._fields:
                vals[native_name] = bool(getattr(source, studio_name, False))
    plan.append((employee, vals, source, counts.get(employee.id, 0)))

print("  %s line(s) across %s employee(s)" % (len(lines), len(plan)))
for employee, vals, source, count in sorted(plan, key=lambda p: -p[3]):
    states = [name for name in FLAGS.values() if vals.get(name)]
    print("\n  %-40s %s line(s)" % (employee.display_name[:40], count))
    print("      company     %s" % (employee.company_id.display_name or '-'))
    print("      badge       %s" % (employee.barcode or '-'))
    print("      Studio row  %s" % (source.id if source else 'none'))
    print("      states      %s" % (', '.join(states) if states else 'none set'))

if not plan:
    print("  nothing to do")
    raise SystemExit()

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing created. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 2. create ---------------------------------------------------------------

title("2. creating")

created = Ssc
for employee, vals, _source, _count in plan:
    # Somebody may already be there under another link - never make a second.
    existing = Ssc.search([('hr_employee_id', '=', employee.id)], limit=1)
    if existing:
        print("  = %-40s already has one" % employee.display_name[:40])
        continue
    record = Ssc.create(vals)
    created |= record
    print("  + %-40s ssc.employee %s" % (employee.display_name[:40], record.id))
cr.commit()


# --- 3. the lines now read from them -----------------------------------------

title("3. pointing the lines at them")

env.add_to_compute(Line._fields['ssc_employee_id'], lines)        # noqa: F821
env.flush_all()                                                   # noqa: F821
cr.commit()

still = Line.search_count([('employee_id', '!=', False),
                           ('ssc_employee_id', '=', False)])
print("  %s line(s) still without one" % still)

title("summary")
print("  %s ssc.employee record(s) created" % len(created))
print("""
  Now run tools/recompute_attendance_roster.py: the states are in place, and the
  stored roster fields can be worked out again from them.""")
