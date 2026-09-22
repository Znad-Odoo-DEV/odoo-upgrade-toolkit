"""Charge each employee's salary to the sites they actually worked on, so that
the payroll journal entry lands on those projects instead of nowhere.

    # report only, writes nothing:
    odoo-bin shell -d <database> --no-http < tools/set_contract_analytic.py

    # same again, this time writing:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/set_contract_analytic.py

Where the split comes from:

  labour  the machines they punch on. Their days over the last few months are
          counted per site and turned into percentages.
  staff   their project distribution, restricted to the on-going sites.

19.0 is what makes the split possible. 18.0 gave hr.contract a single
analytic_account_id, so a man on three sites still had to be charged to one and
the difference cleaned up by hand each month. 19.0 replaced it on hr.version
with analytic_distribution, a percentage map - so the same punch data that says
where he was now says how his salary divides, and the journal entry splits
itself. On 18 the script falls back to the busiest site.

Companies: a site worked by more than one company has one analytic account per
company. Each employee gets the one belonging to the company that pays them,
falling back to the account the project itself points at.

Run tools/migrate_projects_to_native.py first - this reads the id map it left
behind.
"""
import json
import os
import re
from collections import defaultdict
from datetime import date, timedelta

APPLY = os.environ.get('SSC_APPLY') == '1'

# Long enough to see the sites someone really works, short enough that a
# finished project stops counting.
LOOKBACK_DAYS = 90

# Below this, a site is noise - a day passing through on an errand, not work
# the site should carry. Those days are dropped and the rest re-based to 100.
MIN_SHARE = 5.0

ID_MAP_KEY = 'ssc.project_migration.id_map'
ONGOING_STAGE_KEY = 'ssc_payroll.ongoing_project_stage_id'
ANALYTIC_PLAN = 'Project'

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
param = env['ir.config_parameter'].sudo()

# 19.0 dissolved hr.contract into hr.version and hangs the live one off the
# employee; 18.0 keeps a separate contract with a state.
IS_VERSIONED = 'hr.version' in env
Contract = env['hr.version' if IS_VERSIONED else 'hr.contract'].sudo()

SscEmployee = env['ssc.employee'].sudo()
Line = env['ssc.attendance.line'].sudo()
Project = env['project.project'].sudo()
Analytic = env['account.analytic.account'].sudo()

DISTRIBUTES = 'analytic_distribution' in Contract._fields
if not DISTRIBUTES and 'analytic_account_id' not in Contract._fields:
    raise RuntimeError(
        f"{Contract._name} carries neither analytic_distribution nor "
        "analytic_account_id - hr_payroll_account provides them, so check that "
        "it is still installed."
    )


def title(text):
    print("\n" + "=" * 74)
    print(text)
    print("=" * 74)


# --- the two things migrate_projects_to_native.py left behind ---------------

raw_map = param.get_param(ID_MAP_KEY)
if not raw_map:
    raise RuntimeError(
        f"{ID_MAP_KEY} is empty - run tools/migrate_projects_to_native.py first.")
studio_to_project = {int(k): v for k, v in json.loads(raw_map).items()}

ongoing_stage_id = int(param.get_param(ONGOING_STAGE_KEY) or 0)
ongoing_project_ids = set(Project.search(
    [('stage_id', '=', ongoing_stage_id)]).ids) if ongoing_stage_id else set()

plan = env['account.analytic.plan'].sudo().search(
    [('name', '=', ANALYTIC_PLAN), ('parent_id', '=', False)], limit=1)
if not plan:
    raise RuntimeError(f"no root analytic plan named {ANALYTIC_PLAN!r}")

print(f"{len(studio_to_project)} project(s) mapped, "
      f"{len(ongoing_project_ids)} on-going, analytic plan {plan.id}")
print("writing " + ("a percentage distribution" if DISTRIBUTES
                    else "a single analytic account (18.0)"))


def analytic_for(project, company):
    """The account of ``project`` in ``company``'s books."""
    if not project:
        return Analytic.browse()
    candidates = Analytic.search([('plan_id', '=', plan.id), ('name', '=', project.name)])
    return (candidates.filtered(lambda a: a.company_id == company)
            or candidates.filtered(lambda a: not a.company_id)
            or project.account_id)[:1]


def as_percentages(weights):
    """Turn raw weights into percentages summing to exactly 100.

    Sites under MIN_SHARE are dropped and the rest re-based, so a single day
    passing through a neighbouring site does not end up on its books. The
    rounding remainder goes on the largest share.
    """
    total = sum(weights.values())
    if not total:
        return {}
    shares = {k: v * 100.0 / total for k, v in weights.items()}
    kept = {k: v for k, v in shares.items() if v >= MIN_SHARE} or shares
    total = sum(kept.values())
    out = {k: round(v * 100.0 / total, 2) for k, v in kept.items()}
    biggest = max(out, key=out.get)
    out[biggest] = round(out[biggest] + 100.0 - sum(out.values()), 2)
    return out


# --- labour: every site their punches say they worked ----------------------

title("1. reading the punches")

since = date.today() - timedelta(days=LOOKBACK_DAYS)
rows = Line._read_group(
    [('date', '>=', since), ('project_id', '!=', False), ('employee_id', '!=', False)],
    ['employee_id', 'project_id'],
    ['__count'],
)

# studio employee id -> {studio project id: days}
days_by_site = defaultdict(dict)
for studio_employee, studio_project, count in rows:
    days_by_site[studio_employee.id][studio_project.id] = count

print(f"  {len(rows)} employee/project pair(s) since {since}")
print(f"  {len(days_by_site)} employee(s) with punches")


# --- who is behind each contract -------------------------------------------

def normalise_badge(code):
    """Badges as hr.employee stores them: alphanumeric, upper case.

    ssc.employee keeps the badge as typed ('RA-03') while hr.employee only
    accepts alphanumerics, so the sync writes 'RA03' - and then looks the
    employee up by the unstripped value, which is why hr_employee_id is set on
    3 records out of 466.
    """
    return re.sub(r'[^A-Z0-9]', '', (code or '').upper())


by_hr_employee = {}
by_badge = {}
for emp in SscEmployee.search([]):
    if emp.hr_employee_id:
        by_hr_employee[emp.hr_employee_id.id] = emp
    badge = normalise_badge(emp.attendance_code)
    if badge:
        by_badge.setdefault(badge, emp)


def ssc_employee_of(hr_employee):
    return (by_hr_employee.get(hr_employee.id)
            or by_badge.get(normalise_badge(hr_employee.barcode)))


# --- one distribution per live contract ------------------------------------

title("2. matching contracts")

if IS_VERSIONED:                                                     # 19.0
    # is_current is computed without a search method, so the live version is
    # read off the employee. Every employee has one, contract or not, so a wage
    # is what separates the people actually employed from the rest.
    contracts = Contract.browse([
        employee.current_version_id.id
        for employee in env['hr.employee'].sudo().search([])
        if employee.current_version_id
    ]).filtered(lambda c: c.wage)
else:                                                                # 18.0
    contracts = Contract.search([('state', '=', 'open')], order='id')
print(f"  {len(contracts)} live contract(s) with a wage\n")

decided = []          # (contract, {account: percentage}, why)
skipped = {'no_ssc_employee': [], 'no_site': [], 'no_account': [], 'already': []}

for contract in contracts:
    if (contract.analytic_distribution if DISTRIBUTES else contract.analytic_account_id):
        skipped['already'].append(contract)
        continue

    ssc_employee = ssc_employee_of(contract.employee_id)
    if not ssc_employee:
        skipped['no_ssc_employee'].append(contract)
        continue

    if ssc_employee.is_engineer_office:
        # Staff: their own distribution, on-going sites only.
        weights = {
            line.project_id.id: line.percentage
            for line in ssc_employee.staff_project_ids
            if line.percentage
            and studio_to_project.get(line.project_id.id) in ongoing_project_ids
        }
        why = 'staff'
    else:
        # Labour: the days they punched, per site.
        weights = dict(days_by_site.get(ssc_employee.studio_ref_id, {}))
        why = f"{sum(weights.values())} day(s)"

    shares = as_percentages(weights)
    if not shares:
        skipped['no_site'].append(contract)
        continue

    # Studio project -> native project -> the account for this company. Two
    # Studio projects resolving to one account are merged rather than fighting.
    by_account = defaultdict(float)
    for studio_project_id, percentage in shares.items():
        project = Project.browse(studio_to_project.get(studio_project_id, 0)).exists()
        account = analytic_for(project, contract.company_id) if project else None
        if account:
            by_account[account] += percentage

    if not by_account:
        skipped['no_account'].append(contract)
        continue

    decided.append((contract, dict(by_account), why))

for contract, by_account, why in decided:
    parts = ", ".join(
        f"{a.code or a.name[:18]} {p:.0f}%"
        for a, p in sorted(by_account.items(), key=lambda kv: -kv[1])
    )
    print(f"  {contract.employee_id.name[:32]:<32} {parts}  ({why})")


# --- write, or say what would have been written ----------------------------

title("summary")

split = sum(1 for _c, by_account, _w in decided if len(by_account) > 1)
print(f"  matched            {len(decided)}   ({split} across more than one site)")
print(f"  already set        {len(skipped['already'])}")
print(f"  no ssc.employee    {len(skipped['no_ssc_employee'])}")
print(f"  no site found      {len(skipped['no_site'])}")
print(f"  no analytic found  {len(skipped['no_account'])}")

for contract in skipped['no_ssc_employee']:
    print(f"  ! {contract.employee_id.name}: no ssc.employee links to this hr.employee")
for contract in skipped['no_site']:
    print(f"  . {contract.employee_id.name}: no site found - left empty")
for contract in skipped['no_account']:
    print(f"  ! {contract.employee_id.name}: sites found but none has an analytic "
          f"account for {contract.company_id.name}")

if not APPLY:
    env.cr.rollback()
    print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write.")
else:
    for contract, by_account, _why in decided:
        if DISTRIBUTES:
            contract.analytic_distribution = {
                str(account.id): percentage for account, percentage in by_account.items()
            }
        else:
            biggest = max(by_account, key=by_account.get)
            contract.analytic_account_id = biggest.id
    env.cr.commit()
    print(f"\nwritten: {len(decided)} contract(s) now carry their site split.")
