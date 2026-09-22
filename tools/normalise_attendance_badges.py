"""Store badges in the one shape everything else compares against.

    # report only, writes nothing:
    odoo-bin shell -d <database> --no-http < tools/normalise_attendance_badges.py

    # same again, this time writing:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/normalise_attendance_badges.py

hr.employee.barcode only accepts alphanumerics, so a badge typed 'RA-03' is
written there as 'RA03'. The masters kept the typed form, and everything that
looks an employee up by badge compared the two literally and found nothing -
which is why ssc.employee.hr_employee_id was set on 3 records out of 466.

This strips the punctuation at the source, on both masters:

    ssc.employee.attendance_code
    x_employeeslist.x_studio_attendance_id

Same rule hooks._clean_barcode already applies on the way into barcode: keep
letters and digits, cut at eighteen characters. Case is left alone - barcode
does not change it either.

Two badges that collapse onto the same value are NOT written. Merging two
people onto one badge is worse than leaving the dash in, so they are reported
and skipped for a human to settle.
"""
import os
import re

APPLY = os.environ.get('SSC_APPLY') == '1'

TARGETS = [
    ('ssc.employee', 'attendance_code', 'name'),
    ('x_employeeslist', 'x_studio_attendance_id', 'x_name'),
]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text):
    print("\n" + "=" * 74)
    print(text)
    print("=" * 74)


def normalise(code):
    """The shape hr.employee.barcode stores: alphanumerics, eighteen max."""
    return re.sub(r'[^A-Za-z0-9]', '', (code or '').strip())[:18]


total_changed = 0
total_blocked = 0

for model_name, field, label_field in TARGETS:
    title(f"{model_name}.{field}")

    if model_name not in env:
        print(f"  model {model_name} is not on this database - skipped")
        continue
    Model = env[model_name].sudo()
    if field not in Model._fields:
        print(f"  {model_name} has no field {field} - skipped")
        continue

    records = Model.search([])
    print(f"  {len(records)} record(s)")

    # What each badge would become, and who already holds that value.
    holders = {}
    for record in records:
        current = record[field]
        if current:
            holders.setdefault(normalise(current), []).append(record)

    changes = []
    blocked = []
    for record in records:
        current = record[field] or ''
        wanted = normalise(current)
        if not wanted or wanted == current:
            continue
        # Someone else already carries the normalised form, or two dashed
        # badges collapse onto each other: writing either would merge two
        # people onto one badge.
        clash = [r for r in holders.get(wanted, []) if r.id != record.id]
        if clash:
            blocked.append((record, current, wanted, clash))
        else:
            changes.append((record, current, wanted))

    for record, current, wanted in changes:
        print(f"  > {(record[label_field] or '?')[:40]:<40} {current!r:>14} -> {wanted!r}")

    for record, current, wanted, clash in blocked:
        others = ", ".join((r[label_field] or '?')[:24] for r in clash[:3])
        print(f"  ! {(record[label_field] or '?')[:40]:<40} {current!r:>14} -> {wanted!r} "
              f"CLASHES with {others}")

    print(f"\n  to change {len(changes)}   blocked by a clash {len(blocked)}")
    total_changed += len(changes)
    total_blocked += len(blocked)

    if APPLY and changes:
        for record, _current, wanted in changes:
            record[field] = wanted


title("summary")
print(f"  badges to normalise  {total_changed}")
print(f"  blocked by a clash   {total_blocked}")

if total_blocked:
    print("\n  The blocked ones are left as they are: two records would end up "
          "sharing a badge.\n  Settle those by hand, then run this again.")

if not APPLY:
    env.cr.rollback()
    print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write.")
else:
    env.cr.commit()
    print(f"\nwritten: {total_changed} badge(s) normalised.")
    print("Run the employee sync afterwards so the hr.employee links catch up:")
    print("  env['ssc.employee'].search([])._sync_to_hr(); env.cr.commit()")
