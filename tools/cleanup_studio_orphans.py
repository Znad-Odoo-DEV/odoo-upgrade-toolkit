"""Delete the Studio menus and actions that point at something that no longer
exists. Run it after tools/pre_upgrade_v19.py has reported them:

    odoo-bin shell -d <database> --no-http < tools/cleanup_studio_orphans.py

It is a DRY RUN by default - it prints what it would remove and changes nothing.
Once the list has been read and agreed, opt in for that one run:

    CLEANUP_DELETE=1 odoo-bin shell -d <database> --no-http < tools/cleanup_studio_orphans.py

The switch lives in the environment rather than in the file so that the copy on
the branch is never the armed one: nobody deletes rows by running this by
accident, and arming it leaves a trace in the shell history.

Only records whose target is genuinely gone are touched: an action whose
res_model is not in ir.model, or a menu whose action row no longer exists or
opens such a model. A menu like that cannot work today either - clicking it
raises - so removing it loses nothing, and it is one less thing for the
post-upgrade crawler to trip over.

Menus and actions that Studio can still resolve are never touched, whatever
their name looks like.
"""

import os

DELETE = os.environ.get('CLEANUP_DELETE') == '1'
MODULE = 'studio_customization'

known_models = set(env['ir.model'].search([]).mapped('model'))
doomed_actions = env['ir.actions.act_window'].browse()
doomed_menus = env['ir.ui.menu'].browse()

# --- actions whose model is gone ------------------------------------------
action_data = env['ir.model.data'].search([
    ('model', '=', 'ir.actions.act_window'), ('module', '=', MODULE)])
action_xmlids = {d.res_id: f"{d.module}.{d.name}" for d in action_data}
for action in env['ir.actions.act_window'].browse(list(action_xmlids)).exists():
    if action.res_model not in known_models:
        doomed_actions |= action
        print(f"  ACTION {action_xmlids[action.id]}: "
              f"res_model '{action.res_model}' does not exist")

# --- menus whose action is gone, or opens a missing model -----------------
menu_data = env['ir.model.data'].search([
    ('model', '=', 'ir.ui.menu'), ('module', '=', MODULE)])
menu_xmlids = {d.res_id: f"{d.module}.{d.name}" for d in menu_data}
for menu in env['ir.ui.menu'].with_context(active_test=False) \
                             .browse(list(menu_xmlids)).exists():
    if not menu.action:
        continue
    try:
        target = menu.action.exists()
    except Exception:
        target = None
    reason = None
    if not target:
        reason = "action is gone"
    elif getattr(target, 'res_model', None) and target.res_model not in known_models:
        reason = f"opens missing model '{target.res_model}'"
    if reason:
        doomed_menus |= menu
        print(f"  MENU   {menu_xmlids[menu.id]} ({menu.complete_name}): {reason}")

print(f"\n=== {len(doomed_menus)} menu(s) and {len(doomed_actions)} action(s) "
      f"are orphaned")

if not DELETE:
    print("=== DRY RUN - nothing removed. Re-run with CLEANUP_DELETE=1 to apply.")
else:
    # Menus first: a menu referencing an action we are about to drop would
    # otherwise be left pointing at nothing.
    for record in (doomed_menus, doomed_actions):
        for rec in record:
            try:
                with env.cr.savepoint():
                    rec.unlink()
            except Exception as exc:
                print(f"  !! could not remove {rec._name} id={rec.id}: "
                      f"{str(exc).splitlines()[0][:120]}")
    env.cr.commit()
    print("=== removed and committed")
