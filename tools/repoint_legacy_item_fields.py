"""Repoint every legacy field that names an item at product.template.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/repoint_legacy_item_fields.py

The item half of the same job the projects went through, with two differences:
there are many2many fields this time, each with a relation table of its own, and
two fields on product.product that point back at the legacy list and hold
nothing - a bridge somebody started and never used. Those are dropped.

Order, and it matters:

 1. every stored id must be in the map that tools/migrate_items_to_native.py
    wrote, or nothing runs
 2. values are translated first, in batches over the primary key, so no table is
    held in one lock
 3. the field is told where to point only afterwards, and for a many2many the
    table and its two columns are pinned down explicitly, because Odoo works
    them out from the model names otherwise and would look for a table that
    does not exist
 4. the foreign key is put back on the way out, so the database enforces the
    link again rather than waiting for a restart that may never create it

Progress is recorded per field: an interrupted run resumes where it stopped.
"""
import json
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

LEGACY_MODEL = 'x_all_items_list'
LEGACY_TABLE = 'x_all_items_list'
TARGET_MODEL = 'product.template'
TARGET_TABLE = 'product_template'
ID_MAP_KEY = 'ssc.item_migration.id_map'
DONE_KEY = 'ssc.item_migration.legacy_fields_done'
BATCH = 25000

# Empty bridges on product.product, left from an attempt that never went
# anywhere. They mean nothing once the product is the item.
DROP_FIELDS = [
    ('product.product', 'x_studio_item'),
    ('product.product', 'x_studio_many2one_field_4rh_1j337rpgm'),
]

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


def translate(table, column, old_ids, new_ids, pk='id'):
    """Walk the table by its primary key, translating as we go."""
    cr.execute('SELECT MIN("%s"), MAX("%s") FROM "%s"' % (pk, pk, table))
    low, high = cr.fetchone()
    moved = 0
    while low is not None and low <= high:
        cr.execute(
            'UPDATE "%s" AS t SET "%s" = m.new_id'
            '  FROM (SELECT * FROM unnest(%%s::int[], %%s::int[])'
            '        AS x(old_id, new_id)) AS m'
            ' WHERE t."%s" = m.old_id AND t."%s" >= %%s AND t."%s" < %%s'
            % (table, column, column, pk, pk),
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
        "%s is empty. Run tools/migrate_items_to_native.py first." % ID_MAP_KEY)
done = set(json.loads(param.get_param(DONE_KEY) or '[]'))
old_ids = list(id_map)
new_ids = [id_map[k] for k in old_ids]

title("0. what this run is working from")
print("  %s item(s) in the map" % len(id_map))
print("  %s field(s) done in an earlier run" % len(done))
print("  writing" if not DRY_RUN else "  DRY RUN - nothing will be written")


# --- 1. the fields ----------------------------------------------------------

fields = IrField.search([('relation', '=', LEGACY_MODEL)])
simple, many2many, relation_only = [], [], []
for field in fields.sorted(lambda f: (f.model, f.name)):
    if (field.model, field.name) in DROP_FIELDS:
        continue
    if field.ttype == 'many2many':
        table = field.relation_table
        if not table or not table_exists(table):
            relation_only.append(field)
            continue
        # which of the two columns is ours
        ours = field.column2 if field.column2 and 'items' in (field.column2 or '') else None
        if not ours:
            for candidate in (field.column1, field.column2,
                              '%s_id' % LEGACY_TABLE, 'x_all_items_list_id'):
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
print("  %s with nothing stored (relation only)" % len(relation_only))
print("  %s empty bridge(s) on product.product to drop" % len(DROP_FIELDS))
for field, table, ours, count in many2many:
    print("    m2m  %-40s %-30s %s row(s)" % (field.model, table, count))


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
    print("  STOPPED. These hold item ids with no product:")
    for key, strays in unmapped.items():
        print("    %-52s %s" % (key, strays))
    raise SystemExit(
        "\nSettle those items in tools/migrate_items_to_native.py first. "
        "Nothing was changed.")

total = sum(c for _f, _t, c in simple) + sum(c for _f, _t, _o, c in many2many)
print("  every stored id is in the map")
print("  %s row(s) to translate" % total)
for field, table, count in sorted(simple, key=lambda p: -p[2])[:8]:
    print("    %8s  %-40s %s" % (count, field.model, field.name))

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
    cr.execute('ALTER TABLE "%s" ADD CONSTRAINT "%s" FOREIGN KEY ("%s") '
               'REFERENCES "%s"(id) ON DELETE SET NULL NOT VALID'
               % (table, ('%s_%s_fkey' % (table, field.name))[:63],
                  field.name, TARGET_TABLE))
    cr.execute('ALTER TABLE "%s" VALIDATE CONSTRAINT "%s"'
               % (table, ('%s_%s_fkey' % (table, field.name))[:63]))
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
    # pinned down, or Odoo works the table out from the model names and looks
    # for one that was never there
    other = field.column1 if field.column1 != ours else field.column2
    cr.execute("""
        UPDATE ir_model_fields
           SET relation = %s, relation_table = %s, column1 = %s, column2 = %s
         WHERE model = %s AND name = %s
    """, (TARGET_MODEL, table, other or field.column1, ours, field.model, field.name))
    cr.execute('ALTER TABLE "%s" ADD CONSTRAINT "%s" FOREIGN KEY ("%s") '
               'REFERENCES "%s"(id) ON DELETE CASCADE NOT VALID'
               % (table, ('%s_%s_fkey' % (table, ours))[:63], ours, TARGET_TABLE))
    cr.execute('ALTER TABLE "%s" VALIDATE CONSTRAINT "%s"'
               % (table, ('%s_%s_fkey' % (table, ours))[:63]))
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


# --- 4. the empty bridges ---------------------------------------------------

title("4. the empty bridges on product.product")

for model, name in DROP_FIELDS:
    field = IrField.search([('model', '=', model), ('name', '=', name)], limit=1)
    if not field:
        print("  = %s.%s is already gone" % (model, name))
        continue
    table = table_of(model)
    held = 0
    if column_exists(table, name):
        cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL' % (table, name))
        held = cr.fetchone()[0]
    if held:
        print("  ! %s.%s holds %s row(s) - repointed, not dropped" % (model, name, held))
    else:
        try:
            with cr.savepoint():
                field.unlink()
            print("  - %s.%s dropped" % (model, name))
            continue
        except Exception as exc:
            # A field registered as module data cannot be unlinked, and forcing
            # it would mean going behind the module's back. Pointing it at the
            # product instead leaves nothing naming the list, which is what the
            # deletion needs; an empty field on product.product harms nobody.
            print("  ! %s.%s will not drop (%s)"
                  % (model, name, str(exc).strip().splitlines()[0]))
    for fk_name, target in foreign_keys(table, name):
        if target == LEGACY_TABLE:
            cr.execute('ALTER TABLE "%s" DROP CONSTRAINT "%s"' % (table, fk_name))
    cr.execute("UPDATE ir_model_fields SET relation = %s WHERE model = %s AND name = %s",
               (TARGET_MODEL, model, name))
    print("  > %s.%s repointed instead" % (model, name))
cr.commit()

title("summary")
print("  %s row(s) translated" % moved_total)
cr.execute("SELECT COUNT(*) FROM ir_model_fields WHERE relation = %s", (LEGACY_MODEL,))
print("  %s field(s) still naming %s" % (cr.fetchone()[0], LEGACY_MODEL))
print("\n  NEXT: odoosh-restart http")
