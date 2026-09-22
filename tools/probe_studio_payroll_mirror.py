"""Did the Studio payroll actually reach ssc_payroll? Reads only.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http < tools/probe_studio_payroll_mirror.py

ssc_payroll is built as a mirror: six bridges copy the Studio payroll models
into native ones, each native record keeping the id of the Studio record it
came from. Deleting the Studio side is only safe for the records that made the
crossing, so this counts both sides and, for every bridge, names the Studio
records that no native record claims.

Those are what deleting would lose. Everything else is already held twice.
"""
from collections import defaultdict

WIDTH = 100

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

# (Studio model, native model, the field on the native side holding the
#  Studio id). The link field is found rather than assumed: these were named
#  differently as each bridge was written.
BRIDGES = [
    ('x_advance_salaries', 'ssc.advance'),
    ('x_leave_expenses', 'ssc.leave.expense'),
    ('x_on_hold_amounts', 'ssc.on.hold'),
    ('x_salary_batches', 'ssc.salary.batch'),
    ('x_attachments_list', 'ssc.attachment'),
    ('x_staff_payslips', 'ssc.payslip'),
    ('x_to_pay', 'ssc.payslip'),
]
UNBRIDGED = ['x_e_o_s_gratuity', 'x_salary_attachments']

print()
print("=" * WIDTH)
print("STUDIO PAYROLL, AND WHAT CROSSED INTO ssc_payroll")
print("=" * WIDTH)
print("  %-24s %-22s %8s %8s %9s  %s"
      % ("STUDIO", "NATIVE", "STUDIO", "NATIVE", "UNCLAIMED", "LINK FIELD"))
print("  " + "-" * (WIDTH - 4))

unclaimed_by_model = defaultdict(list)

for studio_name, native_name in BRIDGES:
    if studio_name not in env:
        print("  %-24s %-22s %8s" % (studio_name, "-", "not on this database"))
        continue
    Studio = env[studio_name].sudo().with_context(active_test=False)
    studio_rows = Studio.search([])

    if native_name not in env:
        print("  %-24s %-22s %8s %8s %9s  %s"
              % (studio_name, native_name, len(studio_rows), "-", len(studio_rows),
                 "native model absent"))
        unclaimed_by_model[studio_name] = list(studio_rows)
        continue

    Native = env[native_name].sudo().with_context(active_test=False)
    # The column that carries the Studio id. Integer, and named after it.
    link = next((n for n, f in Native._fields.items()
                 if f.type == 'integer'
                 and ('studio' in n or 'legacy' in n or n.endswith('_src_id'))), None)
    if not link:
        print("  %-24s %-22s %8s %8s %9s  %s"
              % (studio_name, native_name, len(studio_rows), Native.search_count([]),
                 "?", "no link column found"))
        continue

    claimed = set(Native.search([(link, '!=', 0)]).mapped(link))
    missing = [row for row in studio_rows if row.id not in claimed]
    unclaimed_by_model[studio_name] = missing
    print("  %-24s %-22s %8s %8s %9s  %s"
          % (studio_name, native_name, len(studio_rows), Native.search_count([]),
             len(missing), link))

print("  " + "-" * (WIDTH - 4))
for name in UNBRIDGED:
    if name in env:
        rows = env[name].sudo().with_context(active_test=False).search_count([])
        print("  %-24s %-22s %8s %8s %9s  %s"
              % (name, "(no bridge)", rows, "-", rows, "never mirrored"))

total = sum(len(rows) for rows in unclaimed_by_model.values())
print()
if total:
    print("  %s Studio record(s) no native record claims. Deleting the Studio" % total)
    print("  side loses these and only these:")
    for studio_name, rows in sorted(unclaimed_by_model.items()):
        if not rows:
            continue
        print()
        print("  %s (%s):" % (studio_name, len(rows)))
        for row in rows[:15]:
            try:
                shown = row.display_name
            except Exception:                                   # noqa: BLE001
                shown = row.id
            print("      id=%-8s %s" % (row.id, shown))
        if len(rows) > 15:
            print("      ... and %s more" % (len(rows) - 15))
else:
    print("  Every Studio payroll record is already held by a native one.")
# ----------------------------------------------------------------------
# Second opinion for x_to_pay.
#
# x_to_pay and x_staff_payslips both mirror onto ssc.payslip through the same
# studio_ref_id, and only the staff ones carry it: the labour payslips were
# generated natively rather than copied, so the link is empty and the count
# above reads every one of them as lost. The link is the wrong question for
# them. The right one is whether a payslip for that employee and that month
# exists at all.
# ----------------------------------------------------------------------
if 'x_to_pay' in env and 'ssc.payslip' in env:
    print()
    print("=" * WIDTH)
    print("x_to_pay AGAIN, MATCHED ON EMPLOYEE AND MONTH RATHER THAN ON THE LINK")
    print("=" * WIDTH)

    Slip = env['ssc.payslip'].sudo().with_context(active_test=False)
    native = defaultdict(int)
    for row in Slip.search_read([], ['employee_id', 'month', 'year']):
        employee = row['employee_id'][1] if row['employee_id'] else ''
        native[(employee.strip().lower(), row['month'] or '', str(row['year'] or ''))] += 1

    ToPay = env['x_to_pay'].sudo().with_context(active_test=False)
    cols = ToPay.fields_get()
    emp_col = next((n for n, m in cols.items()
                    if m.get('type') == 'many2one'
                    and m.get('relation') in ('hr.employee', 'ssc.employee', 'x_employeeslist')), None)
    month_col = next((n for n in ('x_studio_month',) if n in cols), None)
    year_col = next((n for n in ('x_studio_year',) if n in cols), None)

    if not (emp_col and month_col and year_col):
        print("  x_to_pay does not carry employee + month + year under the names")
        print("  expected (%s / %s / %s) - matched nothing."
              % (emp_col, month_col, year_col))
    else:
        matched, unmatched = 0, []
        for row in ToPay.search([]):
            employee = row[emp_col]
            name = (employee.display_name or '').strip().lower() if employee else ''
            key = (name, str(row[month_col] or ''), str(row[year_col] or ''))
            if native.get(key):
                matched += 1
            else:
                unmatched.append((row, key))
        print("  %s of %s Studio payslips have a native payslip for the same"
              % (matched, matched + len(unmatched)))
        print("  employee and the same month.")
        if unmatched:
            print()
            print("  %s do NOT, and deleting x_to_pay loses those:" % len(unmatched))
            for row, key in unmatched[:25]:
                print("      id=%-8s %s" % (row.id, row.display_name))
            if len(unmatched) > 25:
                print("      ... and %s more" % (len(unmatched) - 25))
    print("=" * WIDTH)

print()
print("=" * WIDTH)

env.cr.rollback()
