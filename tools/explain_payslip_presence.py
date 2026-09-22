"""Why this person has a native payslip at all, and where the amount came from.

    cd ~/src/user
    SSC_EMPLOYEE="Mandeep Singh Raj Singh" odoo-bin shell -d <database> \
        --no-http 2>/dev/null < tools/explain_payslip_presence.py

Mandeep Singh Raj Singh's August payslip pays 96.77 AED - BASIC only, every
allowance zero, NET the same. 96.77 is 3000 / 31, one day of a three thousand
dirham wage. He is also one of the thirty two Saud employees the reconciliation
lists as native-only: Odoo paid him and ssc_payroll did not.

Two questions, and they have different answers:

  where the day came from   the ratio rule prices (period days - absent) over
      days in month, and the work entries decide what counts as absent. One day
      of BASIC means the entries cover one day, which is a fact about the
      entries and not about the wage.

  why he is on the run at all   a native pay run offers anybody whose contract
      is running in the period, and it never consults ssc.employee. Whatever
      marks him finished on the ssc side - cancelled, a departure date, an
      archived record - is invisible to it. Only hr.version's contract dates
      and hr.employee.active are.

So this prints both sides of that: what ssc thinks of him, what hr thinks of
him, the contract dates the pay run actually read, every work entry in the
period with its type and state, and the payslip's own lines and worked days.

Read-only.
"""
import os
from collections import defaultdict

WIDTH = 112
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
WANTED = (os.environ.get('SSC_EMPLOYEE') or 'Mandeep Singh').strip().lower()

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value, width=12):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


Employee = env['hr.employee'].sudo()
Payslip = env['hr.payslip'].sudo()
WorkEntry = env['hr.work.entry'].sudo()
SscEmployee = env.get('ssc.employee')
SscSlip = env.get('ssc.payslip')

found = Employee.search([]).filtered(lambda e: WANTED in (e.name or '').lower())
if not found:
    print("no employee matching %r" % WANTED)
    raise SystemExit

for employee in found:
    title("%s   -   %s" % (employee.name or '?', employee.company_id.name or '-'))

    # ------------------------------------------------------ what hr thinks
    version = employee.sudo().version_id
    print("  hr.employee")
    print("      active                 %s" % employee.active)
    for field in ('departure_date', 'departure_reason_id', 'employee_type'):
        if field in employee._fields and employee[field]:
            value = employee[field]
            print("      %-22s %s" % (field, getattr(value, 'name', value)))
    print("      version [%s]  contract %s .. %s   wage %s"
          % (version.id, version.contract_date_start or 'none',
             version.contract_date_end or 'open', num(version.wage)))
    print("      structure type         %s"
          % (version.structure_type_id.name or 'none'))
    print("      company on the version %s"
          % (version.company_id.name or 'none'))

    # ----------------------------------------------------- what ssc thinks
    print("")
    print("  ssc.employee")
    profile = SscEmployee.sudo().search(
        [('hr_employee_id', '=', employee.id)], limit=1) \
        if SscEmployee is not None else None
    if not profile:
        print("      no ssc.employee is linked to this hr.employee at all")
    else:
        print("      [%s] %s" % (profile.id, profile.display_name))
        for field in ('is_cancelled', 'is_engineer_office', 'joining_date',
                      'employee_code', 'active', 'total_salary', 'basic_salary'):
            if field in profile._fields:
                print("      %-22s %s" % (field, profile[field]))

    if SscSlip is not None and profile:
        ssc_slips = SscSlip.sudo().search([('employee_id', '=', profile.id),
                                           ('month', '=', MONTH),
                                           ('year', '=', str(YEAR))])
        print("      ssc payslip(s) for %s-%s: %s"
              % (MONTH, YEAR, len(ssc_slips) or "none"))

    # ------------------------------------------------------- the payslips
    slips = Payslip.search([('employee_id', '=', employee.id)]).filtered(
        lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
        and str(s.date_from.year) == str(YEAR))
    for slip in slips:
        title("native payslip [%s]  %s .. %s  state=%s  %s"
              % (slip.id, slip.date_from, slip.date_to, slip.state,
                 slip.struct_id.name or '?'), '-')
        print("    lines:")
        for line in slip.line_ids.sorted(lambda l: l.sequence):
            print("        seq %-5s %-22s %s" % (line.sequence,
                                                 line.code or '?',
                                                 num(line.total)))
        print("    worked days lines:")
        if not slip.worked_days_line_ids:
            print("        none - nothing tells the rule any day was worked")
        for line in slip.worked_days_line_ids:
            print("        %-36s %7s day(s) %8s hour(s) %s"
                  % ((line.name or line.code or '?')[:36], line.number_of_days,
                     line.number_of_hours, num(line.amount)))
        if slip.input_line_ids:
            print("    salary inputs:")
            for line in slip.input_line_ids:
                print("        %-22s %s" % (line.code or '?', num(line.amount)))

        # The arithmetic, spelled out.
        basic = sum(l.total for l in slip.line_ids if l.code == 'BASIC')
        wage = version.wage or 0.0
        if wage:
            print("    BASIC %s of a wage of %s is a ratio of %.4f"
                  % (num(basic), num(wage), basic / wage))
            print("    which over a 31 day month is %.2f day(s)"
                  % (basic / wage * 31))

        entries = defaultdict(lambda: [0, 0.0])
        for entry in WorkEntry.search([('employee_id', '=', employee.id),
                                       ('date', '>=', str(slip.date_from)),
                                       ('date', '<=', str(slip.date_to))]):
            key = (entry.work_entry_type_id.name or '?', entry.state)
            entries[key][0] += 1
            entries[key][1] += entry.duration if 'duration' in entry._fields else 0.0
        print("    work entries in the period:")
        if not entries:
            print("        none at all")
        for (name, state), (count, hours) in sorted(entries.items()):
            mark = "   <-- counts toward the payslip" if state != 'cancelled' else ""
            print("        %-36s %-11s %4s entry(ies) %8.1f h%s"
                  % (name[:36], state, count, hours, mark))

    if not slips:
        print("")
        print("  no native payslip for %s-%s" % (MONTH, YEAR))

env.cr.rollback()
title("read only - nothing was written")
