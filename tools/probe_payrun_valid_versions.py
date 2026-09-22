"""Call the Select Employees filter itself and ask it why it excluded somebody.

    cd ~/src/user
    SSC_COMPANIES="ROYAL ARROW" odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/probe_payrun_valid_versions.py

probe_payrun_employee_field.py found the mechanism. There is no employee field
on hr.payslip.run and no wizard - the Select Employees dialog is
action_payroll_hr_version_list_view_payrun, which builds its list from

    self._get_valid_version_ids(date_start, date_end, structure_id,
                                company_id, None, schedule_pay)

and then subtracts anybody who already holds a payslip for those exact dates
and that exact structure. Two conditions in the surrounding code are worth
suspecting before anything else:

    valid_versions.filtered(lambda c: c.structure_type_id.id == self.structure_id.type_id.id)
    Domain('version_id.schedule_pay', '=', schedule_pay if schedule_pay else False)

A run's schedule_pay is computed from structure_id.type_id.default_schedule_pay,
while every hr.version carries its own. Nothing keeps the two in step, and a
mismatch removes a perfectly valid contract from the list without saying so.

_get_valid_version_ids did not print in the previous probe because its name
contains none of the words that probe filtered on - so this prints it first,
then stops reasoning about it and calls it:

  * every pay run in the period with its structure, its structure type and its
    schedule_pay side by side;
  * the action the dialog actually opens, and how many versions its domain
    admits - that number IS what the dialog shows;
  * and for everybody the run excluded, their version's structure type and
    schedule_pay against the run's, so the mismatched column is the one that
    differs.

Read-only.
"""
import inspect
import os
from collections import defaultdict

WIDTH = 116
FROM = os.environ.get('SSC_FROM') or '2026-08-01'
TO = os.environ.get('SSC_TO') or '2026-08-25'
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or 'ROYAL ARROW').split(',') if n.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


Run = env['hr.payslip.run'].sudo()
Version = env['hr.version'].sudo()
Employee = env['hr.employee'].sudo()

# ----------------------------------------------------------------- the filter
title("1. _get_valid_version_ids - the filter itself")
member = getattr(type(Run), '_get_valid_version_ids', None)
if member is None:
    print("  the method does not exist on this version")
else:
    try:
        print(inspect.getsource(member))
    except Exception as error:  # noqa: BLE001
        print("  source not available - %s" % error)

# ------------------------------------------------------------------- the runs
title("2. the pay runs, and what they are tied to")
runs = Run.search([('date_start', '<=', TO), ('date_end', '>=', FROM)])
scoped = [r for r in runs
          if not ONLY or any(p in (r.company_id.name or '').upper() for p in ONLY)]
if not scoped:
    print("  no pay run in the period for %s" % ", ".join(ONLY))
for run in scoped:
    structure = run.structure_id
    print("\n  [%s] %s" % (run.id, run.name or '?'))
    print("       dates      %s .. %s" % (run.date_start, run.date_end))
    print("       structure  %s" % (structure.name or 'NONE - no structure set'))
    print("       type       %s" % (structure.type_id.name if structure else '-'))
    print("       schedule   run=%s   structure type default=%s"
          % (run.schedule_pay or 'False',
             structure.type_id.default_schedule_pay if structure else '-'))
    print("       payslips   %s" % len(run.slip_ids))

# --------------------------------------------------- what the dialog would show
title("3. what the dialog would actually offer")
for run in scoped:
    print("\n  [%s] %s" % (run.id, run.name or '?'))
    try:
        action = run.action_payroll_hr_version_list_view_payrun()
    except Exception as error:  # noqa: BLE001
        print("       the action raised: %s" % str(error).splitlines()[0])
        continue

    domain = action.get('domain') or []
    offered_ids = []
    for leaf in domain:
        if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == 'id':
            offered_ids = list(leaf[2] or [])
    offered = Version.browse(offered_ids).exists()
    print("       the dialog would list %s version(s)" % len(offered))
    names = sorted(set(offered.mapped('employee_id.name')))
    for name in names[:15]:
        print("           %s" % (name or '?'))
    if len(names) > 15:
        print("           ... and %s more" % (len(names) - 15))

    # Everybody in the company who is not on that list, and the two columns
    # most likely to be the reason.
    company = run.company_id
    everybody = Employee.search([('company_id', '=', company.id)])
    excluded = everybody.filtered(
        lambda e: e.sudo().version_id.id not in set(offered.ids))
    running = excluded.filtered(
        lambda e: e.sudo().contract_date_start
        and str(e.sudo().contract_date_start) <= TO
        and (not e.sudo().contract_date_end
             or str(e.sudo().contract_date_end) >= FROM))
    print("       %s employee(s) excluded, %s of them with a contract running"
          % (len(excluded), len(running)))

    run_type = run.structure_id.type_id
    by_reason = defaultdict(list)
    for employee in running:
        version = employee.sudo().version_id
        bits = []
        if run_type and version.structure_type_id.id != run_type.id:
            bits.append("structure type %s != run %s"
                        % (version.structure_type_id.name or '(none)',
                           run_type.name))
        if version.schedule_pay != run.schedule_pay:
            bits.append("schedule_pay %s != run %s"
                        % (version.schedule_pay or 'False',
                           run.schedule_pay or 'False'))
        by_reason[" AND ".join(bits) or
                  "no visible mismatch - look further"].append(employee.name or '?')
    for reason, people in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print("\n       %4s  %s" % (len(people), reason))
        for name in sorted(people)[:8]:
            print("             %s" % name)
        if len(people) > 8:
            print("             ... and %s more" % (len(people) - 8))

# ------------------------------------------------ the two columns, counted
title("4. schedule_pay and structure type across the company")
for run in scoped[:1]:
    company = run.company_id
    everybody = Employee.search([('company_id', '=', company.id)])
    by_schedule = defaultdict(int)
    by_type = defaultdict(int)
    for employee in everybody:
        version = employee.sudo().version_id
        by_schedule[version.schedule_pay or 'False'] += 1
        by_type[version.structure_type_id.name or '(none)'] += 1
    print("\n  %s" % (company.name or '?'))
    print("    schedule_pay on the employees' versions:")
    for value, count in sorted(by_schedule.items(), key=lambda kv: -kv[1]):
        print("      %4s  %s" % (count, value))
    print("    structure type:")
    for value, count in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print("      %4s  %s" % (count, value))

env.cr.rollback()
title("read only - the transaction was rolled back")
