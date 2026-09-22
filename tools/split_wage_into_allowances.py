"""Put the basic salary in wage and the allowances in their own fields.

    odoo-bin shell -d <database> --no-http < tools/split_wage_into_allowances.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/split_wage_into_allowances.py

Every contract carries the whole gross figure in `wage` and nothing in the
allowance fields the UAE localisation provides. That was fine while nothing
read them, and it stops being fine the moment payroll does, because the
localisation derives the hourly wage from `wage` - so overtime would be priced
off a number that includes housing and other allowances.

    hourly = (wage + housing + transportation + other) / hours

Overtime in this company is priced off the basic salary alone. An employee on
1000 basic and 1600 gross earns 5.21 an hour of overtime, not 8.33. Leaving the
gross in `wage` overpays every overtime hour by sixty percent before a single
rule is written.

WHAT MOVES WHERE

    ssc_employee.basic_salary        -> hr.version.wage
    ssc_employee.house_allowance     -> l10n_ae_housing_allowance
    ssc_employee.transport_allowance -> l10n_ae_transportation_allowance
    ssc_employee.other_allowance     -> l10n_ae_other_allowances

The localisation then computes l10n_ae_total_salary as the sum of the four,
which is the same arithmetic ssc_employee already uses for gross_salary. So the
check is exact and needs no payslip: after this runs, every contract's
l10n_ae_total_salary must equal the gross the payroll in use today pays. Any
employee where it does not is printed rather than guessed at.

WHICH SIDE IS RIGHT WHEN THEY DISAGREE

ssc_employee, and its payslips where it has nothing to say. Six staff carry a
zero on their employee record and are paid every month regardless, the real
figure sitting on the payslip; the payslip names its fields the same way, so it
stands in without anything else having to know.

It is the system paying these people this month, and the
contracts were priced from a snapshot that missed two different things: a
handful of people have had a raise since, and seventy six were never priced at
all and sit at zero while the company pays them. Both are listed by name, worst
first, so the size of each gap is visible rather than averaged away.

Nothing here is paid yet, by either system, so this is safe to run and safe to
run again.
"""
import os
import re

APPLY = os.environ.get('SSC_APPLY') == '1'

env = env(context=dict(  # noqa: F821
    env.context, lang='en_US', active_test=False,  # noqa: F821
    tracking_disable=True, mail_create_nolog=True,
    mail_create_nosubscribe=True, mail_auto_subscribe_no_notify=True,
    mail_notify_force_send=False,
))

Employee = env['hr.employee'].sudo()
Version = env['hr.version'].sudo()
Ssc = env['ssc.employee'].sudo() if 'ssc.employee' in env else None

FIELDS = ('wage', 'l10n_ae_housing_allowance',
          'l10n_ae_transportation_allowance', 'l10n_ae_other_allowances')


def title(text):
    print()
    print("=" * 96)
    print(text)
    print("=" * 96)


def badge(value):
    return re.sub(r'[^A-Za-z0-9]', '', (value or '').strip())[:18].upper()


if Ssc is None:
    print("ssc.employee is not on this database - nothing to do")
    raise SystemExit

missing = [name for name in FIELDS if name not in Version._fields]
if missing:
    print(f"hr.version has no {missing} - is l10n_ae_hr_payroll installed?")
    raise SystemExit

# ---------------------------------------------------------------------------
title("1. matching the payroll records to the contracts")

by_badge = {}
for employee in Employee.search([]):
    if employee.barcode:
        by_badge.setdefault(badge(employee.barcode), employee)

pay = {}
for record in Ssc.with_context(active_test=False).search([]):
    employee = record.hr_employee_id or by_badge.get(badge(record.attendance_code))
    if employee:
        pay.setdefault(employee.id, record)

print(f"  ssc.employee records     : {Ssc.with_context(active_test=False).search_count([])}")
print(f"  matched to an employee   : {len(pay)}")

# ---------------------------------------------------------------------------
title("2. what changes")

# Six staff carry no salary on their ssc.employee record and are paid every
# month all the same - the figure lives on their payslips instead. A payslip
# names its fields identically, so it stands in for the employee record and
# nothing downstream has to know the difference.
Slip = env['ssc.payslip'].sudo() if 'ssc.payslip' in env else None


def priced_from_a_payslip(employee):
    if Slip is None:
        return None
    return Slip.search([('hr_employee_id', '=', employee.id),
                        ('gross_salary', '>', 0)],
                       order='from_date desc', limit=1) or None


planned, unpriced, no_version, unchanged = [], [], [], 0
from_payslip = []
for employee in Employee.with_context(active_test=True).search([]):
    record = pay.get(employee.id)
    if not record or not record.gross_salary:
        fallback = priced_from_a_payslip(employee)
        if not fallback:
            if record:
                unpriced.append(employee)
            continue
        from_payslip.append(employee)
        record = fallback
    version = employee.current_version_id
    if not version:
        no_version.append(employee)
        continue
    wanted = {
        'wage': record.basic_salary,
        'l10n_ae_housing_allowance': record.house_allowance,
        'l10n_ae_transportation_allowance': record.transport_allowance,
        'l10n_ae_other_allowances': record.other_allowance,
    }
    if all(abs((version[name] or 0.0) - value) < 0.01 for name, value in wanted.items()):
        unchanged += 1
        continue
    planned.append((employee, version, record, wanted))

print(f"  contracts to rewrite     : {len(planned)}")
print(f"  priced from a payslip    : {len(from_payslip)}")
for employee in sorted(from_payslip, key=lambda e: e.name):
    print(f"      {employee.name}")
print(f"  already correct          : {unchanged}")
print(f"  priced at zero, skipped  : {len(unpriced)}")
print(f"  no current contract      : {len(no_version)}")
print()
print(f"  {'employee':<32} {'wage now':>10} {'-> basic':>10} {'house':>8} "
      f"{'transp':>8} {'other':>9} {'= gross':>10}")
for employee, version, record, wanted in sorted(planned, key=lambda x: x[0].name)[:15]:
    print(f"  {employee.name[:32]:<32} {version.wage:>10.2f} {wanted['wage']:>10.2f} "
          f"{wanted['l10n_ae_housing_allowance']:>8.2f} "
          f"{wanted['l10n_ae_transportation_allowance']:>8.2f} "
          f"{wanted['l10n_ae_other_allowances']:>9.2f} {record.gross_salary:>10.2f}")
if len(planned) > 15:
    print(f"  ... and {len(planned) - 15} more")

# ---------------------------------------------------------------------------
title("3. contracts whose wage disagrees with the payroll in use")

disagree = [(e, v, r) for e, v, r, _w in planned
            if abs((v.wage or 0.0) - r.gross_salary) > 0.01
            and abs((v.wage or 0.0) - r.basic_salary) > 0.01]
print(f"  {len(disagree)} employee(s) - ssc_employee is taken as right")
for employee, version, record in sorted(disagree, key=lambda x: abs(
        (x[1].wage or 0) - x[2].gross_salary), reverse=True):
    gap = record.gross_salary - (version.wage or 0.0)
    flag = '  <-- look at this one' if abs(gap) >= 1000 else ''
    print(f"  {employee.name[:34]:<34} contract {version.wage:>9.2f}   "
          f"payroll {record.gross_salary:>9.2f}   gap {gap:>9.2f}{flag}")

# ---------------------------------------------------------------------------
title("4. what the total wage bill becomes")

before = sum((v.wage or 0.0) for _e, v, _r, _w in planned)
after = sum(r.gross_salary for _e, _v, r, _w in planned)
print(f"  gross on the contracts today   {before:>12,.2f}")
print(f"  gross after this runs          {after:>12,.2f}")
print(f"  difference                     {after - before:>12,.2f}")
never = [1 for _e, v, _r, _w in planned if not v.wage]
print()
print(f"  Almost none of that is a raise. {len(never)} of these contracts carry no")
print("  wage at all - the company pays those people every month and their")
print("  contract in Odoo says zero. The rest is the handful whose salary")
print("  changed after the contract was priced.")

# ---------------------------------------------------------------------------
if APPLY:
    written, failed = 0, []
    for employee, version, record, wanted in planned:
        try:
            with env.cr.savepoint():
                version.write(wanted)
            written += 1
        except Exception as error:
            failed.append((employee.name, str(error).splitlines()[0][:70]))
    env.cr.commit()

    title("APPLIED")
    print(f"  rewritten {written} | refused {len(failed)}")
    for name, message in failed:
        print(f"      {name[:30]:<30} {message}")

    # The localisation sums the four fields itself. If its total does not
    # match the payroll being paid today, something did not land.
    wrong = []
    for employee, version, record, _w in planned:
        total = version.l10n_ae_total_salary
        if abs(total - record.gross_salary) > 0.01:
            wrong.append((employee.name, total, record.gross_salary))
    print()
    print(f"  contracts whose total now equals the payroll gross: "
          f"{len(planned) - len(wrong)} / {len(planned)}")
    for name, total, gross in wrong:
        print(f"      MISMATCH {name[:30]:<30} {total:>10.2f} vs {gross:>10.2f}")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
