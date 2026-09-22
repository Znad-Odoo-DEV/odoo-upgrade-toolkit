"""Repoint every legacy field that names an employee at hr.employee.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/repoint_legacy_employee_fields.py

The third of these, and the same shape as the first two: the id each field
holds is translated through the map tools/migrate_employees_to_native.py wrote,
and the field itself is told to point at hr.employee. Nearly half a million
links across eighty-odd fields, plus the three many2many with a relation table
of their own.

Order, and it matters:

 1. every stored id must be in the map, or nothing runs
 2. values are translated first, in batches over the primary key, so no table is
    held in one lock and an interrupted run resumes where it stopped
 3. the field is repointed only afterwards, and the foreign key put back on the
    way out, so the database enforces the link again straight away

The fields belonging to a module - ssc.attendance.line.employee_id above all -
are left to the module's own migration script. Repointing a field from under
the code that declares it is how a registry ends up disagreeing with its own
database.
"""
import json
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

LEGACY_MODEL = 'x_employeeslist'
LEGACY_TABLE = 'x_employeeslist'
TARGET_MODEL = 'hr.employee'
TARGET_TABLE = 'hr_employee'
ID_MAP_KEY = 'ssc.employee_migration.id_map'
DONE_KEY = 'ssc.employee_migration.legacy_fields_done'
BATCH = 25000

cr = env.cr                                                      # noqa: F821
param = env['ir.config_parameter'].sudo()                        # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def table_of(model_name):
    model = env.get(model_name)                                  # noqa: F821
    return model._table if model is not None else model_name.replace('.', '_')


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


def table_exists(table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def foreign_keys(table, column):
    cr.execute("""
        SELECT con.conname, tgt.relname
          FROM pg_constraint con
          JOIN pg_class rel ON rel.oid = con.conrelid
          JOIN pg_class tgt ON tgt.oid = con.confrelid
          JOIN pg_attribute att ON att.attrelid = con.conrelid
                               AND att.attnum = ANY (con.conkey)
         WHERE con.contype = 'f' AND rel.relname = %s AND att.attname = %s
    """, (table, column))
    return cr.fetchall()


def translate(table, column, old_ids, new_ids):
    cr.execute('SELECT MIN(id), MAX(id) FROM "%s"' % table)
    low, high = cr.fetchone()
    moved = 0
    while low is not None and low <= high:
        cr.execute(
            'UPDATE "%s" AS t SET "%s" = m.new_id'
            '  FROM (SELECT * FROM unnest(%%s::int[], %%s::int[])'
            '        AS x(old_id, new_id)) AS m'
            ' WHERE t."%s" = m.old_id AND t.id >= %%s AND t.id < %%s'
            % (table, column, column),
            (old_ids, new_ids, low, low + BATCH))
        moved += cr.rowcount
        low += BATCH
        cr.commit()
    return moved


# --- the map ----------------------------------------------------------------

id_map = {int(k): int(v) for k, v in
          json.loads(param.get_param(ID_MAP_KEY) or '{}').items()}
if not id_map:
    raise SystemExit(
        "%s is empty. Run tools/migrate_employees_to_native.py first." % ID_MAP_KEY)
done = set(json.loads(param.get_param(DONE_KEY) or '[]'))
old_ids = list(id_map)
new_ids = [id_map[k] for k in old_ids]

title("0. what this run is working from")
print("  %s employee(s) in the map" % len(id_map))
print("  %s field(s) done in an earlier run" % len(done))
print("  writing" if not DRY_RUN else "  DRY RUN - nothing will be written")


# --- 1. the fields ----------------------------------------------------------

simple, many2many, relation_only, coded = [], [], [], []
for field in IrField.search([('relation', '=', LEGACY_MODEL)]).sorted(
        lambda f: (f.model, f.name)):
    if field.state == 'base':
        coded.append(field)
        continue
    if field.ttype == 'many2many':
        table = field.relation_table
        if not table or not table_exists(table):
            relation_only.append(field)
            continue
        ours = None
        for candidate in (field.column1, field.column2,
                          '%s_id' % LEGACY_TABLE, 'x_employeeslist_id'):
            if candidate and column_exists(table, candidate):
                for _name, target in foreign_keys(table, candidate):
                    if target == LEGACY_TABLE:
                        ours = candidate
                        break
            if ours:
                break
        if not ours:
            relation_only.append(field)
            continue
        cr.execute('SELECT COUNT(*) FROM "%s"' % table)
        many2many.append((field, table, ours, cr.fetchone()[0]))
        continue

    table = table_of(field.model)
    if not column_exists(table, field.name):
        relation_only.append(field)
        continue
    cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL' % (table, field.name))
    simple.append((field, table, cr.fetchone()[0]))

title("1. fields pointing at %s" % LEGACY_MODEL)
print("  %s many2one with a column" % len(simple))
print("  %s many2many with a table" % len(many2many))
print("  %s with nothing stored" % len(relation_only))
print("  %s belonging to a module, left to its migration script:" % len(coded))
for field in coded:
    print("      %s.%s" % (field.model, field.name))


# --- 2. coverage ------------------------------------------------------------

title("2. coverage")

unmapped = {}
for field, table, count in simple:
    if not count:
        continue
    cr.execute('SELECT DISTINCT "%s" FROM "%s" WHERE "%s" IS NOT NULL'
               % (field.name, table, field.name))
    strays = sorted({row[0] for row in cr.fetchall()} - set(id_map))
    if strays:
        unmapped['%s.%s' % (field.model, field.name)] = strays[:10]
for field, table, ours, count in many2many:
    cr.execute('SELECT DISTINCT "%s" FROM "%s"' % (ours, table))
    strays = sorted({row[0] for row in cr.fetchall()} - set(id_map))
    if strays:
        unmapped['%s (m2m)' % table] = strays[:10]

if unmapped:
    print("  STOPPED. These hold employee ids with no native counterpart:")
    for key, strays in unmapped.items():
        print("    %-52s %s" % (key, strays))
    raise SystemExit(
        "\nRe-run tools/migrate_employees_to_native.py first. Nothing was changed.")

total = sum(c for _f, _t, c in simple) + sum(c for _f, _t, _o, c in many2many)
print("  every stored id is in the map")
print("  %s row(s) to translate" % total)
for field, table, count in sorted(simple, key=lambda p: -p[2])[:10]:
    print("    %8s  %-42s %s" % (count, field.model, field.name))

if DRY_RUN:
    print("\n  DRY RUN - stopping here. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 3. translate and repoint ----------------------------------------------

title("3. translating")

moved_total = 0
for field, table, count in simple:
    key = '%s.%s' % (field.model, field.name)
    if key in done:
        print("  = %-52s done earlier" % key)
        continue
    for name, _target in foreign_keys(table, field.name):
        cr.execute('ALTER TABLE "%s" DROP CONSTRAINT "%s"' % (table, name))
    moved = translate(table, field.name, old_ids, new_ids) if count else 0
    cr.execute("UPDATE ir_model_fields SET relation = %s WHERE model = %s AND name = %s",
               (TARGET_MODEL, field.model, field.name))
    fk = ('%s_%s_fkey' % (table, field.name))[:63]
    cr.execute('ALTER TABLE "%s" ADD CONSTRAINT "%s" FOREIGN KEY ("%s") '
               'REFERENCES "%s"(id) ON DELETE SET NULL NOT VALID'
               % (table, fk, field.name, TARGET_TABLE))
    cr.execute('ALTER TABLE "%s" VALIDATE CONSTRAINT "%s"' % (table, fk))
    done.add(key)
    param.set_param(DONE_KEY, json.dumps(sorted(done)))
    cr.commit()
    moved_total += moved
    print("  > %-52s %7s row(s)" % (key, moved))

for field, table, ours, count in many2many:
    key = '%s.%s' % (field.model, field.name)
    if key in done:
        print("  = %-52s done earlier" % key)
        continue
    for name, _target in foreign_keys(table, ours):
        cr.execute('ALTER TABLE "%s" DROP CONSTRAINT "%s"' % (table, name))
    cr.execute(
        'UPDATE "%s" AS t SET "%s" = m.new_id'
        '  FROM (SELECT * FROM unnest(%%s::int[], %%s::int[])'
        '        AS x(old_id, new_id)) AS m WHERE t."%s" = m.old_id'
        % (table, ours, ours), (old_ids, new_ids))
    moved = cr.rowcount
    other = field.column1 if field.column1 != ours else field.column2
    cr.execute("""
        UPDATE ir_model_fields
           SET relation = %s, relation_table = %s, column1 = %s, column2 = %s
         WHERE model = %s AND name = %s
    """, (TARGET_MODEL, table, other or field.column1, ours, field.model, field.name))
    fk = ('%s_%s_fkey' % (table, ours))[:63]
    cr.execute('ALTER TABLE "%s" ADD CONSTRAINT "%s" FOREIGN KEY ("%s") '
               'REFERENCES "%s"(id) ON DELETE CASCADE NOT VALID'
               % (table, fk, ours, TARGET_TABLE))
    cr.execute('ALTER TABLE "%s" VALIDATE CONSTRAINT "%s"' % (table, fk))
    done.add(key)
    param.set_param(DONE_KEY, json.dumps(sorted(done)))
    cr.commit()
    moved_total += moved
    print("  > %-52s %7s link(s)  [m2m]" % (key, moved))

for field in relation_only:
    key = '%s.%s' % (field.model, field.name)
    if key in done:
        continue
    cr.execute("UPDATE ir_model_fields SET relation = %s WHERE model = %s AND name = %s",
               (TARGET_MODEL, field.model, field.name))
    done.add(key)
    param.set_param(DONE_KEY, json.dumps(sorted(done)))
    cr.commit()
    print("  > %-52s relation only" % key)

title("summary")
print("  %s row(s) translated" % moved_total)
cr.execute("SELECT COUNT(*) FROM ir_model_fields WHERE relation = %s", (LEGACY_MODEL,))
print("  %s field(s) still naming %s" % (cr.fetchone()[0], LEGACY_MODEL))
print("""
  NEXT: odoosh-restart http, then tools/fix_employee_code_references.py for the
  automations that read an employee the old way.""")
