"""Everything still holding on to x_employeeslist, in one place.

    odoo-bin shell --no-http --shell-interface=python < tools/what_still_needs_the_employee_list.py

Reads only. The links are gone - eighty-odd fields translated, and the punch
line with them - so what is left is the awkward remainder: fields declared by a
module rather than by Studio, related paths that read an attribute which was
never going to move, automations that reach an employee the old way, and the
views and rules that mention the model by name.

Each section ends in a verdict rather than a count, because the counts have
stopped being the interesting part. What matters is which of these stops the
model being deleted and which merely stops working the day it is.
"""
import re

LEGACY_MODEL = 'x_employeeslist'
LEGACY_TABLE = 'x_employeeslist'

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
Legacy = env.get(LEGACY_MODEL)                                   # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def table_exists(table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


if Legacy is None or not table_exists(LEGACY_TABLE):
    print("%s is not in this database. Nothing to report." % LEGACY_MODEL)
    raise SystemExit()

Legacy = Legacy.sudo().with_context(active_test=False)
cr.execute('SELECT COUNT(*) FROM "%s"' % LEGACY_TABLE)
row_count = cr.fetchone()[0]

title("0. the model itself")
print("  %s row(s)" % row_count)
print("  %s field(s) declared on it" % IrField.search_count([('model', '=', LEGACY_MODEL)]))


# --- 1. links -----------------------------------------------------------------

title("1. fields that still point at it")

pointing = IrField.search([('relation', '=', LEGACY_MODEL)]).sorted(
    lambda f: (f.state, f.model, f.name))
if not pointing:
    print("  none - every link was translated")
for field in pointing:
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""",
               (field.model.replace('.', '_'), field.name))
    stored_here = bool(cr.fetchone())
    held = '-'
    if stored_here:
        cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL'
                   % (field.model.replace('.', '_'), field.name))
        held = cr.fetchone()[0]
    print("  %-9s %-38s %-34s %s row(s)"
          % (field.state, field.model, field.name, held))
print("\n  A 'base' field is declared by a module: its migration script moves it,")
print("  never this tool. A 'manual' one left here was missed and should not be.")


# --- 2. readers ---------------------------------------------------------------

title("2. related fields that read through it")


def walks_through(model_name, parts):
    current = env.get(model_name)                                # noqa: F821
    for part in parts[:-1]:
        if current is None or part not in current._fields:
            return False
        field = current._fields[part]
        if not field.relational:
            return False
        current = env.get(field.comodel_name)                     # noqa: F821
    return current is not None and current._name == LEGACY_MODEL


readers = []
for field in IrField.search([('related', '!=', False)]):
    parts = (field.related or '').split('.')
    if len(parts) < 2:
        if field.model == LEGACY_MODEL:
            readers.append((field, parts[-1]))
        continue
    if walks_through(field.model, parts):
        readers.append((field, parts[-1]))

by_model = {}
for field, attribute in readers:
    by_model.setdefault(field.model, []).append((field, attribute))
for model in sorted(by_model):
    print("\n  %s" % model)
    for field, attribute in sorted(by_model[model], key=lambda p: p[0].name):
        print("      %-38s %s" % (field.name, field.related))
print("\n  %s field(s) on %s model(s)" % (len(readers), len(by_model)))
print("  These break the day the model goes: Odoo drops a related field whose")
print("  path no longer resolves, and the views showing it fail on open.")


# --- 3. code ------------------------------------------------------------------

title("3. automations and server actions that name it")

Server = env['ir.actions.server'].sudo()                         # noqa: F821
hits = []
for action in Server.search([]):
    code = action.code or ''
    if LEGACY_MODEL in code:
        hits.append((action, 'names the model'))
        continue
    # a field of the list read off an employee link, e.g. <employee>.x_name
    if re.search(r'\.x_studio_[a-z_0-9]+', code) and 'employee' in code.lower():
        hits.append((action, 'reads an employee attribute'))
for action, why in hits:
    print("  %-6s %-46s %s" % (action.id, (action.name or '')[:46], why))
print("\n  %s server action(s)" % len(hits))

Automation = env.get('base.automation')                          # noqa: F821
if Automation is not None:
    rules = Automation.sudo().search([('model_id.model', '=', LEGACY_MODEL)])
    print("  %s automation(s) triggered by the model itself:" % len(rules))
    for rule in rules:
        print("      %-6s %-40s %s" % (rule.id, (rule.name or '')[:40],
                                       'on' if rule.active else 'off'))


# --- 4. the furniture ---------------------------------------------------------

title("4. views, menus, rules and the rest")

model_record = env['ir.model'].sudo().search(                    # noqa: F821
    [('model', '=', LEGACY_MODEL)], limit=1)

for label, model_name, domain in (
    ('views', 'ir.ui.view', [('model', '=', LEGACY_MODEL)]),
    ('window actions', 'ir.actions.act_window', [('res_model', '=', LEGACY_MODEL)]),
    ('filters', 'ir.filters', [('model_id', '=', LEGACY_MODEL)]),
    ('access rules', 'ir.model.access', [('model_id', '=', model_record.id)]),
    ('record rules', 'ir.rule', [('model_id', '=', model_record.id)]),
    ('crons', 'ir.cron', [('model_id', '=', model_record.id)]),
):
    records = env[model_name].sudo().search(domain)              # noqa: F821
    print("  %-16s %s" % (label, len(records)))
    for record in records[:6]:
        print("      %-6s %s" % (record.id, (record.display_name or '')[:56]))
    if len(records) > 6:
        print("      ... and %s more" % (len(records) - 6))

cr.execute("""SELECT COUNT(*) FROM ir_ui_view
               WHERE arch_db::text LIKE %s AND model != %s""",
           ('%' + LEGACY_MODEL + '%', LEGACY_MODEL))
print("  %s view(s) of other models mention it by name" % cr.fetchone()[0])


# --- 5. verdict ---------------------------------------------------------------

title("what stands between here and deleting it")

blocking = [f for f in pointing if f.state == 'manual']
coded = [f for f in pointing if f.state == 'base']
print("""  1. %s Studio link(s) left. Any number above zero is a field the repointing
     tool did not reach, and it must be settled before the model goes.
  2. %s coded link(s), each belonging to a module and moved by that module's
     own migration script.
  3. %s related field(s) reading an attribute that is not moving. They do not
     block the deletion; they break on it, quietly, and the screens showing
     them fail afterwards. Remove them on purpose first.
  4. %s server action(s) reaching an employee the old way.

  The rows themselves - %s of them - are the archive. Nothing reads them once
  the four above are settled, and they go with the model.""" % (
    len(blocking), len(coded), len(readers), len(hits), row_count))
