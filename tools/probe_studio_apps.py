"""What is behind each Studio app on the dashboard. Reads only.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http < tools/probe_studio_apps.py

An app on the dashboard is a root menu, and a Studio app is one whose
ir.model.data row belongs to studio_customization. This walks each one down
to its leaves and says, for every leaf, which action it opens, which model that
action is on, how many rows the model holds, and whether the model still
exists. A leaf whose model is gone is a dead menu; a leaf whose model has rows
is a decision.

The point is to turn "delete this app" into the list of models it actually
stands on, so the deletion can be named model by model and nothing else is
touched.
"""
WIDTH = 100

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

Menu = env['ir.ui.menu'].sudo().with_context(active_test=False)
Data = env['ir.model.data'].sudo()
IrModel = env['ir.model'].sudo()

studio_menu_ids = {
    row['res_id'] for row in Data.search_read(
        [('model', '=', 'ir.ui.menu'), ('module', '=', 'studio_customization')],
        ['res_id'])
}

roots = Menu.search([('parent_id', '=', False)], order='sequence, id')
apps = roots.filtered(lambda m: m.id in studio_menu_ids)

print()
print("=" * WIDTH)
print("STUDIO APPS ON THE DASHBOARD, AND THE MODELS THEY STAND ON")
print("=" * WIDTH)

models_seen = {}


def describe_action(action):
    """(model name, row count or None, note) for whatever the menu opens."""
    if not action:
        return None, None, "no action"
    if action._name == 'ir.actions.act_window':
        name = action.res_model
    elif action._name == 'ir.actions.server':
        name = action.model_id.model if action.model_id else None
    elif action._name == 'ir.actions.client':
        return None, None, "client action: %s" % (action.tag or '')
    else:
        return None, None, action._name
    if not name:
        return None, None, "%s without a model" % action._name
    if name not in env:
        return name, None, "MODEL GONE"
    if name in models_seen:
        return name, models_seen[name], ""
    count = env[name].sudo().with_context(active_test=False).search_count([])
    models_seen[name] = count
    return name, count, ""


def walk(menu, depth):
    model, count, note = describe_action(menu.action)
    indent = "  " * depth
    label = (indent + (menu.name or ''))[:40]
    if model:
        shown = "%s row%s" % (count, "" if count == 1 else "s") if count is not None else "-"
        print("  %-40s %-30s %-10s %s" % (label, model[-30:], shown, note))
    else:
        print("  %-40s %-30s %-10s %s" % (label, "", "", note))
    for child in Menu.search([('parent_id', '=', menu.id)], order='sequence, id'):
        walk(child, depth + 1)


for app in apps:
    print()
    print("  APP: %s   (menu id %s)" % (app.name, app.id))
    print("  " + "-" * (WIDTH - 4))
    print("  %-40s %-30s %-10s %s" % ("MENU", "MODEL", "ROWS", "NOTE"))
    for child in Menu.search([('parent_id', '=', app.id)], order='sequence, id'):
        walk(child, 1)

print()
print("=" * WIDTH)
print("THE MODELS, ONCE EACH")
print("=" * WIDTH)
print("  %-42s %8s   %s" % ("MODEL", "ROWS", "STUDIO?"))
print("  " + "-" * (WIDTH - 4))
for name in sorted(models_seen):
    print("  %-42s %8s   %s" % (name[-42:], models_seen[name],
                                "yes" if name.startswith('x_') else "NATIVE - never a target"))
print()
print("  Name the x_ ones to delete on SSC_MODELS. Their menus go with them, and")
print("  an app whose menus are all gone is swept only if Studio owns it.")
print("=" * WIDTH)

env.cr.rollback()
