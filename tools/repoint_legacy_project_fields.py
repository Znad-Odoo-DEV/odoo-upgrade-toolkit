"""Repoint every legacy field that names a project at project.project.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/repoint_legacy_project_fields.py

Phase B, step 2, and the last thing standing between the database and deleting
x_projects_list. Around a hundred Studio fields across ninety models still hold
a legacy project id - the daily attendance, the attendance per employee, the
BOQ and quantities, the subcontractors, the stores and transactions, the
requests, the purchase orders. Together they carry some 800,000 links.

Each field is turned in place: the id it stores is translated through the same
old -> new map the whole migration has used, and the field itself is told to
point at project.project from now on. The attributes those records read through
the project - the project number above all - were carried onto project.project
by tools/carry_project_attributes.py, which is why the related fields keep
working afterwards without a single edit.

Order matters and is enforced:

 1. every stored id must be in the map, or nothing runs at all
 2. the values are translated first, per field, in batches over the primary key
    so a table of half a million rows is never held in one lock
 3. only then is ir_model_fields.relation changed
 4. Odoo builds the new foreign keys on the next restart, by which time the
    values they check are already right

Progress is recorded per field, so an interrupted run resumes where it stopped
instead of starting over. Nothing is deleted; the legacy list keeps every row.

AFTER THIS RUNS: restart the instance (odoosh-restart) so the registry picks up
the new relation and lays the foreign keys down.
"""
import json
import os

# Prints the plan and rolls back unless SSC_WRITE=1 is in the environment.
DRY_RUN = os.environ.get('SSC_WRITE') != '1'

LEGACY_MODEL = 'x_projects_list'
TARGET_MODEL = 'project.project'
ID_MAP_KEY = 'ssc.project_migration.id_map'
DONE_KEY = 'ssc.project_migration.legacy_fields_done'

# Rows per statement. Big enough to be quick, small enough that no single lock
# is held for long on a table the whole company is using.
BATCH = 25000

cr = env.cr                                                      # noqa: F821
param = env['ir.config_parameter'].sudo()                        # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def table_of(model_name):
    """The table behind a model, whether or not it is in the registry."""
    model = env.get(model_name)                                  # noqa: F821
    if model is not None:
        return model._table
    return model_name.replace('.', '_')


def column_exists(table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return bool(cr.fetchone())


def drop_foreign_keys(table, column):
    cr.execute("""
        SELECT con.conname
          FROM pg_constraint con
          JOIN pg_class rel ON rel.oid = con.conrelid
          JOIN pg_attribute att ON att.attrelid = con.conrelid
                               AND att.attnum = ANY (con.conkey)
         WHERE con.contype = 'f' AND rel.relname = %s AND att.attname = %s
    """, (table, column))
    names = [row[0] for row in cr.fetchall()]
    for name in names:
        cr.execute('ALTER TABLE "%s" DROP CONSTRAINT "%s"' % (table, name))
    return names


# --- the map ----------------------------------------------------------------

id_map = {int(k): int(v) for k, v in
          json.loads(param.get_param(ID_MAP_KEY) or '{}').items()}
if not id_map:
    raise SystemExit(
        "%s is empty. Run tools/migrate_projects_to_native.py first." % ID_MAP_KEY)

done = set(json.loads(param.get_param(DONE_KEY) or '[]'))
old_ids = [k for k in id_map]
new_ids = [id_map[k] for k in old_ids]

title("0. what this run is working from")
print("  %s project(s) in the id map" % len(id_map))
print("  %s field(s) already done in an earlier run" % len(done))
print("  writing" if not DRY_RUN else "  DRY RUN - nothing will be written")


# --- 1. the fields ----------------------------------------------------------

fields = IrField.search([('relation', '=', LEGACY_MODEL), ('ttype', '=', 'many2one')])
plan, unreachable = [], []
for field in fields.sorted(lambda f: (f.model, f.name)):
    table = table_of(field.model)
    if not column_exists(table, field.name):
        unreachable.append((field.model, field.name, table))
        continue
    cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL'
               % (table, field.name))
    plan.append((field, table, cr.fetchone()[0]))

title("1. fields pointing at %s" % LEGACY_MODEL)
print("  %s field(s), %s with a column to work on"
      % (len(fields), len(plan)))
if unreachable:
    print("\n  ! no column in the database - nothing to translate, relation only:")
    for model, name, table in unreachable:
        print("    %-42s %-36s (%s)" % (model, name, table))


# --- 2. is every stored id known? -------------------------------------------

title("2. coverage")

unmapped = {}
for field, table, count in plan:
    if not count:
        continue
    cr.execute('SELECT DISTINCT "%s" FROM "%s" WHERE "%s" IS NOT NULL'
               % (field.name, table, field.name))
    strays = sorted({row[0] for row in cr.fetchall()} - set(id_map))
    if strays:
        unmapped['%s.%s' % (field.model, field.name)] = strays

if unmapped:
    print("  STOPPED. These fields hold project ids with no native counterpart:")
    for key, strays in unmapped.items():
        print("    %-52s %s" % (key, strays))
    raise SystemExit(
        "\nRe-run tools/migrate_projects_to_native.py - it matches by name and is "
        "safe to run twice - then run this again. Nothing was changed.")

total_rows = sum(c for _f, _t, c in plan)
print("  every stored id is in the map")
print("  %s row(s) to translate across %s field(s)" % (total_rows, len(plan)))
print("\n  the ten heaviest:")
for field, table, count in sorted(plan, key=lambda p: -p[2])[:10]:
    print("    %8s  %-42s %s" % (count, field.model, field.name))

if DRY_RUN:
    print("\n  DRY RUN - stopping here. Run again with SSC_WRITE=1 to write.")
    cr.rollback()
    raise SystemExit()


# --- 3. translate, then repoint --------------------------------------------

title("3. translating")

moved_total = 0
for field, table, count in plan:
    key = '%s.%s' % (field.model, field.name)
    if key in done:
        print("  = %-52s done earlier" % key)
        continue

    dropped = drop_foreign_keys(table, field.name)

    moved = 0
    if count:
        # Walked over the primary key rather than over the values: a row is then
        # visited exactly once, even where a new project id happens to be the
        # same number as some legacy one.
        cr.execute('SELECT MIN(id), MAX(id) FROM "%s"' % table)
        low, high = cr.fetchone()
        while low is not None and low <= high:
            cr.execute(
                'UPDATE "%s" AS t SET "%s" = m.new_id'
                '  FROM (SELECT * FROM unnest(%%s::int[], %%s::int[])'
                '        AS x(old_id, new_id)) AS m'
                ' WHERE t."%s" = m.old_id AND t.id >= %%s AND t.id < %%s'
                % (table, field.name, field.name),
                (old_ids, new_ids, low, low + BATCH),
            )
            moved += cr.rowcount
            low += BATCH
            cr.commit()

    cr.execute("""
        UPDATE ir_model_fields SET relation = %s
         WHERE model = %s AND name = %s
    """, (TARGET_MODEL, field.model, field.name))

    done.add(key)
    param.set_param(DONE_KEY, json.dumps(sorted(done)))
    cr.commit()

    moved_total += moved
    print("  > %-52s %7s row(s)%s"
          % (key, moved, "  [fk %s dropped]" % len(dropped) if dropped else ""))

# The relation-only fields still have to be turned, or they keep naming a model
# that is about to disappear.
for model, name, _table in unreachable:
    key = '%s.%s' % (model, name)
    if key in done:
        continue
    cr.execute("""
        UPDATE ir_model_fields SET relation = %s WHERE model = %s AND name = %s
    """, (TARGET_MODEL, model, name))
    done.add(key)
    param.set_param(DONE_KEY, json.dumps(sorted(done)))
    cr.commit()
    print("  > %-52s relation only" % key)

title("summary")
print("  %s row(s) translated" % moved_total)
print("  %s field(s) now point at %s" % (len(done), TARGET_MODEL))
cr.execute("SELECT COUNT(*) FROM ir_model_fields WHERE relation = %s", (LEGACY_MODEL,))
print("  %s field(s) still naming %s" % (cr.fetchone()[0], LEGACY_MODEL))
print("""
  NEXT: restart the instance so the registry picks the new relation up and lays
  the foreign keys down -

      odoosh-restart

  Then check a screen that reads a project through one of these fields before
  going anywhere near deleting %s.""" % LEGACY_MODEL)
