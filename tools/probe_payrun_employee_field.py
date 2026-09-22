"""Where the Select Employees list comes from, read out of the running registry.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_payrun_employee_field.py

probe_payrun_wizard.py ruled out the two obvious answers. hr.payslip.run has no
struct_id and no structure_type_id - the run printed only its state and its
payslip count, so a run does not know Labour from Staff except by its own name.
And no ir.actions.act_window carries a domain that could filter employees.

That leaves the field itself. Odoo 19 puts the employee list on the pay run
form, so the filter is either the field's own domain, a domain written into the
form view's XML, or a compute that builds the list in Python. All three are
readable from the registry, and this reads all three rather than picking one:

  * every field on hr.payslip.run, with the ones pointing at hr.employee
    marked, plus their domain, compute and related attributes;
  * the arch of every form view on the model, because a domain written in XML
    beats the field's own and is invisible from the field alone;
  * the source of every method on the model, which is where a compute or an
    onchange would be doing it;
  * and the pay run in question against its own company: how many employees it
    could have offered, and how many it did.

Read-only.
"""
import inspect
import os

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


def show_source(obj, limit=70):
    try:
        lines = inspect.getsource(obj).splitlines()
    except Exception as error:  # noqa: BLE001
        print("    (source not available - %s)" % error)
        return
    for line in lines[:limit]:
        print("    " + line)
    if len(lines) > limit:
        print("    ... %s more line(s)" % (len(lines) - limit))


Run = env.get('hr.payslip.run')
if Run is None:
    print("hr.payslip.run is not installed here")
    raise SystemExit
Run = Run.sudo()

# ------------------------------------------------------------------ 1. fields
title("1. every field on hr.payslip.run")
print("  %-34s %-14s %-30s %s"
      % ("field", "type", "comodel", "domain / compute / related"))
print("  " + "-" * (WIDTH - 4))
employee_fields = []
for name in sorted(Run._fields):
    field = Run._fields[name]
    comodel = getattr(field, 'comodel_name', '') or ''
    bits = []
    domain = getattr(field, 'domain', None)
    if domain:
        bits.append("domain=%s" % (domain if isinstance(domain, str)
                                   else repr(domain)))
    if getattr(field, 'compute', None):
        bits.append("compute=%s" % field.compute)
    if getattr(field, 'related', None):
        bits.append("related=%s" % '.'.join(field.related))
    if comodel == 'hr.employee':
        employee_fields.append(name)
    mark = ">>" if comodel == 'hr.employee' else "  "
    print("%s %-34s %-14s %-30s %s"
          % (mark, name[:34], field.type, comodel[:30], "  ".join(bits)[:40]))

print("\n  field(s) pointing at hr.employee: %s"
      % (", ".join(employee_fields) or "NONE - the list is not a field on the run"))

# ------------------------------------------------------------------- 2. views
title("2. form views on hr.payslip.run - a domain in XML beats the field's own")
View = env['ir.ui.view'].sudo()
for view in View.search([('model', '=', 'hr.payslip.run')], order='priority, id'):
    print("\n  [%s] %s   type=%s   inherits=%s"
          % (view.id, view.name or '?', view.type,
             view.inherit_id.name if view.inherit_id else '-'))
    if view.type != 'form':
        continue
    arch = view.arch_db or ''
    for line in arch.splitlines():
        stripped = line.strip()
        # The interesting lines are the ones naming an employee or a domain.
        if any(word in stripped for word in
               ('employee', 'domain', 'struct', 'context', 'button')):
            print("      " + stripped[:WIDTH - 8])

# ----------------------------------------------------------------- 3. methods
title("3. methods on hr.payslip.run")
for name in sorted(n for n in dir(Run) if not n.startswith('__')):
    member = getattr(type(Run), name, None)
    if not callable(member) or not hasattr(member, '__module__'):
        continue
    module = getattr(member, '__module__', '') or ''
    if 'hr_payroll' not in module and 'hr.payslip' not in module:
        continue
    if not any(word in name for word in
               ('employee', 'generate', 'compute', 'payslip', 'onchange',
                'default', 'action')):
        continue
    print("\n  hr.payslip.run.%s   (%s)" % (name, module))
    show_source(member, limit=50)

# ------------------------------------------------------- 4. the run in question
title("4. the pay runs in the period, against their own company")
Employee = env['hr.employee'].sudo()
Structure = env['hr.payroll.structure'].sudo()

for run in Run.search([('date_start', '<=', TO), ('date_end', '>=', FROM)]):
    company = run.company_id
    if ONLY and not any(part in (company.name or '').upper() for part in ONLY):
        continue
    print("\n  [%s] %s" % (run.id, run.name or '?'))
    print("       company=%s   state=%s   payslips=%s"
          % (company.name or '-', run.state, len(run.slip_ids)))
    print("       dates %s .. %s" % (run.date_start, run.date_end))

    # Who is actually on it, and on which structure - the run has no structure
    # of its own, so the payslips are the only place the answer can live.
    by_structure = {}
    for slip in run.slip_ids:
        key = slip.struct_id.name or '(none)'
        by_structure.setdefault(key, []).append(slip.employee_id.name or '?')
    for structure, names in sorted(by_structure.items()):
        print("       %-46s %s  (%s)"
              % (structure[:46], ", ".join(sorted(names)[:6]), len(names)))

    everybody = Employee.search([('company_id', '=', company.id)])
    with_contract = everybody.filtered(
        lambda e: e.sudo().contract_date_start
        and str(e.sudo().contract_date_start) <= TO
        and (not e.sudo().contract_date_end
             or str(e.sudo().contract_date_end) >= FROM))
    print("       %s employee(s) in the company, %s with a contract running "
          "in the period" % (len(everybody), len(with_contract)))

    already = env['hr.payslip'].sudo().search([
        ('employee_id', 'in', with_contract.ids),
        ('date_from', '<=', TO), ('date_to', '>=', FROM)])
    print("       %s of them already hold a payslip in the period"
          % len(set(already.mapped('employee_id').ids)))
    free = with_contract.filtered(lambda e: e.id not in set(
        already.mapped('employee_id').ids))
    print("       %s free to be offered" % len(free))
    if free and len(free) <= 12:
        for employee in free:
            print("           %-40s %s"
                  % ((employee.name or '?')[:40],
                     employee.sudo().structure_type_id.name or '(no type)'))

env.cr.rollback()
title("read only - the transaction was rolled back")
