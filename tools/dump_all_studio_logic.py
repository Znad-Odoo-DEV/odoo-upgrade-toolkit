"""Every automation and every server action in the database, written to a file.

    odoo-bin shell --no-http --shell-interface=python < tools/dump_all_studio_logic.py
    SSC_OUT=~/logic.md   where to write it (default ~/studio_logic.md)
    SSC_MODELS=a,b       only these models, if you want a slice of it

Reads only. Writes one file and nothing else.

dump_studio_logic.py answers "what does this model do". This answers "what does
the database do", which is the question you have when you are replacing a
system rather than one model of it: four hundred server actions, on sixty
models, calling each other, and no two of them named anything useful.

It goes to a file because it is a book, not a screen. The terminal prints an
index - which model has how much logic in it, and which actions nobody calls -
and the file has all of it in full.

Read the index first. A model with twenty actions is where the system actually
lives; a model with one called "Execute Code" is usually a button somebody
pressed twice in 2024.
"""
import os
import re

OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/studio_logic.md')
ONLY = {m.strip() for m in (os.environ.get('SSC_MODELS') or '').split(',') if m.strip()}

cr = env.cr                                                      # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
Server = env['ir.actions.server'].sudo()                         # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821
Automation = env.get('base.automation')                          # noqa: F821


def get(record, name, default=''):
    return record[name] if name in record._fields else default


def plain(value):
    if isinstance(value, dict):
        return next(iter(value.values()), '')
    return value


# --- who calls what --------------------------------------------------------

# buttons in views: name="<action id>" type="action"
called_by_view = {}
cr.execute("""SELECT id, model, arch_db::text FROM ir_ui_view
               WHERE arch_db::text LIKE '%<button%'""")
BUTTON = re.compile(r'<button[^>]*name=\\?"(\d+)\\?"[^>]*type=\\?"action\\?"')
for view_id, view_model, arch in cr.fetchall():
    for found in BUTTON.findall(arch or ''):
        called_by_view.setdefault(int(found), set()).add(
            '%s (view %s)' % (view_model or '-', view_id))

# actions called from another action's code, by id or by xml id
cr.execute("SELECT id, code FROM ir_act_server WHERE code IS NOT NULL")
called_by_code = {}
for action_id, code in cr.fetchall():
    for found in re.findall(r'\b(\d{3,5})\b', code or ''):
        called_by_code.setdefault(int(found), set()).add(action_id)

rules_by_action = {}
rules = Automation.sudo().search([]) if Automation else []
for rule in rules:
    for action in get(rule, 'action_server_ids') or []:
        rules_by_action.setdefault(action.id, []).append(rule)


def describe_action(action, out, indent='  '):
    out.append("%s#### action %s - %s" % (indent, action.id, action.name or ''))
    owner = get(action, 'model_id')
    out.append("%s- model: `%s`" % (indent, owner.model if owner else '-'))
    out.append("%s- kind: `%s`" % (indent, get(action, 'state')))
    for name, label in (('crud_model_id', 'creates'),
                        ('link_field_id', 'links through'),
                        ('update_path', 'updates'),
                        ('update_field_id', 'updates field'),
                        ('value', 'value'),
                        ('selection_value', 'selection'),
                        ('activity_summary', 'activity'),
                        ('webhook_url', 'posts to')):
        value = get(action, name)
        if not value:
            continue
        try:
            value = value.display_name if hasattr(value, 'display_name') else value
        except Exception:
            value = str(value)
        out.append("%s- %s: %s" % (indent, label, str(value)[:120]))

    if action.id in rules_by_action:
        for rule in rules_by_action[action.id]:
            out.append("%s- called by automation %s (%s), trigger `%s`%s"
                       % (indent, rule.id, rule.name or '', get(rule, 'trigger'),
                          '' if rule.active else ' [OFF]'))
    for where in sorted(called_by_view.get(action.id, [])):
        out.append("%s- button on %s" % (indent, where))
    callers = called_by_code.get(action.id, set()) - {action.id}
    if callers:
        out.append("%s- named in the code of action(s): %s"
                   % (indent, ', '.join(str(c) for c in sorted(callers))))
    if not rules_by_action.get(action.id) and not called_by_view.get(action.id) \
            and not callers:
        out.append("%s- **nothing calls it**" % indent)

    code = get(action, 'code')
    if code:
        out.append("%s```python" % indent)
        for line in str(code).rstrip().splitlines():
            out.append("%s%s" % (indent, line))
        out.append("%s```" % indent)
    for child in get(action, 'child_ids') or []:
        out.append("%s- then:" % indent)
        describe_action(child, out, indent + '  ')
    out.append("")


# --- gather ---------------------------------------------------------------

actions = Server.search([], order='id')
by_model = {}
for action in actions:
    owner = get(action, 'model_id')
    name = owner.model if owner else '(no model)'
    if ONLY and name not in ONLY:
        continue
    by_model.setdefault(name, []).append(action)

rules_by_model = {}
for rule in rules:
    name = get(rule, 'model_id').model if get(rule, 'model_id') else '(no model)'
    if ONLY and name not in ONLY:
        continue
    rules_by_model.setdefault(name, []).append(rule)

names = sorted(set(by_model) | set(rules_by_model),
               key=lambda n: (-len(by_model.get(n, [])), n))

# --- write ----------------------------------------------------------------

out = ["# Every automation and server action in this database", ""]
out.append("%s server action(s) on %s model(s), %s automation(s)."
           % (sum(len(v) for v in by_model.values()), len(by_model), len(rules)))
out.append("")
out.append("| model | actions | automations | uncalled |")
out.append("| --- | ---: | ---: | ---: |")
for name in names:
    mine = by_model.get(name, [])
    loose = [a for a in mine
             if not rules_by_action.get(a.id)
             and not called_by_view.get(a.id)
             and not (called_by_code.get(a.id, set()) - {a.id})]
    out.append("| %s | %s | %s | %s |"
               % (name, len(mine), len(rules_by_model.get(name, [])), len(loose)))
out.append("")

for name in names:
    out.append("")
    out.append("## %s" % name)
    out.append("")
    for rule in rules_by_model.get(name, []):
        out.append("### automation %s - %s%s"
                   % (rule.id, rule.name or '', '' if rule.active else '  [OFF]'))
        for field, label in (('trigger', 'trigger'),
                             ('trigger_field_ids', 'when these change'),
                             ('filter_pre_domain', 'before'),
                             ('filter_domain', 'only when'),
                             ('trg_date_id', 'date field'),
                             ('trg_date_range', 'delay')):
            value = get(rule, field)
            if not value:
                continue
            try:
                value = ', '.join(value.mapped('name')) if hasattr(value, 'mapped') \
                    else value
            except Exception:
                value = str(value)
            out.append("- %s: `%s`" % (label, str(value)[:160]))
        out.append("")
        for action in get(rule, 'action_server_ids') or []:
            describe_action(action, out)
    for action in by_model.get(name, []):
        if rules_by_action.get(action.id):
            continue                      # already printed under its automation
        describe_action(action, out)

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(out))

# --- the index on the screen ----------------------------------------------

print("\n%-40s %8s %8s %8s" % ('model', 'actions', 'rules', 'uncalled'))
for name in names:
    mine = by_model.get(name, [])
    loose = [a for a in mine
             if not rules_by_action.get(a.id)
             and not called_by_view.get(a.id)
             and not (called_by_code.get(a.id, set()) - {a.id})]
    print("%-40s %8s %8s %8s"
          % (name, len(mine), len(rules_by_model.get(name, [])), len(loose)))

print("\n%s server action(s), %s automation(s), %s model(s)"
      % (sum(len(v) for v in by_model.values()), len(rules), len(names)))
print("written to %s" % OUT)
print("""
  Read the index first. A model with twenty actions is where the system lives.
  'uncalled' is an action no automation fires, no button presses and no other
  action names - usually a rule that was replaced and never removed, and
  occasionally one that is called from somewhere this cannot see.""")
