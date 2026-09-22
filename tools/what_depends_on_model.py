"""Everything that would notice if this model went. Any model, one at a time.

    SSC_MODEL=x_to_pay odoo-bin shell --no-http < tools/what_depends_on_model.py

Reads only. The stocktake written for the employee list, made general, because
the same question comes up for every Studio model on the way out and the answer
is never the one you expect: the links are the easy part, and what actually
breaks is a related path somewhere else, or a line of code in an automation
nobody has opened in a year.

It reports in the order the work has to be done:

 1. rows, and what the model is
 2. what points at it - and whether anything is stored in those columns, because
    a link holding nothing is a link nobody will miss
 3. what reads through it, which breaks on deletion rather than blocking it
 4. code that names it, which fails at run time in the middle of doing something
 5. the furniture - views, actions, menus, rules - which goes with the model
 6. what it points at, which is how you tell whether deleting it strands
    anything else

Nothing here decides anything. Deleting a model with rows in it is not a
reversible act, and the point of this is to make the list short enough to read
before that decision is taken.
"""
import os
import re

MODEL = os.environ.get('SSC_MODEL') or ''

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821

if not MODEL:
    raise SystemExit("Set SSC_MODEL, e.g. SSC_MODEL=x_to_pay")

Model = env.get(MODEL)                                           # noqa: F821
record = IrModel.search([('model', '=', MODEL)], limit=1)
if Model is None or not record:
    raise SystemExit("%s is not a model in this database." % MODEL)

TABLE = Model._table


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


# --- 0 ------------------------------------------------------------------------

title("0. %s" % MODEL)

rows = 0
if table_exists(TABLE):
    cr.execute('SELECT COUNT(*) FROM "%s"' % TABLE)
    rows = cr.fetchone()[0]
own = IrField.search([('model', '=', MODEL)])
print("  %-24s %s" % ("name", record.name))
print("  %-24s %s" % ("table", TABLE))
print("  %-24s %s" % ("rows", rows))
print("  %-24s %s (%s declared by a module)"
      % ("fields", len(own), len(own.filtered(lambda f: f.state == 'base'))))
print("  %-24s %s" % ("transient", record.transient))


# --- 1. links in -------------------------------------------------------------

title("1. what points at it")

pointing = IrField.search([('relation', '=', MODEL)]).sorted(
    lambda f: (f.state, f.model, f.name))
held_total = 0
for field in pointing:
    table = (env[field.model]._table if env.get(field.model) is not None    # noqa: F821
             else field.model.replace('.', '_'))
    held = '-'
    if field.ttype == 'many2many':
        relation = field.relation_table
        if relation and table_exists(relation):
            cr.execute('SELECT COUNT(*) FROM "%s"' % relation)
            held = cr.fetchone()[0]
            held_total += held
    elif column_exists(table, field.name):
        cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL'
                   % (table, field.name))
        held = cr.fetchone()[0]
        held_total += held
    print("  %-8s %-9s %-32s %-34s %s"
          % (field.state, field.ttype, field.model, field.name, held))
print("\n  %s field(s), %s row(s) actually holding one" % (len(pointing), held_total))


# --- 2. readers --------------------------------------------------------------

title("2. what reads through it")


def walks_through(model_name, parts):
    current = env.get(model_name)                                # noqa: F821
    for part in parts[:-1]:
        if current is None or part not in current._fields:
            return False
        field = current._fields[part]
        if not field.relational:
            return False
        current = env.get(field.comodel_name)                     # noqa: F821
    return current is not None and current._name == MODEL


readers = []
for field in IrField.search([('related', '!=', False)]):
    parts = (field.related or '').split('.')
    if len(parts) < 2:
        continue
    if walks_through(field.model, parts):
        readers.append(field)
by_model = {}
for field in readers:
    by_model.setdefault(field.model, []).append(field)
for model in sorted(by_model):
    print("\n  %s" % model)
    for field in sorted(by_model[model], key=lambda f: f.name):
        print("      %-34s %s" % (field.name, field.related))
print("\n  %s reader(s) on %s model(s)" % (len(readers), len(by_model)))


# --- 3. code -----------------------------------------------------------------

title("3. code that names it")

Server = env['ir.actions.server'].sudo()                         # noqa: F821
naming = []
for action in Server.search([]):
    if MODEL in (action.code or ''):
        naming.append(action)
for action in naming:
    print("  %-6s %s" % (action.id, (action.name or '')[:60]))
print("\n  %s server action(s)" % len(naming))

Automation = env.get('base.automation')                          # noqa: F821
if Automation is not None:
    rules = Automation.sudo().search([('model_id', '=', record.id)])
    print("  %s automation(s) on the model itself:" % len(rules))
    for rule in rules:
        print("      %-6s %-44s %s" % (rule.id, (rule.name or '')[:44],
                                       'on' if rule.active else 'off'))

cr.execute("""SELECT id, name FROM ir_ui_view
               WHERE arch_db::text LIKE %s""", ('%' + MODEL + '%',))
mentions = cr.fetchall()
print("  %s view(s) name it in their arch" % len(mentions))
for view_id, name in mentions[:8]:
    label = name if isinstance(name, str) else (name or {}).get('en_US', '')
    print("      %-6s %s" % (view_id, str(label)[:58]))


# --- 4. furniture -------------------------------------------------------------

title("4. what goes with it")

for label, model_name, domain in (
    ('views', 'ir.ui.view', [('model', '=', MODEL)]),
    ('window actions', 'ir.actions.act_window', [('res_model', '=', MODEL)]),
    ('menus', 'ir.ui.menu', []),
    ('filters', 'ir.filters', [('model_id', '=', MODEL)]),
    ('access rules', 'ir.model.access', [('model_id', '=', record.id)]),
    ('record rules', 'ir.rule', [('model_id', '=', record.id)]),
    ('crons', 'ir.cron', [('model_id', '=', record.id)]),
    ('attachments', 'ir.attachment', [('res_model', '=', MODEL)]),
    ('messages', 'mail.message', [('model', '=', MODEL)]),
):
    Target = env.get(model_name)                                 # noqa: F821
    if Target is None:
        continue
    if label == 'menus':
        actions = env['ir.actions.act_window'].sudo().search(     # noqa: F821
            [('res_model', '=', MODEL)])
        found = Target.sudo().search(
            [('action', 'in', ['ir.actions.act_window,%s' % a.id for a in actions])])
    else:
        found = Target.sudo().search(domain)
    print("  %-16s %s" % (label, len(found)))
    for item in found[:5]:
        print("      %-8s %s" % (item.id, (item.display_name or '')[:56]))
    if len(found) > 5:
        print("      ... and %s more" % (len(found) - 5))


# --- 5. links out -------------------------------------------------------------

title("5. what it points at")

out = {}
for field in own:
    if field.ttype in ('many2one', 'many2many', 'one2many') and field.relation:
        out.setdefault(field.relation, []).append(field.name)
for target, names in sorted(out.items(), key=lambda kv: -len(kv[1])):
    print("  %-40s %2s field(s)  %s"
          % (target, len(names), ', '.join(sorted(names)[:3])
             + (' ...' if len(names) > 3 else '')))


# --- verdict ------------------------------------------------------------------

title("before deleting %s" % MODEL)
print("""  %s row(s) go with it, and they do not come back.

  %s field(s) point at it: each one must be repointed or removed first, and a
  many2one belonging to a module is moved by that module's migration, never by
  hand.
  %s related field(s) read through it. They do not block the deletion - Odoo
  drops a path it cannot resolve - they simply stop working, and the screens
  showing them fail on open.
  %s server action(s) name it and will raise the next time they run.
  Everything in section 4 is deleted with the model and needs no separate work.

  Nothing above has been changed.""" % (rows, len(pointing), len(readers), len(naming)))
