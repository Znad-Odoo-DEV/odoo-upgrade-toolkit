"""Lay the foreign keys back down on the repointed project columns.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/restore_project_foreign_keys.py

Phase B, step 3. tools/repoint_legacy_project_fields.py had to drop each
column's foreign key before it could translate the ids under it. Odoo does not
put them back on its own: it creates the key for a manual field when it creates
the column, and the columns were already there.

Nothing is broken without them - the ORM checks a many2one on write either way -
but the database stops enforcing what it used to, and a project deleted one day
would leave dangling ids behind. So they go back, with the ON DELETE SET NULL
that Odoo gives a manual many2one.

Each key is added NOT VALID first and validated afterwards. The first takes a
brief lock, the second a weak one, so a table of half a million rows is never
held still while the whole file is checked.

It also reports what is left tied to the old list - a relation table belonging
to a field that no longer exists, say - because anything still pointing at
x_projects_list will refuse to let it be deleted.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

LEGACY_TABLE = 'x_projects_list'
TARGET_TABLE = 'project_project'
TARGET_MODEL = 'project.project'

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def has_column(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


def has_foreign_key(table, column):
    cr.execute("""
        SELECT 1 FROM pg_constraint con
          JOIN pg_class src ON src.oid = con.conrelid
          JOIN pg_attribute att ON att.attrelid = con.conrelid
                               AND att.attnum = ANY (con.conkey)
         WHERE con.contype = 'f' AND src.relname = %s AND att.attname = %s
    """, (table, column))
    return bool(cr.fetchone())


# --- 1. what is missing a key ----------------------------------------------

title("1. columns to secure")

todo = []
for field in IrField.search([('relation', '=', TARGET_MODEL),
                             ('state', '=', 'manual')]).sorted(lambda f: f.model):
    model = env.get(field.model)                                 # noqa: F821
    if model is None:
        continue
    table = model._table
    if not has_column(table, field.name) or has_foreign_key(table, field.name):
        continue
    cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL' % (table, field.name))
    todo.append((table, field.name, cr.fetchone()[0]))

print("  %s column(s) without a foreign key" % len(todo))


# --- 2. would any of them fail? --------------------------------------------

title("2. dangling values")

dangling = []
for table, column, _count in todo:
    cr.execute("""
        SELECT COUNT(*) FROM "%s" t
         WHERE t."%s" IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM "%s" p WHERE p.id = t."%s")
    """ % (table, column, TARGET_TABLE, column))
    stray = cr.fetchone()[0]
    if stray:
        dangling.append((table, column, stray))

if dangling:
    print("  STOPPED. These columns hold ids no project has:")
    for table, column, stray in dangling:
        print("    %-46s %-34s %s row(s)" % (table, column, stray))
    raise SystemExit(
        "\nNothing was changed. Those rows have to be settled before the "
        "database can be asked to enforce the link.")
print("  none - every id in every column is a project that exists")


# --- 3. what is still tied to the old list ----------------------------------

title("3. still tied to %s" % LEGACY_TABLE)

cr.execute("""
    SELECT src.relname, att.attname, con.conname
      FROM pg_constraint con
      JOIN pg_class src ON src.oid = con.conrelid
      JOIN pg_class tgt ON tgt.oid = con.confrelid
      JOIN pg_attribute att ON att.attrelid = con.conrelid
                           AND att.attnum = ANY (con.conkey)
     WHERE con.contype = 'f' AND tgt.relname = %s
""", (LEGACY_TABLE,))
leftovers = cr.fetchall()
if not leftovers:
    print("  nothing")
for table, column, conname in leftovers:
    cr.execute('SELECT COUNT(*) FROM "%s"' % table)
    rows = cr.fetchone()[0]
    owner = IrField.search([('relation_table', '=', table)], limit=1)
    cr.execute("""SELECT 1 FROM information_schema.tables WHERE table_name = %s""",
               (table,))
    print("  %-46s %-24s %s row(s)" % (table, column, rows))
    print("      constraint : %s" % conname)
    print("      field      : %s" % (
        '%s.%s' % (owner.model, owner.name) if owner
        else 'none - the field it belonged to is gone'))
    print("      note       : this has to be settled before %s can be deleted"
          % LEGACY_TABLE)


if DRY_RUN:
    print("\n  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 4. add the keys --------------------------------------------------------

title("4. adding")

added = 0
for table, column, count in todo:
    name = '%s_%s_fkey' % (table, column)
    if len(name) > 63:                       # postgres identifier limit
        name = name[:63]
    cr.execute("""
        ALTER TABLE "%s"
          ADD CONSTRAINT "%s" FOREIGN KEY ("%s") REFERENCES "%s"(id)
              ON DELETE SET NULL NOT VALID
    """ % (table, name, column, TARGET_TABLE))
    cr.commit()
    cr.execute('ALTER TABLE "%s" VALIDATE CONSTRAINT "%s"' % (table, name))
    cr.commit()
    added += 1
    print("  + %-46s %-34s %s row(s)" % (table, column, count))

title("summary")
print("  %s foreign key(s) added" % added)
cr.execute("""
    SELECT COUNT(*) FROM pg_constraint con
      JOIN pg_class tgt ON tgt.oid = con.confrelid
     WHERE con.contype = 'f' AND tgt.relname = %s
""", (TARGET_TABLE,))
print("  %s now point at %s" % (cr.fetchone()[0], TARGET_TABLE))
print("  %s still tied to %s (listed above)" % (len(leftovers), LEGACY_TABLE))
