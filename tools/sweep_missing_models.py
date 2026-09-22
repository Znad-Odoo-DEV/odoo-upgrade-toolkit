"""Everything still naming a model that no longer exists.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/sweep_missing_models.py

Deleting an ir.model does not take with it everything that held its name. The
foreign keys go - access rules, record rules, server actions, the fields - and
the columns that hold a model name as ordinary text stay exactly as they were:
the window action that opened it, the filters somebody saved on it, the chatter
written against it, the attachments filed under it.

Nothing crashes. It shows up as one line per name in the log,

    ERROR odoo.addons.base.models.ir_model: Missing model x_0_1_delivery_note

written by ir.model.access.check() when something asks whether the current user
may read a model the registry has never heard of, and then the menu quietly does
not appear. Six names were in the log after sixty-eight models were removed, and
none of them had failed anywhere a person could see.

Read-only unless SSC_WRITE=1. A name is only ever swept when env has no such
model - a model that exists and is merely uninstalled is not this, and is left
alone.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

cr = env.cr                                                      # noqa: F821

# table, column, what it is. Only columns holding a model name as text: the
# ones holding a foreign key into ir_model went with the model.
PLACES = (
    ('ir_ui_view',        'model',      'views'),
    ('ir_act_window',     'res_model',  'window actions'),
    ('ir_act_report_xml', 'model',      'reports'),
    ('ir_filters',        'model_id',   'saved filters'),
    ('mail_message',      'model',      'chatter messages'),
    ('mail_followers',    'res_model',  'followers'),
    ('mail_activity',     'res_model',  'activities'),
    ('ir_attachment',     'res_model',  'attachments'),
)


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def table_exists(table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


title("1. rows naming a model that is gone")

plan = []
for table, column, label in PLACES:
    if not table_exists(table) or not column_exists(table, column):
        continue
    cr.execute('SELECT "%s", COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL '
               'GROUP BY "%s" ORDER BY 1' % (column, table, column, column))
    for name, count in cr.fetchall():
        if not name or ' ' in name:
            continue
        if env.get(name) is not None:                            # noqa: F821
            continue
        plan.append((table, column, label, name, count))

for table, column, label, name, count in sorted(plan, key=lambda r: (r[3], r[0])):
    print("  %-40s %-18s %5s  %s" % (name, label, count, table))
print("\n  %s name(s) across %s row(s)"
      % (len({row[3] for row in plan}), sum(row[4] for row in plan)))


# --- 2. menus pointing at an action that is not there ------------------------

title("2. menus whose action no longer exists")

# Read the column, not the field. ir.ui.menu.action is a Reference, and a
# Reference whose target is gone reads back as False - so asking the ORM
# "which menus have an action" skips exactly the broken ones. Fifty-nine of
# them survived a sweep that way, and the first one somebody opened - the
# Configuration menu - was a white screen and a database that looked dead.
Menu = env['ir.ui.menu'].sudo()                                  # noqa: F821
cr.execute("""SELECT id FROM ir_ui_menu
               WHERE action IS NOT NULL
                 AND split_part(action, ',', 2) ~ '^[0-9]+$'
                 AND split_part(action, ',', 2)::int
                     NOT IN (SELECT id FROM ir_actions)""")
orphan_menus = Menu.browse([row[0] for row in cr.fetchall()])

for menu in orphan_menus:
    print("  %-6s %s" % (menu.id, (menu.complete_name or menu.name or '')[:66]))
print("\n  %s menu(s)" % len(orphan_menus))
if orphan_menus:
    print("""
  These are emptied rather than deleted: the menu may be somebody's place in a
  hierarchy, and a menu with no action is a heading. A menu with neither an
  action nor children is removed.""")

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing changed. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


title("3. sweeping")

swept = 0
for table, column, label, name, count in plan:
    try:
        with cr.savepoint():
            cr.execute('DELETE FROM "%s" WHERE "%s" = %%s' % (table, column), (name,))
        swept += count
        print("  - %-40s %-18s %5s" % (name, label, count))
    except Exception as exc:
        print("  ! %-40s %-18s %s"
              % (name, label, str(exc).strip().splitlines()[0][:60]))
cr.commit()
print("\n  %s row(s) removed" % swept)

emptied, removed = 0, 0
for menu in orphan_menus:
    if not menu.exists():
        continue
    try:
        with cr.savepoint():
            if menu.child_id:
                # A menu with children is somebody's place in a hierarchy: it
                # becomes a heading rather than disappearing and taking the
                # branch with it. Written in SQL because the ORM will not write
                # a Reference field whose current value it cannot resolve.
                cr.execute("UPDATE ir_ui_menu SET action = NULL WHERE id = %s",
                           (menu.id,))
                emptied += 1
            else:
                cr.execute("DELETE FROM ir_ui_menu WHERE id = %s", (menu.id,))
                removed += 1
    except Exception as exc:
        print("  ! menu %-6s %s" % (menu.id, str(exc).strip().splitlines()[0][:60]))
cr.commit()
print("  %s menu(s) emptied, %s removed" % (emptied, removed))


title("3b. action rows left behind in ir_actions")

# ir.actions.act_window shares its id with a row in ir_actions, and deleting
# only from ir_act_window leaves the parent behind: a record that answers to an
# id, has no window, and takes down whatever opens it.
cr.execute("""SELECT id FROM ir_actions WHERE type = 'ir.actions.act_window'
               AND id NOT IN (SELECT id FROM ir_act_window)""")
half_gone = [row[0] for row in cr.fetchall()]
print("  %s row(s)" % len(half_gone))
if half_gone:
    cr.execute("UPDATE res_users SET action_id = NULL WHERE action_id IN %s",
               (tuple(half_gone),))
    print("  %s user(s) had one as their home action" % cr.rowcount)
    cr.execute("DELETE FROM ir_actions WHERE id IN %s", (tuple(half_gone),))
    print("  %s removed" % cr.rowcount)
    cr.commit()


title("4. what is left")

left = 0
for table, column, label in PLACES:
    if not table_exists(table) or not column_exists(table, column):
        continue
    cr.execute('SELECT DISTINCT "%s" FROM "%s" WHERE "%s" IS NOT NULL'
               % (column, table, column))
    for (name,) in cr.fetchall():
        if name and ' ' not in name and env.get(name) is None:   # noqa: F821
            left += 1
            print("  %-40s %s" % (name, table))
print("\n  %s left" % left)
print("""
  Restart, then open the menus. The log is the only place this was ever
  reported, so the log is where it is checked: no line saying Missing model
  means there is nothing left holding a name that answers to nothing.""")
