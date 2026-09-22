"""Every Studio model, with what it holds and whether anybody reaches it.

    odoo-bin shell --no-http --shell-interface=python < tools/studio_model_inventory.py
    SSC_SORT=rows  (default)   the fullest first
    SSC_SORT=name              alphabetical
    SSC_SORT=used              the most recently written first

Reads only. Writes nothing.

This is the list to decide from. One line per model:

    rows     how many records it holds. Zero means nothing was ever entered,
             or everything was deleted.
    last     the most recent write_date in it. A model last touched two years
             ago is not a model anybody is using.
    menu     whether a menu item opens it. A model with no menu is reachable
             only from inside another form, or not at all.
    in       fields on other models pointing at it, its own line models not
             counted. This is what has to be settled before it can be deleted.
    lines    its own line models, which go with it.

A line model is listed under its parent and never on its own, because it is not
a decision: it goes when the parent goes and it cannot be kept without it.
"""
import os

SORT = (os.environ.get('SSC_SORT') or 'rows').strip()

cr = env.cr                                                      # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821


def title(text):
    print("\n" + "=" * 100)
    print(text)
    print("=" * 100)


def table_exists(table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


records = IrModel.search([('model', '=like', 'x\\_%')]).sorted('model')
names = {r.model for r in records}

# Which model each one is a line of. Studio names a line model after its parent
# and gives it a many2one back, and both have to be true.
parent_of = {}
for field in IrField.search([('ttype', '=', 'many2one'), ('relation', 'in', list(names))]):
    if field.model not in names:
        continue
    if field.model.startswith(field.relation + '_line'):
        parent_of.setdefault(field.model, field.relation)

# every act_window per model, and whether a menu opens one
cr.execute("SELECT id, res_model FROM ir_act_window")
actions = {}
for action_id, res_model in cr.fetchall():
    actions.setdefault(res_model, []).append(action_id)

cr.execute("SELECT action FROM ir_ui_menu WHERE action IS NOT NULL")
menu_actions = set()
for (action,) in cr.fetchall():
    if action and ',' in action:
        kind, _sep, ident = action.partition(',')
        if kind == 'ir.actions.act_window' and ident.isdigit():
            menu_actions.add(int(ident))

# links in from outside, counted per target
incoming = {}
for field in IrField.search([('relation', 'in', list(names))]):
    target = field.relation
    if field.model == target:
        continue
    if parent_of.get(field.model) == target:
        continue                          # its own line, going with it anyway
    incoming.setdefault(target, []).append(field)

rows_of, last_of = {}, {}
for record in records:
    Model = env.get(record.model)                                # noqa: F821
    if Model is None or not table_exists(Model._table):
        rows_of[record.model] = 0
        continue
    cr.execute('SELECT COUNT(*) FROM "%s"' % Model._table)
    rows_of[record.model] = cr.fetchone()[0]
    if rows_of[record.model] and column_exists(Model._table, 'write_date'):
        cr.execute('SELECT MAX(write_date) FROM "%s"' % Model._table)
        stamp = cr.fetchone()[0]
        last_of[record.model] = str(stamp)[:10] if stamp else ''

children_of = {}
for child, parent in parent_of.items():
    children_of.setdefault(parent, []).append(child)


def line(record, indent=0):
    model_name = record.model
    rows = rows_of.get(model_name, 0)
    kids = children_of.get(model_name, [])
    kid_rows = sum(rows_of.get(k, 0) for k in kids)
    return ("  %-42s %-30s %8s %-11s %-5s %4s %6s"
            % (' ' * indent + model_name,
               (record.name or '')[:30],
               rows,
               last_of.get(model_name, '-'),
               'menu' if any(a in menu_actions for a in actions.get(model_name, []))
               else ('screen' if actions.get(model_name) else '-'),
               len(incoming.get(model_name, [])),
               '%s/%s' % (len(kids), kid_rows) if kids else ''))


title("every Studio model")
print("  %-42s %-30s %8s %-11s %-5s %4s %6s"
      % ('model', 'what Studio called it', 'rows', 'last write', 'menu', 'in', 'lines'))

tops = [r for r in records if r.model not in parent_of]
if SORT == 'name':
    tops.sort(key=lambda r: r.model)
elif SORT == 'used':
    tops.sort(key=lambda r: (last_of.get(r.model, ''), rows_of.get(r.model, 0)),
              reverse=True)
else:
    tops.sort(key=lambda r: (rows_of.get(r.model, 0)
                             + sum(rows_of.get(k, 0)
                                   for k in children_of.get(r.model, []))),
              reverse=True)

by_name = {r.model: r for r in records}
for record in tops:
    print(line(record))

orphan_lines = [r for r in records
                if r.model in parent_of and parent_of[r.model] not in names]
if orphan_lines:
    title("line models whose parent is already gone")
    for record in orphan_lines:
        print(line(record))

title("what this says")
print("""  %s Studio model(s), %s of them line models of another.
  %s row(s) in all of them together.

  'menu'   a menu item opens it.
  'screen' an action exists but no menu points at it.
  '-'      nothing opens it: it is only ever seen inside another form.

  'in' is the number of fields elsewhere pointing at it. Every one has to be
  dropped or repointed before it can be deleted, and the deletion tool will
  refuse until they are.

  Tell me which of these go and which stay. A model that stays is one nothing
  touches: no field of it is removed, no node of it leaves a view."""
      % (len(records), len(parent_of), sum(rows_of.values())))
