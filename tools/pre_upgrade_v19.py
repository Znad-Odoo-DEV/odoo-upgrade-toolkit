"""Pre-upgrade preparation for the 18.0 -> 19.0 upgrade.

Run this on a COPY of production (or on production itself) right before the
dump that gets sent to upgrade.odoo.com:

    odoo-bin shell -d <database> --no-http < tools/pre_upgrade_v19.py

Why it is needed
----------------
upgrade.odoo.com always runs standard Odoo only - custom module code is never
loaded there, for any customer. Anything our modules define in Python therefore
does not exist during the upgrade. That is harmless for a view that stands on
its own (it just breaks itself), but a view that INHERITS a core view takes the
whole inheritance tree down with it: one bad xpath on
base.res_config_settings_view_form invalidates every res.config.settings view in
the database, which is what makes the post-upgrade menu crawler fail on every
Settings menu at once.

So: switch those inheriting views off before the dump. Both of them declare
``active`` in their XML, so updating the module on 19.0 turns them straight back
on - there is nothing to undo by hand afterwards.

The Studio part only REPORTS. Deleting Studio menus/actions is destructive and
depends on what the business still uses, so that call stays with a human.
"""

CUSTOM_MODULES = ('ssc_payroll', 'ssc_attendance')

# --------------------------------------------------------------------------
# 1. Deactivate our views that inherit a core view
# --------------------------------------------------------------------------
# Found by walking inherit_id: a view of ours whose parent belongs to another
# module. Listed explicitly so this script says out loud what it touches.
INHERITING_VIEWS = (
    'ssc_attendance.res_config_settings_view_form',   # -> base.res_config_settings_view_form
    'ssc_payroll.view_company_form_ssc_payroll',      # -> base.view_company_form
)

print("\n=== 1. deactivating custom views that inherit core views")
for xmlid in INHERITING_VIEWS:
    view = env.ref(xmlid, raise_if_not_found=False)
    if not view:
        print(f"  .. {xmlid}: not present, skipped")
    elif not view.active:
        print(f"  .. {xmlid}: already inactive")
    else:
        view.active = False
        print(f"  OK {xmlid}: deactivated")

# Safety net: catch any inheriting view added since this script was written.
ours = env['ir.model.data'].search([
    ('model', '=', 'ir.ui.view'),
    ('module', 'in', CUSTOM_MODULES),
])
for view in env['ir.ui.view'].browse(ours.mapped('res_id')).exists():
    if not (view.active and view.inherit_id) or view.xml_id in INHERITING_VIEWS:
        continue
    parent_module = (view.inherit_id.xml_id or '.').split('.')[0]
    if parent_module not in ('',) + CUSTOM_MODULES:
        print(f"  !! {view.xml_id} also inherits {view.inherit_id.xml_id} "
              f"and is still active - add it to INHERITING_VIEWS")

# --------------------------------------------------------------------------
# 1b. Deactivate views built in the interface on top of our models
# --------------------------------------------------------------------------
# A Studio form over ssc.attendance, or a list view someone saved from the UI:
# the model behind it does not exist upgrade-side either, so the view cannot
# validate and the menus that open it fail the crawler.
#
# Unlike our own two views above, these belong to studio_customization or to
# nobody, so nothing turns them back on afterwards - switching them off blindly
# would quietly drop somebody's customisation. The ids are therefore recorded in
# a config parameter, and tools/post_upgrade_v19.py restores exactly this set
# once the database is on 19.0 with our modules loaded again.
RESTORE_KEY = 'ssc.pre_upgrade.deactivated_view_ids'

model_data = env['ir.model.data'].search([('model', '=', 'ir.model'),
                                          ('module', 'in', CUSTOM_MODULES)])
custom_models = set()
for model in env['ir.model'].browse(model_data.mapped('res_id')).exists():
    # A model is ours only when no other module contributes to it: extending
    # res.company with _inherit files an ir.model.data row under us as well.
    contributors = {m.strip() for m in (model.modules or '').split(',') if m.strip()}
    if contributors and contributors <= set(CUSTOM_MODULES):
        custom_models.add(model.model)

our_view_ids = set(ours.mapped('res_id'))
foreign = env['ir.ui.view'].search([('model', 'in', list(custom_models)),
                                    ('active', '=', True)]) \
                           .filtered(lambda v: v.id not in our_view_ids)

print("\n=== 1b. deactivating interface-built views on our models")
for view in foreign:
    view.active = False
    print(f"  OK {view.xml_id or view.id} [{view.model}/{view.type}]: deactivated")
if not foreign:
    print("  .. none")


def record(key, records):
    """Merge ids into a config parameter, so running this twice does not lose
    what the first run recorded."""
    if not records:
        return
    param = env['ir.config_parameter'].sudo()
    previous = {int(i) for i in (param.get_param(key) or '').split(',') if i.strip()}
    param.set_param(key, ','.join(str(i) for i in sorted(previous | set(records.ids))))
    print(f"  -> recorded {len(records)} id(s) under {key}")


record(RESTORE_KEY, foreign)

# --- menus opening an action on one of our models --------------------------
# ir.actions.act_window has no active flag, so an action Studio built over
# ssc.attendance cannot be switched off. The menu that exposes it can be, and
# the menu is what the crawler actually walks.
MENU_RESTORE_KEY = 'ssc.pre_upgrade.deactivated_menu_ids'

our_menu_ids = set(env['ir.model.data'].search([
    ('model', '=', 'ir.ui.menu'), ('module', 'in', CUSTOM_MODULES)]).mapped('res_id'))
doomed_menus = env['ir.ui.menu'].browse()
for menu in env['ir.ui.menu'].search([('action', '!=', False)]):
    if menu.id in our_menu_ids:
        continue
    try:
        action = menu.action.exists()
    except Exception:
        continue
    if action and getattr(action, 'res_model', None) in custom_models:
        doomed_menus |= menu

print("\n=== 1c. deactivating foreign menus that open one of our models")
for menu in doomed_menus:
    menu.active = False
    print(f"  OK {menu.complete_name} -> {menu.action.res_model}: deactivated")
if not doomed_menus:
    print("  .. none")
record(MENU_RESTORE_KEY, doomed_menus)

# --- record rules: reported, never touched ---------------------------------
# A record rule on one of our models is dangling upgrade-side too, but switching
# a rule off widens who can see the data, and it would stay off until somebody
# noticed. That is not a trade this script gets to make on its own.
our_rule_ids = set(env['ir.model.data'].search([
    ('model', '=', 'ir.rule'), ('module', 'in', CUSTOM_MODULES)]).mapped('res_id'))
foreign_rules = env['ir.rule'].search([('model_id.model', 'in', list(custom_models))]) \
                              .filtered(lambda r: r.id not in our_rule_ids)
if foreign_rules:
    print("\n=== 1d. record rules on our models, NOT touched")
    for rule in foreign_rules:
        print(f"  !! {rule.name} [{rule.model_id.model}]")
    print("     Deactivating a record rule widens data access, so this script")
    print("     leaves them alone. They are rules built in the interface, so")
    print("     check after the upgrade that they survived and still apply.")

# Committed here, before the read-only reports below: they walk Studio data and
# every view in the database, and a failure in a report must not cost us the
# deactivation, which is the part that actually matters for the upgrade.
env.cr.commit()
print("  -> committed")

# --------------------------------------------------------------------------
# 2. Report orphan Studio menus and actions (no deletion)
# --------------------------------------------------------------------------
print("\n=== 2. Studio leftovers pointing at something that no longer exists")
known_models = set(env['ir.model'].search([]).mapped('model'))
orphans = 0

actions = env['ir.actions.act_window'].search([])
studio_actions = actions.filtered(
    lambda a: (a.xml_id or '').startswith('studio_customization.'))
for action in studio_actions:
    if action.res_model not in known_models:
        orphans += 1
        print(f"  ACTION {action.xml_id}: res_model '{action.res_model}' does not exist")

# ir.ui.menu has no xml_id field, so the external ids come from ir.model.data.
menu_data = env['ir.model.data'].search([('model', '=', 'ir.ui.menu'),
                                         ('module', '=', 'studio_customization')])
menu_xmlids = {d.res_id: f"{d.module}.{d.name}" for d in menu_data}
menus = env['ir.ui.menu'].with_context(active_test=False) \
                         .browse(list(menu_xmlids)).exists()
for menu in menus:
    xmlid = menu_xmlids[menu.id]
    try:
        target = menu.action and menu.action.exists()
    except Exception:
        # A menu whose action row is gone raises rather than returning empty.
        target = None
    if menu.action and not target:
        orphans += 1
        print(f"  MENU   {xmlid} ({menu.complete_name}): action is gone")
    elif target and getattr(target, 'res_model', None) \
            and target.res_model not in known_models:
        orphans += 1
        print(f"  MENU   {xmlid} ({menu.complete_name}): "
              f"points at missing model '{target.res_model}'")

print(f"\n=== {orphans} Studio leftover(s) reported - review, then remove by hand")

# --------------------------------------------------------------------------
# 3. Report views that are already broken today
# --------------------------------------------------------------------------
# A view that cannot render on 18.0 will not magically render on 19.0. Better to
# find out now than from the upgrade log.
print("\n=== 3. views that fail to render on the current version")
broken = 0
for view in env['ir.ui.view'].search([('active', '=', True)]):
    if not view.model or view.model not in env:
        continue
    try:
        env[view.model].get_view(view.id, view.type)
    except Exception as exc:
        broken += 1
        print(f"  BROKEN {view.xml_id or view.id} [{view.model}]: "
              f"{str(exc).splitlines()[0][:160]}")
print(f"=== {broken} broken view(s)")

# --------------------------------------------------------------------------
# 4. Crawl every menu, the way the post-upgrade TestCrawler does
# --------------------------------------------------------------------------
# Sections 2 and 3 look at Studio leftovers and at views in isolation. This one
# reproduces the actual failing test: walk every menu, resolve its action, and
# render the views that action would open. Comparing this list against the menus
# that failed during the upgrade tells us which failures are real problems in the
# data and which only happen on the upgrade platform, where our Python is absent.
print("\n=== 4. full menu crawl (what TestCrawler does)")
crawl_failures = 0
all_menus = env['ir.ui.menu'].with_context(active_test=False).search(
    [('action', '!=', False)])
for menu in all_menus:
    try:
        action = menu.action.exists()
    except Exception as exc:
        crawl_failures += 1
        print(f"  MENU {menu.complete_name}: action unreadable - "
              f"{str(exc).splitlines()[0][:120]}")
        continue
    if not action or action._name != 'ir.actions.act_window':
        continue
    if not action.res_model or action.res_model not in env:
        crawl_failures += 1
        print(f"  MENU {menu.complete_name}: model '{action.res_model}' missing")
        continue
    try:
        modes = [m.strip() for m in (action.view_mode or 'list').split(',') if m.strip()]
        env[action.res_model].get_views([(False, m) for m in modes])
    except Exception as exc:
        crawl_failures += 1
        print(f"  MENU {menu.complete_name} [{action.res_model}]: "
              f"{str(exc).splitlines()[0][:160]}")
print(f"=== crawled {len(all_menus)} menus, {crawl_failures} failure(s)")

env.cr.commit()
print("\ncommitted. Take the dump now.")
