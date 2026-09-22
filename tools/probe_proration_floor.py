"""Where three days comes from when nothing was worked.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_proration_floor.py

    SSC_EMPLOYEE="Mandeep Singh" ...     # reproduce on somebody in particular

Every payslip for a leaver paid the same shape: BASIC at 3/31 of the wage, no
allowances, nothing else. Mandeep Singh Raj Singh at 1,000 x 3/31 = 96.77.
Kamlesh, Parfait and Ahmad Ali Sameu showed exactly 3.00 days before their
overtime lines were rebuilt. Three is not a coincidence and it is not a
calculation of anything.

The formula I have on record is

    ratio = (period_days - absent) / days_in_month

which over 1..25 August in a 31 day month gives 3/31 only if absent is 22. With
no work entries at all, absent ought to be zero and the answer 25/31. So either
absent is not what I think, or the live rule is not the rule I have. Reading it
is cheaper than reasoning about it, and today has settled four of these by
reading and none by reasoning.

WHAT IT DOES

  Prints the live BASIC and RATIO rule source from each Labour structure - what
  production runs, not what the repo says. Then takes an employee with no live
  work entry in the period, creates a payslip for them inside a savepoint,
  computes it, and dumps the worked-days lines and every value the rule had to
  work with, before rolling the whole thing back.

  The payslips that showed this are deleted, so the only way to see the
  arithmetic again is to reproduce it. Nothing is kept.

Read-only: the payslip is created inside a savepoint and discarded.
"""
import os

WIDTH = 112
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
FROM = os.environ.get('SSC_FROM') or '2026-08-01'
TO = os.environ.get('SSC_TO') or '2026-08-25'
WANTED = (os.environ.get('SSC_EMPLOYEE') or '').strip().lower()
SUFFIX = 'Labour Pay'

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


Rule = env['hr.salary.rule'].sudo()
Structure = env['hr.payroll.structure'].sudo()
Payslip = env['hr.payslip'].sudo()
Employee = env['hr.employee'].sudo()
WorkEntry = env['hr.work.entry'].sudo()

# --------------------------------------------------- 1. the rule, as it runs
title("1. the live BASIC rule in each Labour structure")
seen = set()
structures = Structure.search([]).filtered(
    lambda s: (s.name or '').endswith(SUFFIX))
for structure in structures:
    for rule in Rule.search([('struct_id', '=', structure.id),
                             ('active', '=', True)]):
        if rule.code not in ('BASIC', 'RATIO', 'WORKED_RATIO'):
            continue
        body = rule.amount_python_compute or ''
        key = (rule.code, body)
        if key in seen:
            continue
        seen.add(key)
        print("")
        print("  [%s] %-10s seq %-5s %-28s   %s"
              % (rule.id, rule.code, rule.sequence, (rule.name or '')[:28],
                 structure.name or '?'))
        print("      amount_select=%s  condition_select=%s"
              % (rule.amount_select, rule.condition_select))
        for line in body.splitlines():
            print("      | %s" % line)
if not seen:
    print("  no BASIC rule found in any Labour structure")

# ------------------------------------------- 2. somebody with nothing worked
title("2. an employee with no live work entry in %s .. %s" % (FROM, TO))
candidate = None
for employee in Employee.search([('company_id', '!=', False)]):
    if WANTED and WANTED not in (employee.name or '').lower():
        continue
    version = employee.sudo().version_id
    if not version.contract_date_start or not version.structure_type_id:
        continue
    if version.contract_date_end and str(version.contract_date_end) < TO:
        continue
    structure = next((s for s in structures
                      if s.type_id == version.structure_type_id), None)
    if not structure:
        continue
    live = WorkEntry.search_count([
        ('employee_id', '=', employee.id), ('date', '>=', FROM),
        ('date', '<=', TO), ('state', '!=', 'cancelled')])
    if live:
        continue
    candidate = (employee, version, structure)
    break

if not candidate:
    print("  none found - every employee in scope has live work entries")
    env.cr.rollback()
    raise SystemExit

employee, version, structure = candidate
print("  %s   -   %s" % (employee.name or '?', employee.company_id.name or '-'))
print("      wage %s   contract %s .. %s   structure %s"
      % (version.wage, version.contract_date_start,
         version.contract_date_end or 'open', structure.name or '?'))

# ------------------------------------------- 3. reproduce it in a savepoint
title("3. a payslip for them, computed and then discarded")
try:
    with env.cr.savepoint():
        slip = Payslip.create({
            'employee_id': employee.id,
            'date_from': FROM,
            'date_to': TO,
            'struct_id': structure.id,
            'name': 'proration floor probe',
        })
        slip.with_context(active_test=True).compute_sheet()

        print("  worked days lines:")
        if not slip.worked_days_line_ids:
            print("      none")
        for line in slip.worked_days_line_ids:
            print("      %-36s code=%-14s %7s day(s) %8s hour(s) %s"
                  % ((line.name or '?')[:36], line.code or '?',
                     line.number_of_days, line.number_of_hours, line.amount))

        print("")
        print("  lines:")
        for line in slip.line_ids.sorted(lambda l: l.sequence):
            print("      seq %-5s %-16s %12.2f" % (line.sequence,
                                                   line.code or '?', line.total))

        localdict = slip._get_localdict()
        print("")
        print("  what the rule could see:")
        print("      worked_days keys   %s" % sorted(localdict['worked_days']))
        for code, line in sorted(localdict['worked_days'].items()):
            print("          %-16s days=%s hours=%s amount=%s"
                  % (code, line.number_of_days, line.number_of_hours,
                     line.amount))
        print("      inputs keys        %s" % sorted(localdict['inputs']))
        print("      version.wage       %s" % localdict['version'].wage)
        print("      payslip dates      %s .. %s" % (slip.date_from, slip.date_to))

        basic = sum(l.total for l in slip.line_ids if l.code == 'BASIC')
        wage = version.wage or 0.0
        if wage:
            print("")
            print("      BASIC %.2f / wage %.2f = %.6f" % (basic, wage, basic / wage))
            print("      x 31 = %.2f day(s)" % (basic / wage * 31))
            print("      x 25 = %.2f day(s) of the period" % (basic / wage * 25))
        raise RuntimeError('discard')
except RuntimeError as error:
    if str(error) != 'discard':
        raise
except Exception as error:  # noqa: BLE001
    print("  could not build one: %s: %s"
          % (type(error).__name__, str(error).strip().splitlines()[0]))

env.cr.rollback()
title("read only - the payslip was discarded")
