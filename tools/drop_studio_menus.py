"""Remove the Studio-owned menus under a named app. Menus only.

    cd ~/src/user
    SSC_MENUS=740,914 odoo-bin shell -d <database> --no-http < tools/drop_studio_menus.py

    APPLY=1   delete. Without it nothing is touched and everything is listed.

drop_studio_models takes a menu with it when the menu opens a model being
deleted. That leaves the other kind: a Studio-made menu that opens a NATIVE
model - "Salary Rule" under a Studio Payroll app pointing at hr.salary.rule -
or opens nothing at all. Those hold an app on the dashboard after every model
of its own is gone, and no model deletion can ever reach them.

A menu is a Studio artefact. Removing one touches no model, no field, no view:
the native app keeps its own menus, and Studio can put this one back in a
minute. So this removes, under each named root, every menu whose
ir.model.data row belongs to studio_customization, deepest first, and the
root itself last if nothing remains beneath it.

It refuses, and says so, when a menu under the root opens a Studio model that
still exists: that is a model somebody has not decided about, and hiding its
menu is not deciding. Name the model on drop_studio_models, or leave the app.

Never a menu a module owns. Never a model. Never a record.
"""
import os

APPLY = os.environ.get('APPLY') == '1'
ROOTS = [int(x) for x in (os.environ.get('SSC_MENUS') or '').replace(' ', '').split(',') if x]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env
Menu = env['ir.ui.menu'].sudo().with_context(active_test=False)
Data = env['ir.model.data'].sudo()

if not ROOTS:
    print("  Name the app roots by menu id: SSC_MENUS=740,914  (probe_studio_apps prints them)")
    raise SystemExit

owner = {row['res_id']: row['module'] for row in
         Data.search_read([('model', '=', 'ir.ui.menu')], ['res_id', 'module'])}


def studio_owned(menu):
    return owner.get(menu.id) in (None, 'studio_customization', '__export__')


def opens(menu):
    """(model or None, kind) for what the menu opens."""
    action = menu.action
    if not action:
        return None, 'nothing'
    if action._name == 'ir.actions.act_window':
        return action.res_model, 'window'
    if action._name == 'ir.actions.server':
        return (action.model_id.model if action.model_id else None), 'server'
    return None, action._name.split('.')[-1]


def subtree(menu):
    out = [menu]
    for child in Menu.search([('parent_id', '=', menu.id)], order='sequence, id'):
        out.extend(subtree(child))
    return out


going, blocked, foreign = [], [], []
for root_id in ROOTS:
    root = Menu.browse(root_id).exists()
    if not root:
        print("  menu %s is not on this database - skipped." % root_id)
        continue
    print()
    print("  APP: %s   (menu id %s)" % (root.complete_name, root.id))
    print("  " + "-" * 96)
    for menu in subtree(root):
        model, kind = opens(menu)
        depth = menu.complete_name.count('/')
        label = ("  " * depth + (menu.name or ''))[:44]
        if not studio_owned(menu):
            foreign.append(menu)
            verdict = "KEPT - owned by %s" % owner.get(menu.id)
        elif model and model.startswith('x_') and model in env:
            blocked.append((menu, model))
            verdict = "BLOCKED - still opens Studio model %s" % model
        else:
            going.append(menu)
            verdict = "goes  (%s)" % (model or kind)
        print("  %-44s %s" % (label, verdict))

print()
print("  %s menu(s) would go, %s blocked, %s kept for a module." % (len(going), len(blocked), len(foreign)))
if blocked:
    print()
    print("  BLOCKED means a Studio model still stands behind the menu. Decide the")
    print("  model first - name it on drop_studio_models - and this menu goes with it.")
    print("  Hiding the menu is not a decision about the model, so it is not made here.")

if not APPLY:
    print()
    print("  DRY RUN - nothing was touched. Re-run with APPLY=1.")
    env.cr.rollback()
else:
    # Deepest first, so a parent is never asked to go while a child stands.
    removed = 0
    for menu in sorted(going, key=lambda m: -m.complete_name.count('/')):
        if Menu.search_count([('parent_id', '=', menu.id)]):
            continue                    # something beneath it is blocked or foreign
        try:
            with env.cr.savepoint():
                menu.unlink()
            removed += 1
        except Exception as exc:                                # noqa: BLE001
            print("      %s kept: %s" % (menu.complete_name, " ".join(str(exc).split())[:80]))
    env.cr.commit()
    print()
    print("  %s of %s menu(s) removed. Committed." % (removed, len(going)))
    left = len(going) - removed
    if left:
        print("  %s stayed because something blocked or module-owned is still beneath them." % left)
