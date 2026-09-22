"""Tie the legacy employee list to hr.employee and move what has a home there.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/migrate_employees_to_native.py

Step 0 of moving off x_employeeslist. Most of the answer is already in the
database: ssc.employee mirrors the legacy row (studio_ref_id) and points at the
native employee (hr_employee_id), so the great majority know who they are
already. The rest are matched on the name, and the few with nobody to match are
given an archived hr.employee of their own - not because anyone will look at
them, but because a link with nowhere to land stops the whole migration.

Then the attributes, and only the ones hr.employee already has a place for.
Nothing is added to hr.employee: that is the instruction, and it is the reason
the rest of the legacy attributes - the allowances, the gratuity, the document
expiry dates - do not come across. Everything reading them through the employee
is removed by tools/drop_orphan_employee_readers.py, deliberately and with the
list printed first.

The nationality is the one that cannot be copied straight: a name in text on
one side, a country on the other. It is matched against res.country by name and
by code, and whatever does not match is reported rather than guessed at.
"""
import json
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

LEGACY_MODEL = 'x_employeeslist'
TARGET_MODEL = 'hr.employee'
ID_MAP_KEY = 'ssc.employee_migration.id_map'

# legacy field -> the native field that already means the same thing
MOVE = {
    'x_studio_attendance_id': 'barcode',
    'x_studio_employee_id': 'registration_number',
    'x_studio_passport': 'passport_id',
    'x_studio_profession': 'job_title',
    'x_studio_residence_visa_no': 'visa_no',
    'x_studio_user': 'user_id',
    'x_studio_nationality': 'country_id',      # text -> res.country, resolved below
    'x_studio_eidres_visa_expiry_date': 'visa_expire',
    'x_studio_date_field_6lg_1ib47o7c3': 'work_permit_expiration_date',
}

cr = env.cr                                                      # noqa: F821
param = env['ir.config_parameter'].sudo()                        # noqa: F821

Legacy = env[LEGACY_MODEL].sudo().with_context(active_test=False)   # noqa: F821
Hr = env[TARGET_MODEL].sudo().with_context(active_test=False)       # noqa: F821
Ssc = env['ssc.employee'].sudo().with_context(active_test=False)    # noqa: F821
Country = env['res.country'].sudo()                                 # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def norm(value):
    return ' '.join((value or '').split()).lower()


# --- 1. the map -------------------------------------------------------------

title("1. matching the legacy rows to hr.employee")

bridge = {e.studio_ref_id: e.hr_employee_id.id
          for e in Ssc.search([('studio_ref_id', '!=', False)]) if e.hr_employee_id}

# The name twice, and which of the two is the person. Eight legacy employees
# have two hr.employee rows: one created on 2026-08-12 from the Studio list,
# carrying the registration number and nothing else - no badge, no punch,
# archived since - and one that predates it, carrying the badge and every
# punch and no code. tools/archive_duplicate_employees.py named the first
# kind ghosts and the second keepers. A name match has to refuse a name that
# appears twice, and refusing them was about to give each a THIRD record; the
# registration number would have chosen the ghost, because the ghost is where
# the import wrote it. So the rule is the one that tool used: the record that
# carries work. Active, or a badge, or attendance. Exactly one such, or refuse.
Attendance = env['hr.attendance'].sudo()                                 # noqa: F821
punched = set(r['employee_id'][0] for r in
              Attendance.with_context(active_test=False).read_group(
                  [], ['employee_id'], ['employee_id']) if r['employee_id'])


def carries_work(employee):
    return bool(employee.active or employee.barcode or employee.id in punched)


# The ghosts by id, and the record each one is a copy of - the table
# tools/archive_duplicate_employees.py was written from. Two of them are not
# caught by the rule above: Ahsan Naveed and Avtar Kishan have their keeper
# under a slightly different spelling, so the ghost is the only record of
# that exact name, the name match is unique, and unique picks the ghost.
GHOSTS = {
    2100: 2053,   # Usama Zulfiqar Zulfiqar Ali
    2101: 2055,   # Muhammad Amin Ghulam Hussain
    2102: 2054,   # Ahsan Naveed Akhtar Ali
    2103: 2056,   # Harjinder Singh Joginder Pal
    2104: 2065,   # Dharamvir Som Nath
    2105: 2057,   # Muhammad Khalid Muhammad Anwar
    2106: 2058,   # Vishal Balram Singh
    2107: 2069,   # Mohd Amir Siddiqui Shahid Siddiqui
    2108: 2052,   # Jeeta Makbul
    2109: 2067,   # Avtar Kishan Sagli Ram
}
unghosted = []


def real(hr_id, row):
    """The keeper when the match landed on a ghost; the match itself otherwise."""
    if hr_id in GHOSTS and GHOSTS[hr_id]:
        unghosted.append((row, hr_id, GHOSTS[hr_id]))
        return GHOSTS[hr_id]
    return hr_id


by_name, name_dupes = {}, set()
candidates = {}
for employee in Hr.search([]):
    key = norm(employee.name)
    if not key:
        continue
    if key in by_name:
        name_dupes.add(key)
    by_name[key] = employee.id
    candidates.setdefault(key, []).append(employee)

rows = Legacy.search([], order='id')
id_map, from_bridge, from_name, from_keeper, to_create = {}, 0, 0, 0, []
resolved_by_keeper, empty = [], []
for r in rows:
    if not (norm(r.x_name) or r.x_studio_employee_id or r.x_studio_attendance_id):
        # A row with no name, no code and no badge - production has one, id
        # 2743, made on 2026-07-29 and never filled in. There is nothing to
        # make an employee from, and an "Employee 2743" on hr.employee would
        # be a second empty row. It stays out of the map: anything pointing at
        # it is cleared and recorded by the repoint, and it goes with the list.
        empty.append(r)
        continue
    if r.id in bridge:
        id_map[r.id] = bridge[r.id]
        from_bridge += 1
        continue
    key = norm(r.x_name)
    if key and key in by_name and key not in name_dupes:
        id_map[r.id] = real(by_name[key], r)
        from_name += 1
        continue
    if key in name_dupes:
        keepers = [e for e in candidates[key] if carries_work(e)]
        if len(keepers) == 1:
            id_map[r.id] = real(keepers[0].id, r)
            from_keeper += 1
            resolved_by_keeper.append((r, keepers[0],
                                       [e for e in candidates[key] if e.id != keepers[0].id]))
            continue
    to_create.append(r)

print("  %s legacy row(s)" % len(rows))
if empty:
    print("  empty - no name, code or badge - skipped : %s  (ids %s)"
          % (len(empty), [r.id for r in empty]))
print("  through ssc.employee : %s" % from_bridge)
print("  on the name          : %s" % from_name)
print("  name twice, one carries work : %s" % from_keeper)
print("  to be created        : %s" % len(to_create))
if unghosted:
    print()
    print("  landed on a ghost of the 2026-08-12 import, redirected to the record it copies:")
    for r, ghost_id, keeper_id in unghosted:
        keeper = Hr.browse(keeper_id)
        print("      %-38s %-9s ghost hr %-5s -> keeper hr %-5s %s badge=%s"
              % ((r.x_name or '')[:38], r.x_studio_employee_id or '-', ghost_id, keeper.id,
                 'active  ' if keeper.active else 'archived', keeper.barcode or '-'))
if resolved_by_keeper:
    print()
    print("  the name appears twice in hr.employee; the record that carries work is")
    print("  the person, the other is the ghost the import made and is left alone:")
    for r, keeper, ghosts in resolved_by_keeper:
        print("      %-38s %-9s -> hr %-5s %s badge=%-6s punches=%-5s | ghost: %s"
              % ((r.x_name or '')[:38], r.x_studio_employee_id or '-', keeper.id,
                 'active  ' if keeper.active else 'archived', keeper.barcode or '-',
                 Attendance.search_count([('employee_id', '=', keeper.id)]),
                 ", ".join("hr %s %s code=%s" % (g.id, 'active' if g.active else 'archived',
                                                 g.registration_number or '-') for g in ghosts)))
for r in to_create[:8]:
    print("      %-44s %s" % ((r.x_name or '')[:44],
                              'active' if r.x_active else 'archived'))
if len(to_create) > 8:
    print("      ... and %s more" % (len(to_create) - 8))


# --- 2. the countries -------------------------------------------------------

title("2. nationality -> res.country")

countries = {}
for country in Country.with_context(active_test=False).search([]):
    countries[norm(country.name)] = country.id
    if country.code:
        countries[country.code.lower()] = country.id
# Spellings the list actually holds, straightened rather than dropped: a
# misspelt country is still a known country, and 19 employees would otherwise
# arrive with none at all.
ALIASES = {'uae': 'united arab emirates', 'ksa': 'saudi arabia',
           'uk': 'united kingdom', 'usa': 'united states',
           'siraluon': 'sierra leone', 'sierraluon': 'sierra leone',
           'egyptian': 'egypt', 'egyption': 'egypt',
           'nipal': 'nepal', 'emarati': 'united arab emirates',
           'emirati': 'united arab emirates', 'filipino': 'philippines',
           'indian': 'india', 'pakistani': 'pakistan', 'nepali': 'nepal',
           'bangladeshi': 'bangladesh', 'srilankan': 'sri lanka',
           'sudanese': 'sudan', 'syrian': 'syria', 'jordanian': 'jordan'}

resolved, unresolved = {}, {}
for r in rows:
    text = norm(r.x_studio_nationality)
    if not text:
        continue
    key = ALIASES.get(text, text)
    country_id = countries.get(key) or countries.get(key.rstrip('n')) or \
        countries.get(key + 'n')
    if country_id:
        resolved[r.id] = country_id
    else:
        unresolved.setdefault(r.x_studio_nationality, 0)
        unresolved[r.x_studio_nationality] += 1

print("  %s employee(s) resolved to a country" % len(resolved))
if unresolved:
    print("  %s value(s) no country answers to - left empty:" % len(unresolved))
    for text, count in sorted(unresolved.items(), key=lambda kv: -kv[1])[:12]:
        print("      %-32s %s employee(s)" % (text, count))


# --- 3. what moves ----------------------------------------------------------

title("3. attributes moving into a native field")

cr.execute("""SELECT column_name FROM information_schema.columns
               WHERE table_name = 'x_employeeslist'""")
stored = {row[0] for row in cr.fetchall()}
for old, new in sorted(MOVE.items()):
    filled = 0
    if old in stored:
        cr.execute('SELECT COUNT(*) FROM x_employeeslist WHERE "%s" IS NOT NULL' % old)
        filled = cr.fetchone()[0]
    print("  %-38s -> %-20s %s row(s)" % (old, new, filled))

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 4. the ones nobody had -------------------------------------------------

title("4. creating the missing employees")

created = 0
for r in to_create:
    name = (r.x_name or '').strip() or 'Employee %s' % r.id
    # A run that died after this step already made this record; find it
    # rather than make it again.
    employee = Hr.search([('name', '=', name)], limit=1)
    if not employee:
        employee = Hr.create({'name': name, 'active': bool(r.x_active)})
        created += 1
    id_map[r.id] = employee.id
print("  %s created, %s found from an earlier run" % (created, len(to_create) - created))
cr.commit()


# --- 5. move the values -----------------------------------------------------

title("5. values")

written, kept = 0, 0
freed, clashed = [], []
for r in rows:
    employee = Hr.browse(id_map.get(r.id)).exists()
    if not employee:
        continue
    vals = {}
    for old, new in MOVE.items():
        if new not in Hr._fields:
            continue
        if employee[new]:
            kept += 1          # never overwrite what the native record already says
            continue
        if old == 'x_studio_nationality':
            country_id = resolved.get(r.id)
            if country_id:
                vals[new] = country_id
            continue
        value = r[old]
        if not value:
            continue
        vals[new] = value.id if hasattr(value, 'id') else value
    if 'registration_number' in vals:
        # hr_employee_unique_registration_number: one code per company. The
        # ghost of the 2026-08-12 import holds this employee's code, so the
        # code moves off the ghost first - it is archived and carries nothing
        # else. A holder that is not a known ghost is somebody's record, and
        # the code is not written over it.
        holder = Hr.search([('registration_number', '=', vals['registration_number']),
                            ('company_id', '=', employee.company_id.id),
                            ('id', '!=', employee.id)], limit=1)
        if holder and holder.id in GHOSTS:
            holder.write({'registration_number': False})
            freed.append((employee, holder))
        elif holder:
            clashed.append((employee, holder, vals.pop('registration_number')))
    if vals:
        employee.write(vals)
        written += 1
print("  %s employee(s) written" % written)
if freed:
    print("  %s code(s) moved off a ghost onto the person:" % len(freed))
    for employee, ghost in freed:
        print("      %-40s hr %-5s <- ghost hr %s" % (employee.name[:40], employee.id, ghost.id))
if clashed:
    print("  %s code(s) NOT written - another live record holds them:" % len(clashed))
    for employee, holder, code in clashed:
        print("      %-40s hr %-5s code %-10s held by hr %s %s"
              % (employee.name[:40], employee.id, code, holder.id, holder.name[:30]))
print("  %s value(s) left alone, the native record already had one" % kept)

param.set_param(ID_MAP_KEY, json.dumps({str(k): v for k, v in sorted(id_map.items())}))
cr.commit()

title("summary")
print("  %s pair(s) in %s" % (len(id_map), ID_MAP_KEY))
print("  %s field(s) moved into a native home" % len(MOVE))
print("""
  NEXT, in order:
    tools/repoint_legacy_employee_fields.py   the links themselves
    tools/fix_employee_related_paths.py       the readers that have a home now
    tools/drop_orphan_employee_readers.py     the ones that still have none

  The readers used to come first, because there was nowhere for them to read
  from once the allowances stopped being on the employee. There is now:
  hr.employee names ssc.employee, and a path can take one more step to reach
  the salary. So the links move, then every reader that can be repointed is,
  and only what is left over is removed - which is a dozen fields rather than
  the sixty-five it would have been.""")
