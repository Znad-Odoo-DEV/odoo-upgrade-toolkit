"""Put the public holidays onto the working calendars.

    cd ~/src/user

    # report only, writes nothing:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/load_public_holidays.py

    # same again, this time writing:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http 2>/dev/null < tools/load_public_holidays.py

The list lives in payroll_rules/public_holidays.csv, in git, because a public
holiday is a decision about pay: hours worked on one are off-day overtime, and a
holiday block next to an absent working day carries its own penalty. Both read
the calendar, and today the calendar holds none, so both silently never fire.

Each holiday becomes a resource.calendar.leaves row with:

  * no calendar - so it applies to every working schedule, including any made
    later, rather than to the one that happens to be in use today;
  * no resource - so it applies to everybody rather than one person;
  * work entry type AEPUBLICH, so Odoo's own reports agree with our rules.

One row is created PER COMPANY. The company on a calendar leave is computed and
readonly:

    leave.company_id = leave.calendar_id.company_id or self.env.company

so it cannot be left empty - it silently becomes whichever company the shell
happens to run as, and multi-company rules would then hide the holiday from the
other three. Four rows per holiday is the honest way to say "all four".

Dates are stored as a full local day converted to UTC. Dubai is UTC+4 with no
daylight saving, ever, so 1 January is stored as 31 December 20:00 to 1 January
19:59 - correct, and worth knowing before it looks like an off-by-one.

Existing holidays are matched by date and left alone, so this can be re-run
after adding the Islamic dates without duplicating anything.

Reads only unless SSC_APPLY=1.
"""
import os

import pytz

from odoo import fields as odoo_fields

APPLY = os.environ.get('SSC_APPLY') == '1'
SOURCE = os.path.abspath(os.environ.get('SSC_HOLIDAYS')
                         or 'payroll_rules/public_holidays.csv')
TZ_NAME = os.environ.get('SSC_TZ') or 'Asia/Dubai'
CODE = os.environ.get('SSC_HOLIDAY_CODE') or 'AEPUBLICH'

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 88


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def read_file(path):
    """[(date string, name)] from the csv, or a problem to report."""
    if not os.path.isfile(path):
        return [], f"no such file: {path}"
    wanted = []
    with open(path, encoding='utf-8') as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ',' not in line:
                print(f"  ! line {number} has no comma, ignored: {line[:60]}")
                continue
            day, name = line.split(',', 1)
            day, name = day.strip(), name.strip()
            try:
                odoo_fields.Date.to_date(day)
            except Exception:                                    # noqa: BLE001
                print(f"  ! line {number} is not a date, ignored: {day}")
                continue
            wanted.append((day, name))
    return wanted, None


title("1. the list in the repo")

print(f"  {SOURCE}")
wanted, problem = read_file(SOURCE)
if problem:
    print(f"  !! {problem}")
    print("  Run from the repo root, or set SSC_HOLIDAYS to the file.")
else:
    print(f"  {len(wanted)} holiday(s) listed")
    for day, name in wanted:
        print(f"    {day}  {name}")
    if not wanted:
        print("    (none - every line is still commented out)")

# --- what the calendars hold already -----------------------------------------

title("2. what the calendars hold today")

Leaves = env['resource.calendar.leaves'].sudo()
holiday_type = None
if 'hr.work.entry.type' in env:
    holiday_type = env['hr.work.entry.type'].sudo().search(
        [('code', '=', CODE)], limit=1)
print(f"  work entry type {CODE}: {'found' if holiday_type else 'MISSING'}")

# A leave with a holiday_id came from somebody's own time off request; only the
# ones without are company closures. The field only exists once Time Off is
# installed, so it is added to the domain rather than assumed.
closure_domain = [('resource_id', '=', False)]
if 'holiday_id' in Leaves._fields:
    closure_domain.append(('holiday_id', '=', False))
existing = Leaves.search(closure_domain)
print(f"  {len(existing)} company closure(s) on the calendars")
for leave in existing[:20]:
    print(f"    {str(leave.date_from)[:10]} -> {str(leave.date_to)[:10]}  "
          f"{(leave.name or '')[:40]}")

timezone = pytz.timezone(TZ_NAME)
# Which days each company already has covered, so a re-run adds nothing twice.
taken = {}
for leave in existing:
    start = pytz.utc.localize(leave.date_from).astimezone(timezone).date()
    end = pytz.utc.localize(leave.date_to).astimezone(timezone).date()
    while start <= end:
        taken.setdefault(leave.company_id.id, set()).add(start)
        start = odoo_fields.Date.add(start, days=1)

Company = env['res.company'].sudo()
Version = env['hr.version'].sudo() if 'hr.version' in env else None
companies = Company.search([]).filtered(
    lambda c: Version is None or Version.search_count([('company_id', '=', c.id)]))
print(f"  companies to cover: "
      f"{', '.join(c.name[:28] for c in companies) or '(none)'}")

# --- what would be created ----------------------------------------------------

title("3. what this run would create")

to_create = []
for day, name in wanted:
    as_date = odoo_fields.Date.to_date(day)
    start = timezone.localize(
        odoo_fields.Datetime.to_datetime(f"{day} 00:00:00")
    ).astimezone(pytz.utc).replace(tzinfo=None)
    end = timezone.localize(
        odoo_fields.Datetime.to_datetime(f"{day} 23:59:59")
    ).astimezone(pytz.utc).replace(tzinfo=None)
    missing_for = [c for c in companies if as_date not in taken.get(c.id, ())]
    if not missing_for:
        print(f"  {day}  {name[:34]:<34} already on every company")
        continue
    vals = {
        'name': name,
        'date_from': start,
        'date_to': end,
        'resource_id': False,
        'calendar_id': False,
    }
    if holiday_type and 'work_entry_type_id' in Leaves._fields:
        vals['work_entry_type_id'] = holiday_type.id
    if 'time_type' in Leaves._fields:
        vals['time_type'] = 'leave'
    for company in missing_for:
        to_create.append((day, name, company, vals))
    print(f"  {day}  {name[:34]:<34} CREATE for "
          f"{', '.join(c.name[:18] for c in missing_for)}")

title("summary")

if problem:
    print("  the list could not be read, so nothing was compared")
elif not to_create:
    print("  every listed holiday is already on the calendars")
else:
    print(f"  {len(to_create)} holiday(s) to create")
    if not holiday_type:
        print(f"  !! work entry type {CODE} is missing - they would be created "
              f"without one,")
        print("     so Odoo's own reports would not know they are holidays")

if not APPLY:
    env.cr.rollback()
    print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write.")
elif not to_create:
    env.cr.rollback()
    print("\nnothing to do.")
else:
    for _day, _name, company, vals in to_create:
        # The company is computed from env.company at create time, and
        # with_company() does not reach the compute, so it is set afterwards -
        # assignment to a stored computed field does stick. It matters: the
        # multi-company rule is [('company_id', 'in', company_ids + [False])],
        # so a holiday stamped with one company is invisible to the other three.
        leave = Leaves.create(dict(vals))
        if leave.company_id != company:
            leave.company_id = company.id
    env.cr.commit()
    print(f"\nwritten: {len(to_create)} calendar leave(s) created.")
    print("Overtime already computed does not know about them - recompute the")
    print("periods that contain one with tools/regenerate_overtime.py.")
