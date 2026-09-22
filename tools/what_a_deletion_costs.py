"""What a list of models takes with it, and what it takes off other people.

    SSC_LIST=~/going.txt odoo-bin shell --no-http < tools/what_a_deletion_costs.py

Reads only. Writes nothing.

Give it a file with one model name per line - the ones that are going - and it
prints what goes and, more to the point, what the models that are *staying*
lose: every field of theirs that points into the list, how many of their rows
hold a value in it, and every view of theirs that shows one.

That last part is the whole reason this exists. Deleting a model is a decision
about that model; dropping a field off a model that stays is a decision about
somebody else's screen, and it should not arrive as a surprise afterwards.
"""
import os
import re

PATH = os.path.expanduser(os.environ.get('SSC_LIST') or '')

cr = env.cr                                                      # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821
Server = env['ir.actions.server'].sudo()                         # noqa: F821

if not PATH or not os.path.exists(PATH):
    raise SystemExit("Set SSC_LIST to a file with one model name per line.")

wanted = []
for raw in open(PATH):
    name = raw.strip()
    if name and not name.startswith('#'):
        wanted.append(name)

going = set(wanted)


def title(text):
    print("\n" + "=" * 90)
    print(text)
    print("=" * 90)


def table_exists(table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


# Line models come too, and they are not a separate decision. All the way down:
# a line model has line models of its own, and stopping at the first level
# counted x_quantities_summary_line_1b427_line_feb9d - thirty thousand rows -
# as a model that stays and merely loses a field. It does not stay. Its parent
# is going and nothing would ever reach it again.
family = set(going)
while True:
    found = set()
    for field in IrField.search([('ttype', '=', 'many2one'),
                                 ('relation', 'in', list(family))]):
        if field.model in family:
            continue
        if field.model.startswith(field.relation + '_line'):
            found.add(field.model)
    if not found:
        break
    family |= found


title("1. the models on the list")

missing, rows_total = [], 0
print("  %-42s %8s  %s" % ('model', 'rows', 'note'))
for name in wanted:
    record = IrModel.search([('model', '=', name)], limit=1)
    if not record:
        missing.append(name)
        print("  %-42s %8s  NOT A MODEL IN THIS DATABASE" % (name, '-'))
        continue
    Model = env.get(name)                                        # noqa: F821
    rows = 0
    if Model is not None and table_exists(Model._table):
        cr.execute('SELECT COUNT(*) FROM "%s"' % Model._table)
        rows = cr.fetchone()[0]
    rows_total += rows
    print("  %-42s %8s  %s" % (name, rows, (record.name or '')[:40]))

kids = sorted(family - going)
if kids:
    print("\n  and their line models, which cannot be kept without them:")
    for name in kids:
        Model = env.get(name)                                    # noqa: F821
        rows = 0
        if Model is not None and table_exists(Model._table):
            cr.execute('SELECT COUNT(*) FROM "%s"' % Model._table)
            rows = cr.fetchone()[0]
        rows_total += rows
        print("      %-40s %8s" % (name, rows))

print("\n  %s model(s) named, %s line model(s) with them, %s row(s) in all"
      % (len(wanted), len(kids), rows_total))
if missing:
    print("  %s name(s) are not models here - check the spelling before going on"
          % len(missing))


title("2. what the models that STAY lose")

losses = []
for field in IrField.search([('relation', 'in', list(family))]):
    if field.model in family:
        continue
    table = (env[field.model]._table if env.get(field.model) is not None    # noqa: F821
             else field.model.replace('.', '_'))
    held = 0
    if field.ttype == 'many2many':
        if field.relation_table and table_exists(field.relation_table):
            cr.execute('SELECT COUNT(*) FROM "%s"' % field.relation_table)
            held = cr.fetchone()[0]
    elif column_exists(table, field.name):
        cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL'
                   % (table, field.name))
        held = cr.fetchone()[0]
    losses.append((field, held))

if not losses:
    print("  nothing outside the list points at any of them")
else:
    print("  %-32s %-40s %-10s %9s %s"
          % ('model that stays', 'field it loses', 'points at', 'rows', 'owner'))
    for field, held in sorted(losses, key=lambda p: -p[1]):
        print("  %-32s %-40s %-10s %9s %s"
              % (field.model, field.name, field.relation[:10], held, field.state))
    print("\n  %s field(s) on %s model(s) that stay, holding %s value(s)"
          % (len(losses), len({f.model for f, _h in losses}),
             sum(h for _f, h in losses)))
    coded = [f for f, _h in losses if f.state != 'manual']
    if coded:
        print("\n  %s of them say a module declares them, and the deletion will"
              " refuse until that is settled:" % len(coded))
        for field in coded:
            print("      %s.%s" % (field.model, field.name))


title("3. views of models that stay, showing one of those fields")

seen = {}
for field, _held in losses:
    cr.execute("SELECT id FROM ir_ui_view WHERE arch_db::text LIKE %s",
               ('%' + field.name + '%',))
    for (view_id,) in cr.fetchall():
        view = View.browse(view_id).exists()
        if not view or not view.model or view.model in family:
            continue
        seen.setdefault((view.model, view.id, view.name or ''), set()).add(field.name)

for (model_name, view_id, view_name), fields_ in sorted(seen.items()):
    print("  %-30s %-6s %-34s %s"
          % (model_name, view_id, view_name[:34], ', '.join(sorted(fields_))[:40]))
print("\n  %s view(s) on models that stay mention one of the departing fields"
      % len(seen))
print("""
  A node is only removed when its own field is removed, and only inside the
  savepoint that removal has to succeed in. So this is the list of screens that
  will change - not a list of screens at risk.""")


title("4. code that names any of them")

# A model name has to be matched as a whole word, not as a substring. One of
# these models is called x_ - just x_ - and it is a substring of every Studio
# name there is. Matching on containment reported 398 server actions, almost all
# of them belonging to models that are staying, and the deletion tool used the
# same test: it would have deleted them.
NAMES = re.compile(r'(?<![\w.])(%s)(?![\w])'
                   % '|'.join(sorted((re.escape(n) for n in family),
                                     key=len, reverse=True)))

naming = [a for a in Server.search([]) if NAMES.search(a.code or '')]
for action in naming:
    print("  action %-6s %-46s %s" % (action.id, (action.name or '')[:46],
                                      action.model_id.model or ''))

Automation = env.get('base.automation')                          # noqa: F821
rules = []
if Automation is not None:
    ids = IrModel.search([('model', 'in', list(family))]).ids
    rules = Automation.sudo().search([('model_id', 'in', ids)])
for rule in rules:
    print("  rule   %-6s %-46s %s" % (rule.id, (rule.name or '')[:46],
                                      'on' if rule.active else 'off'))
print("\n  %s server action(s), %s automation(s)" % (len(naming), len(rules)))


title("5. chatter, followers and attachments")

for label, table, column in (('messages', 'mail_message', 'model'),
                             ('followers', 'mail_followers', 'res_model'),
                             ('attachments', 'ir_attachment', 'res_model'),
                             ('activities', 'mail_activity', 'res_model')):
    if not table_exists(table) or not column_exists(table, column):
        continue
    cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IN %%s' % (table, column),
               (tuple(family),))
    print("  %-14s %s" % (label, cr.fetchone()[0]))
print("""
  These go with the models and do not come back. Nothing here checks whether
  they were carried anywhere first - that is what the comparison tools are for,
  and running the deletion is the statement that they were read.""")
