"""Why an employee is not offered when a pay run asks you to select employees.

    cd ~/src/user
    SSC_COMPANIES="ROYAL ARROW" odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/probe_payrun_eligibility.py

    SSC_FROM=2026-08-01 SSC_TO=2026-08-25 odoo-bin shell -d <database> \
        --no-http 2>/dev/null < tools/probe_payrun_eligibility.py

Royal Arrow has fifty two labourers on the ssc side and the pay run's Select
Employees dialog offers two. Odoo filters that list rather than showing
everybody, and it filters on three separate things - so "only two appear" has
three possible causes and guessing between them wastes a morning.

For every employee of the company this prints, per person:

  * the salary structure type on their running contract, and whether any pay
    structure is attached to it. A structure type nothing points at cannot be
    paid, and it is the commonest reason a whole company goes missing;
  * contract_date_start and contract_date_end against the period. A contract
    starting after the period, or ended before it, is not running in it - and
    a contract with no start date at all is the quietest version of that;
  * whether they already have a payslip in the period, because Odoo will not
    offer somebody twice.

Then the same counted, so the shape of the problem is one line rather than
fifty.

Read-only.
"""
import os
from collections import defaultdict
from datetime import date

WIDTH = 118
FROM = date.fromisoformat(os.environ.get('SSC_FROM') or '2026-08-01')
TO = date.fromisoformat(os.environ.get('SSC_TO') or '2026-08-25')
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or '').split(',') if n.strip()]
SHOW = int(os.environ.get('SSC_SHOW') or 25)

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


Payslip = env['hr.payslip'].sudo()
Structure = env['hr.payroll.structure'].sudo()

# A structure type with no pay structure behind it can never produce a payslip.
structures_by_type = defaultdict(list)
for structure in Structure.search([]):
    if structure.type_id:
        structures_by_type[structure.type_id.id].append(structure)

title("pay run eligibility for %s .. %s" % (FROM, TO))

companies = env['res.company'].sudo().search([], order='id')
for company in companies:
    if ONLY and not any(part in (company.name or '').upper() for part in ONLY):
        continue

    employees = env['hr.employee'].sudo().search(
        [('company_id', '=', company.id)])
    if not employees:
        continue

    title(company.name or '?', '-')
    print("  %s active employee(s)" % len(employees))

    # Everybody already holding a payslip in the window.
    already = set()
    for slip in Payslip.search([
            ('employee_id', 'in', employees.ids),
            ('date_from', '<=', TO), ('date_to', '>=', FROM)]):
        already.add(slip.employee_id.id)

    reasons = defaultdict(list)
    for employee in employees:
        version = employee.sudo()
        structure_type = version.structure_type_id
        start = version.contract_date_start
        end = version.contract_date_end

        if not structure_type:
            reasons["no salary structure type on the contract"].append(employee)
        elif not structures_by_type.get(structure_type.id):
            reasons["structure type '%s' has no pay structure attached"
                    % (structure_type.name or '?')].append(employee)
        elif not start:
            reasons["no contract start date"].append(employee)
        elif start > TO:
            reasons["contract starts after the period (%s)" % start].append(employee)
        elif end and end < FROM:
            reasons["contract ended before the period (%s)" % end].append(employee)
        elif employee.id in already:
            reasons["already has a payslip in this period"].append(employee)
        else:
            reasons["ELIGIBLE - should appear in the dialog"].append(employee)

    for why, people in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
        mark = "  " if why.startswith("ELIGIBLE") else "!!"
        print("\n  %s %4s  %s" % (mark, len(people), why))
        names = sorted(p.name or '?' for p in people)
        for name in names[:SHOW]:
            print("           %s" % name)
        if len(names) > SHOW:
            print("           ... and %s more" % (len(names) - SHOW))

    # The structure types in play, so a mismatch is visible rather than inferred.
    title("%s: structure types in use" % (company.name or '?'), '.')
    by_type = defaultdict(int)
    for employee in employees:
        by_type[employee.sudo().structure_type_id] += 1
    for structure_type, count in sorted(
            by_type.items(), key=lambda kv: -kv[1]):
        structures = structures_by_type.get(structure_type.id, []) if structure_type else []
        print("  %4s  %-46s -> %s"
              % (count, (structure_type.name if structure_type else '(none)')[:46],
                 ", ".join(s.name or '?' for s in structures) or "NO STRUCTURE"))

title("read only - nothing was written")
