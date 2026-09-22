"""Everything left over from the permit and contract clean-up, in one report.

    odoo-bin shell -d <database> --no-http < tools/hr_action_list.py

Read only. Nothing is written, ever.

Six lists, each one a decision somebody has to make rather than something a
script can settle:

  1  contracts that have genuinely run out while the person keeps working
  2  people on the ministry list that Odoo has never heard of
  3  one person holding two live employee records
  4  one passport number sitting on two different people
  5  passport numbers that are placeholders or malformed
  6  employees with no badge, who therefore have no attendance at all

The ministry rows in section 2 are the ones that matched neither a passport nor
a name, taken from the list for establishment 823412 printed 23/08/2026.
"""
import re
from collections import defaultdict
from datetime import date, timedelta

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
today = date.today()

Employee = env['hr.employee'].sudo()
Attendance = env['hr.attendance'].sudo()
active = Employee.with_context(active_test=True).search([])
everyone = Employee.search([])


def title(number, text):
    print("\n" + "=" * 92)
    print(f"{number}. {text}")
    print("=" * 92)


def since(days):
    return today - timedelta(days=days)


def punches(emp, days=60):
    return Attendance.search_count([('employee_id', '=', emp.id),
                                    ('check_in', '>=', since(days))])


# ---------------------------------------------------------------------------
title(1, "CONTRACTS THAT HAVE RUN OUT - the person is still punching")

expired = []
for emp in active:
    version = emp.current_version_id
    if version and version.contract_date_end and version.contract_date_end < today:
        expired.append((version.contract_date_end, emp, version))

print(f"  {len(expired)} employee(s)\n")
print(f"  {'employee':<34} {'co':<3} {'badge':<9} {'job':<24} {'ended':<12} {'days':>5} {'punch60':>8}")
for end, emp, version in sorted(expired):
    print(f"  {emp.name[:34]:<34} {emp.company_id.id:<3} {(emp.barcode or '-'):<9} "
          f"{(emp.job_title or '-')[:24]:<24} {str(end):<12} "
          f"{(today - end).days:>5} {punches(emp):>8}")

# ---------------------------------------------------------------------------
title(2, "ON THE MINISTRY LIST, NOT IN ODOO - matched by neither passport nor name")

MISSING = [
    ("MD FAYSOL MIA SOMUJ ALI",                    "10/02/2027", "Bricklayer Assistant"),
    ("MOUSTAFA ABDELAZIM ELIMAM ELIMAM ABDELAATI", "07/11/2027", "Building Labourer"),
    ("BALASUBRAMANIAN GANESAN GANESAN",            "18/06/2027", "Carpenter"),
    ("RAFIQ AHAMED KALLASI KAJA MOHIDEEN",         "24/12/2027", "Accountant"),
    ("MONIR AHAMMED SALE AHAMMED",                 "17/12/2026", "Bricklayer"),
    ("MOHAMAD KHALDOUN ABDULKADER SHARABATI",      "10/07/2028", "Building Labourer"),
    ("JENIVIE ERONG AGUILAR",                      "10/04/2027", "Messenger"),
    ("KHALED BADEA AYYASH",                        "24/12/2027", "Operations Manager"),
    ("MOHANNAD M GHAZI KAYYALI REFAEI",            "23/08/2026", "Steel Fixer"),
]
print(f"  {len(MISSING)} name(s)\n")
print(f"  {'ministry name':<46} {'permit expiry':<14} {'job'}")
for name, expiry, job in MISSING:
    print(f"  {name[:46]:<46} {expiry:<14} {job}")
print("\n  Either they left and Odoo was never told, or they are held under a")
print("  spelling nothing here matches. Both need a person to look.")

# ---------------------------------------------------------------------------
title(3, "ONE PERSON, TWO LIVE RECORDS - archive the empty one")


def normalise(name):
    return re.sub(r'[^A-Z0-9]', '', (name or '').upper())


groups = defaultdict(list)
for emp in everyone:
    groups[normalise(emp.name)].append(emp)

live_pairs = []
archived_pairs = []
for key, records in groups.items():
    if len(records) < 2:
        continue
    if all(r.active for r in records):
        live_pairs.append(records)
    else:
        archived_pairs.append(records)

print(f"  {len(live_pairs)} name(s) with every record still active"
      f"   |   {len(archived_pairs)} with the older one already archived\n")
for records in sorted(live_pairs, key=lambda r: r[0].name):
    print(f"  {records[0].name}")
    for emp in sorted(records, key=lambda e: (bool(e.barcode), punches(e)), reverse=True):
        version = emp.current_version_id
        keep = "KEEP  " if emp.barcode or punches(emp) else "ARCHIVE"
        print(f"      {keep} id={emp.id:<6} co={emp.company_id.id} "
              f"badge={(emp.barcode or '-'):<9} punch60={punches(emp):<4} "
              f"wage={getattr(version, 'wage', 0) or 0:<8.0f} "
              f"passport={(emp.passport_id or '-')}")

# ---------------------------------------------------------------------------
title(4, "ONE PASSPORT, TWO DIFFERENT PEOPLE")

by_passport = defaultdict(list)
for emp in everyone:
    if emp.passport_id:
        by_passport[emp.passport_id.strip().upper()].append(emp)

collisions = []
for number, records in by_passport.items():
    if len(records) < 2:
        continue
    if len({normalise(r.name) for r in records}) > 1:
        collisions.append((number, records))

print(f"  {len(collisions)} passport(s) held by people with different names\n")
for number, records in sorted(collisions):
    print(f"  {number}")
    for emp in records:
        print(f"      id={emp.id:<6} co={emp.company_id.id} "
              f"badge={(emp.barcode or '-'):<9} {emp.name}")

# ---------------------------------------------------------------------------
title(5, "PASSPORT NUMBERS THAT CANNOT BE RIGHT")


def suspicious(number):
    value = (number or '').strip().upper()
    if not value:
        return None
    if set(value[1:]) <= {'0'}:
        return "all zeros"
    if value in ('XXX', 'X', 'NA', 'N/A', 'NONE', '-'):
        return "placeholder text"
    if len(value) < 7:
        return f"only {len(value)} characters"
    if len(value) > 12:
        return f"{len(value)} characters, far too long"
    if value.isdigit():
        return "digits only, no letter prefix"
    return None


bad_passports = []
for emp in active:
    reason = suspicious(emp.passport_id)
    if reason:
        bad_passports.append((reason, emp))

print(f"  {len(bad_passports)} employee(s)\n")
print(f"  {'employee':<34} {'co':<3} {'badge':<9} {'passport':<20} {'why'}")
for reason, emp in sorted(bad_passports, key=lambda x: (x[0], x[1].name)):
    print(f"  {emp.name[:34]:<34} {emp.company_id.id:<3} {(emp.barcode or '-'):<9} "
          f"{(emp.passport_id or '-')[:20]:<20} {reason}")

# ---------------------------------------------------------------------------
title(6, "NO BADGE - these people cannot be recorded by the clock at all")

nobadge = active.filtered(lambda e: not e.barcode)
print(f"  {len(nobadge)} employee(s)\n")
by_company = defaultdict(list)
for emp in nobadge:
    by_company[emp.company_id.name].append(emp)
for company, records in sorted(by_company.items()):
    print(f"  {company}  ({len(records)})")
    for emp in sorted(records, key=lambda e: e.name):
        print(f"      {emp.name[:38]:<38} {(emp.job_title or '-')[:30]:<30} "
              f"punch60={punches(emp)}")

print("\n" + "=" * 92)
print("nothing was written")
print("=" * 92)
