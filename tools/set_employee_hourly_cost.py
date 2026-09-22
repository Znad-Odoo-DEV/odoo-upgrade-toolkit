"""Give every employee an hourly cost taken from their own contract, so that a
timesheet hour is worth something and project labour cost stops reading zero.

    # report only, writes nothing:
    odoo-bin shell -d <database> --no-http < tools/set_employee_hourly_cost.py

    # same again, this time writing:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/set_employee_hourly_cost.py

The rate is the cost of one ORDINARY hour:

    contract wage / 30 / hours per day

Everything comes from the contract: the wage it was signed at, and the hours
per day of the working schedule attached to it (eight when none is set). No
ssc.employee, no badge matching, no custom field - hr.contract.wage and
hr.employee.hourly_cost are both native, so this stays true whatever happens to
the Studio side later.

The running contract wins; someone between contracts is priced off their most
recent one rather than left at zero.

Deliberately NOT the overtime rate: that is a real per-hour amount, but it
carries the overtime premium, and using it would price every ordinary hour as
if it were worked late.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'

# A monthly wage divided over 30 days, the same divisor the payroll side
# already uses for its daily rate, so the two never contradict each other.
DAYS_PER_MONTH = 30.0
DEFAULT_HOURS_PER_DAY = 8.0

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

HrEmployee = env['hr.employee'].sudo()

# 19.0 dissolved hr.contract into hr.version and hangs the live one off the
# employee; 18.0 keeps a separate contract with a state. Same question either
# way: which agreement is this person working under right now.
IS_VERSIONED = 'hr.version' in env


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# --- one contract per employee: the running one, else the most recent --------

title("1. contracts")

if IS_VERSIONED:                                                     # 19.0
    Contract = env['hr.version'].sudo()
    contracts = Contract.search([])
    chosen = {}
    for employee in HrEmployee.search([]):
        version = employee.current_version_id
        if version:
            chosen[employee.id] = version
    print(f"  {len(contracts)} version(s), {len(chosen)} current")
else:                                                                # 18.0
    Contract = env['hr.contract'].sudo()
    contracts = Contract.search([], order='date_start desc, id desc')
    print(f"  {len(contracts)} contract(s), "
          f"{len(contracts.filtered(lambda c: c.state == 'open'))} running")
    chosen = {}
    for contract in contracts:
        employee_id = contract.employee_id.id
        current = chosen.get(employee_id)
        if current is None:
            chosen[employee_id] = contract
        elif current.state != 'open' and contract.state == 'open':
            chosen[employee_id] = contract

print(f"  covering {len(chosen)} employee(s)")


# --- price them --------------------------------------------------------------

title("2. rates")

employees = HrEmployee.search([])
decided = []
skipped = {'no_contract': [], 'no_wage': [], 'already': []}

for hr_employee in employees:
    if hr_employee.hourly_cost:
        skipped['already'].append(hr_employee)
        continue

    contract = chosen.get(hr_employee.id)
    if not contract:
        skipped['no_contract'].append(hr_employee)
        continue
    if not contract.wage:
        skipped['no_wage'].append(hr_employee)
        continue

    hours = contract.resource_calendar_id.hours_per_day or DEFAULT_HOURS_PER_DAY
    rate = contract.wage / DAYS_PER_MONTH / hours
    decided.append((hr_employee, contract, hours, rate))

for hr_employee, contract, hours, rate in decided:
    state = '' if IS_VERSIONED else contract.state
    running = '' if state in ('', 'open') else f"  [{state}]"
    print(f"  {hr_employee.name[:36]:<36} wage {contract.wage:>9,.0f}  "
          f"{hours:>4.1f} h/day  ->  {rate:>7.2f} /hour"
          f"  = {contract.wage / DAYS_PER_MONTH:>7.2f} /day{running}")


title("summary")

print(f"  priced             {len(decided)}")
print(f"  already priced     {len(skipped['already'])}")
print(f"  no contract        {len(skipped['no_contract'])}")
print(f"  contract has no wage {len(skipped['no_wage'])}")

for hr_employee in skipped['no_wage']:
    print(f"  . {hr_employee.name}: contract carries no wage")

if decided:
    rates = sorted(rate for *_, rate in decided)
    middle = rates[len(rates) // 2]
    print(f"\n  lowest {rates[0]:.2f} | median {middle:.2f} | highest {rates[-1]:.2f} per hour")

if not APPLY:
    env.cr.rollback()
    print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write.")
else:
    for hr_employee, _contract, _hours, rate in decided:
        hr_employee.hourly_cost = rate
    env.cr.commit()
    print(f"\nwritten: {len(decided)} employee(s) now have an hourly cost.")
