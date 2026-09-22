"""An employee at one company whose contract belongs to another.

    cd ~/src/user

    # report only:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/fix_version_company.py

    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/fix_version_company.py

The Select Employees domain begins with ('company_id', '=', company) against
hr.version, and for Royal Arrow it returns seven versions. The company has
seventy eight employees. Every later leaf was filtering seven records, which is
why the structure type and schedule_pay looked innocent - they were.

hr.employee.company_id and hr.version.company_id are two separate stored
fields. Nothing keeps them in step, the employee list is built from the version
one, and every report anybody has run until now - including this session's own
eligibility probe - read the employee one. Sixty "eligible" employees were
counted off a field the pay run never consults.

WRITING IT IS LEGITIMATE, AND THE SOURCE SAYS SO

    company_id = fields.Many2one('res.company', compute='_compute_company_id',
                                 readonly=False, store=True, ...)

    @api.depends('employee_id.company_id')
    def _compute_company_id(self):
        for version in self:
            if version.employee_id:
                version.company_id = version.employee_id.company_id

  readonly=False, so the write sticks - and the value written is exactly what
  the compute itself would produce, so a later recompute agrees rather than
  reverting it. This is repairing a field that drifted from its own definition,
  not overriding one.

  BUT company_id has a dependant. _compute_structure_type_id is @api.depends on
  it, and it reassigns a default structure type whenever the version has none,
  or when its type's country differs from the company's. Both companies here
  are UAE so a set type survives, but an empty one would be filled with
  whatever structure type the country search happens to return first. So the
  structure type is captured before each write, compared after, and restored if
  it moved - a company fix that silently repoints somebody's salary structure
  is not a company fix.

WHICH ONE IS RIGHT IS NOT ASSUMED

  A version's company decides which journal the payroll entry hits, so moving
  it is a financial change, not a tidy-up. This prints, before writing:

    * both fields' definitions, so a related or delegated field is visible
      rather than inferred - if hr.employee.company_id turned out to be stored
      on the version after all, everything below would be wrong;
    * every (employee company -> version company) pair with its count;
    * which company the employee's existing payslips were issued under, and
      whether any of them are validated or paid. A draft payslip under the
      wrong company can be regenerated; a posted one has already reached the
      accounts and moving the version underneath it is not a repair.

  The employee's own company is treated as the truth, because it is what the
  attendance, the ssc payroll and the structure type all agree on. Anybody
  whose payslips are already validated or paid under the version's company is
  reported and NOT touched - that is a reversal to be decided, not applied.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

WIDTH = 116
APPLY = os.environ.get('SSC_APPLY') == '1'
FROM = os.environ.get('SSC_FROM') or '2026-08-01'
TO = os.environ.get('SSC_TO') or '2026-08-25'
SHOW = int(os.environ.get('SSC_SHOW') or 10)

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
Payslip = env['hr.payslip'].sudo()

# ------------------------------------------------------ 1. are they two fields
title("1. hr.employee.company_id and hr.version.company_id")
for model in (Employee, Version):
    field = model._fields.get('company_id')
    if field is None:
        print("  %-16s has no company_id" % model._name)
        continue
    print("  %-16s type=%-10s store=%s related=%s compute=%s"
          % (model._name, field.type, getattr(field, 'store', '?'),
             '.'.join(field.related) if getattr(field, 'related', None) else '-',
             getattr(field, 'compute', None) or '-'))
print("""
  hr.employee.company_id is related to resource_id.company_id; hr.version's is
  computed from employee_id.company_id with readonly=False. Two stored fields,
  two sources, and a manual write to either one persists - which is how they
  came to disagree, and why writing the version's is a repair rather than an
  override.""")

# ------------------------------------------------------------ 2. the mismatch
title("2. employees whose versions belong to another company")

mismatched = []          # (employee, version, employee company, version company)
for employee in Employee.search([]):
    company = employee.company_id
    if not company:
        continue
    for version in Version.search([('employee_id', '=', employee.id)]):
        if version.company_id.id != company.id:
            mismatched.append((employee, version, company, version.company_id))

if not mismatched:
    print("  none - every version sits under its employee's company")
pairs = defaultdict(list)
for employee, version, company, version_company in mismatched:
    pairs[((company.name or '?'), (version_company.name or '(none)'))].append(employee)
print("  %-42s %-42s %s" % ("employee's company", "version's company", "versions"))
print("  " + "-" * (WIDTH - 4))
for (company, version_company), people in sorted(
        pairs.items(), key=lambda kv: -len(kv[1])):
    print("  %-42s %-42s %s" % (company[:42], version_company[:42], len(people)))

# --------------------------------------------------- 3. what it already cost
title("3. the payslips those employees already hold")

employees = {e.id: e for e, _v, _c, _vc in mismatched}
blocked = set()
if employees:
    slips = Payslip.search([('employee_id', 'in', list(employees))])
    by_state = defaultdict(int)
    by_company = defaultdict(int)
    for slip in slips:
        by_state[slip.state] += 1
        by_company[slip.company_id.name or '?'] += 1
        if slip.state in ('validated', 'paid', 'done'):
            blocked.add(slip.employee_id.id)
    print("  %s payslip(s) in total, by state:" % len(slips))
    for state, count in sorted(by_state.items(), key=lambda kv: -kv[1]):
        print("      %5s  %s" % (count, state))
    print("  by the company the payslip was issued under:")
    for company, count in sorted(by_company.items(), key=lambda kv: -kv[1]):
        print("      %5s  %s" % (count, company))
    print("\n  %s employee(s) hold a validated or paid payslip - NOT touched"
          % len(blocked))
    for employee_id in sorted(blocked)[:SHOW]:
        print("      %s" % (employees[employee_id].name or '?'))
    if len(blocked) > SHOW:
        print("      ... and %s more" % (len(blocked) - SHOW))
else:
    print("  nothing to check")

# ------------------------------------------------- 4. what the run would gain
title("4. what a pay run would then see")
Run = env['hr.payslip.run'].sudo()
for run in Run.search([('date_start', '<=', TO), ('date_end', '>=', FROM)]):
    if not run.structure_id:
        continue
    now = len(Version.search([('company_id', '=', run.company_id.id)]))
    after = now + len([1 for _e, v, c, _vc in mismatched
                       if c.id == run.company_id.id and v.company_id.id != c.id])
    print("  [%s] %-58s versions visible now %3s  ->  %3s"
          % (run.id, (run.name or '?')[:58], now, after))

# ----------------------------------------------------------------------- write
title("summary")
movable = [(e, v, c) for e, v, c, _vc in mismatched if e.id not in blocked]
print("  %s version(s) sit under the wrong company" % len(mismatched))
print("  %s of them belong to employees with no validated or paid payslip"
      % len(movable))
print("  %s employee(s) are held back by a payslip that already posted"
      % len(blocked))

if not APPLY:
    env.cr.rollback()
    print("\n  report only - nothing written. Re-run with SSC_APPLY=1.")
else:
    moved = 0
    failures = []
    restored = []
    for employee, version, company in movable:
        # _compute_structure_type_id is @api.depends(company_id) and will
        # reassign a default to any version that has none. Hold it to account.
        was = version.structure_type_id
        try:
            with env.cr.savepoint():
                version.write({'company_id': company.id})
                if version.structure_type_id != was:
                    restored.append((employee.name or '?',
                                     was.name or '(none)',
                                     version.structure_type_id.name or '(none)'))
                    if was:
                        version.write({'structure_type_id': was.id})
            moved += 1
        except Exception as error:  # noqa: BLE001
            failures.append((employee.name or '?',
                             str(error).strip().splitlines()[0]))
    env.cr.commit()
    print("\n  %s version(s) moved onto their employee's company" % moved)
    if restored:
        print("  %s had their structure type moved by the compute:"
              % len(restored))
        for name, was, became in restored[:SHOW]:
            print("    %-34s %s -> %s%s"
                  % (name[:34], was, became,
                     "   (put back)" if was != "(none)" else "   (was empty)"))
        if len(restored) > SHOW:
            print("    ... and %s more" % (len(restored) - SHOW))
    if failures:
        print("  %s refused the write:" % len(failures))
        for name, reason in failures:
            print("    %-44s %s" % (name[:44], reason[:60]))
    print("\n  Re-open the pay run's Select Employees list - it reads this field.")
