"""Archive the eleven duplicate employee records created on 2026-08-12.

    odoo-bin shell -d <database> --no-http < tools/archive_duplicate_employees.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/archive_duplicate_employees.py

Eleven employee records, ids 2100 to 2110, were all created on the same day
with no badge and no attendance against any of them. Every one is a second copy
of somebody already in the system, and each has exactly one counterpart that
carries the badge and the punches. One of the eleven, 2110, has no name at all
and was archived already.

They are archived rather than deleted. Archiving is reversible, keeps whatever
is pointed at them, and is enough: an archived employee is out of every list,
every payslip run and every attendance report.

Two passport numbers move first. The copies disagree with each other by a single
digit, in both directions, so neither side can be trusted on its own; the
ministry list for establishment 823412 decides, and it says the surviving record
is wrong in exactly two cases. Correcting them before the copy disappears is the
only chance to do it from a source rather than a guess.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'

# ghost id -> the record that keeps the badge and the punches
PAIRS = {
    2100: 2053,   # Usama Zulfiqar Zulfiqar Ali        RW11
    2101: 2055,   # Muhammad Amin Ghulam Hussain       RW14
    2102: 2054,   # Ahsan Naveed Akhtar Ali            RW12
    2103: 2056,   # Harjinder Singh Joginder Pal       RW15
    2104: 2065,   # Dharamvir Som Nath                 RW24
    2105: 2057,   # Muhammad Khalid Muhammad Anwar     RW16
    2106: 2058,   # Vishal Balram Singh                RW17
    2107: 2069,   # Mohd Amir Siddiqui Shahid Siddiqui RW28
    2108: 2052,   # Jeeta Makbul                       RW10   (ghost sat in company 3)
    2109: 2067,   # Avtar Kishan Sagli Ram             RW25
    2110: None,   # Unnamed - no counterpart, already archived
}

# surviving record -> the passport the ministry prints for that person
PASSPORT_FIX = {
    2054: 'BE9671673',   # held BE9671672
    2057: 'JW4124952',   # held JW4124951
}

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
Employee = env['hr.employee'].sudo()
Attendance = env['hr.attendance'].sudo()


def title(text):
    print("\n" + "=" * 88)
    print(text)
    print("=" * 88)


title("1. passport corrections on the surviving records")
passport_writes = []
for keeper_id, correct in PASSPORT_FIX.items():
    keeper = Employee.browse(keeper_id).exists()
    if not keeper:
        print(f"  id={keeper_id} no longer exists - skipped")
        continue
    if keeper.passport_id == correct:
        print(f"  {keeper.name[:34]:<34} already {correct}")
        continue
    print(f"  {keeper.name[:34]:<34} {keeper.passport_id} -> {correct}")
    passport_writes.append((keeper, correct))

title("2. records to archive")
to_archive = []
blocked = []
for ghost_id, keeper_id in PAIRS.items():
    ghost = Employee.browse(ghost_id).exists()
    if not ghost:
        print(f"  id={ghost_id} no longer exists - skipped")
        continue
    punches = Attendance.search_count([('employee_id', '=', ghost_id)])
    keeper = Employee.browse(keeper_id).exists() if keeper_id else None

    # Never archive something that carries work. The whole argument for calling
    # these copies is that nothing was ever recorded against them.
    if punches or ghost.barcode:
        blocked.append((ghost, punches))
        continue
    if not ghost.active:
        print(f"  {ghost.name[:32]:<32} id={ghost_id:<6} already archived")
        continue
    to_archive.append(ghost)
    keeper_label = (f"{keeper.name[:26]} (badge {keeper.barcode})"
                    if keeper else "no counterpart")
    print(f"  {ghost.name[:32]:<32} id={ghost_id:<6} co={ghost.company_id.id}  "
          f"keeps -> {keeper_label}")

if blocked:
    title("REFUSED - these carry a badge or attendance and are not copies")
    for ghost, punches in blocked:
        print(f"  {ghost.name[:34]:<34} id={ghost.id} badge={ghost.barcode or '-'} "
              f"attendance={punches}")

print(f"\n  {len(passport_writes)} passport(s) to correct, {len(to_archive)} record(s) to archive")

if APPLY:
    for keeper, correct in passport_writes:
        keeper.passport_id = correct
    for ghost in to_archive:
        ghost.active = False
    env.cr.commit()
    title("APPLIED")
    print(f"  {len(passport_writes)} passport(s) corrected")
    print(f"  {len(to_archive)} record(s) archived")
    print("\n  Re-run tools/set_work_permit_dates.py afterwards: two of the ministry")
    print("  rows were matching the copy, and now they will find the real employee.")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to write.")
