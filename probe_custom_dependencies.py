"""List everything in the database that depends on our custom Python.

    odoo-bin shell -d <database> --no-http < tools/probe_custom_dependencies.py

Read-only. Nothing is written.

Why: upgrade.odoo.com runs standard Odoo, so the ssc.* models and their fields
do not exist while the database is being upgraded. Every Studio field, view,
action, filter or automation that reaches into one of them is therefore
dangling there - and that is what makes menus fail the post-upgrade crawler even
though they render perfectly on 18.0.

Each section below is one kind of reference. Sections that come back empty rule
that kind out; whatever is listed is a candidate for being switched off before
the dump, the same way section 1 of pre_upgrade_v19.py handles our two
core-inheriting views.
"""

CUSTOM_MODULES = ('ssc_payroll', 'ssc_attendance')

# Models that only our modules define - those are the ones that vanish
# upgrade-side. Extending res.company with _inherit also files an ir.model.data
# row under our module, so going by ir.model.data alone would sweep in core
# models that are in no danger at all; ir.model.modules lists every module that
# contributes to a model, so a model is ours only when nothing else defines it.
model_data = env['ir.model.data'].search([('model', '=', 'ir.model'),
                                          ('module', 'in', CUSTOM_MODULES)])
custom_models = set()
for model in env['ir.model'].browse(model_data.mapped('res_id')).exists():
    contributors = {m.strip() for m in (model.modules or '').split(',') if m.strip()}
    if contributors and contributors <= set(CUSTOM_MODULES):
        custom_models.add(model.model)
print(f"=== {len(custom_models)} model(s) come from {', '.join(CUSTOM_MODULES)}")
print("   ", ', '.join(sorted(custom_models)) or '(none)')

# --- 1. Studio / manual fields pointing at one of them ---------------------
print("\n=== 1. manual (Studio) fields whose relation is a custom model")
fields_hit = env['ir.model.fields'].search([
    ('state', '=', 'manual'), ('relation', 'in', list(custom_models))])
for f in fields_hit:
    print(f"  FIELD {f.model}.{f.name} -> {f.relation} ({f.ttype})")
print(f"=== {len(fields_hit)} field(s)")

# --- 2. Views on a custom model that we do not own -------------------------
# A Studio-authored view over ssc.employee, say: our module would not restore it,
# and it cannot validate upgrade-side.
print("\n=== 2. views on a custom model that our modules do not own")
ours = env['ir.model.data'].search([('model', '=', 'ir.ui.view'),
                                    ('module', 'in', CUSTOM_MODULES)])
our_view_ids = set(ours.mapped('res_id'))
foreign_views = env['ir.ui.view'].search([('model', 'in', list(custom_models))]) \
                                 .filtered(lambda v: v.id not in our_view_ids)
for v in foreign_views:
    print(f"  VIEW  {v.xml_id or v.id} [{v.model}/{v.type}] active={v.active}")
print(f"=== {len(foreign_views)} view(s)")

# --- 3. Window actions on a custom model that we do not own ----------------
print("\n=== 3. window actions on a custom model that our modules do not own")
our_action_data = env['ir.model.data'].search([
    ('model', '=', 'ir.actions.act_window'), ('module', 'in', CUSTOM_MODULES)])
our_action_ids = set(our_action_data.mapped('res_id'))
foreign_actions = env['ir.actions.act_window'].search(
    [('res_model', 'in', list(custom_models))]).filtered(
    lambda a: a.id not in our_action_ids)
for a in foreign_actions:
    print(f"  ACTION {a.xml_id or a.id} -> {a.res_model}")
print(f"=== {len(foreign_actions)} action(s)")

# --- 4. Saved filters, record rules and automations ------------------------
print("\n=== 4. filters / rules / automations on a custom model")
extras = 0
for model_name, label in (('ir.filters', 'FILTER'),
                          ('ir.rule', 'RULE'),
                          ('base.automation', 'AUTOMATION')):
    if model_name not in env:
        continue
    Model = env[model_name]
    try:
        # ir.filters stores the model as a plain name, the others as a Many2one.
        if model_name == 'ir.filters':
            records = Model.search([('model_id', 'in', list(custom_models))])
        else:
            records = Model.search([('model_id.model', 'in', list(custom_models))])
    except Exception as exc:
        print(f"  ?? {model_name}: {str(exc).splitlines()[0][:100]}")
        continue
    # Records our own modules ship are restored with them; only the ones added
    # from the interface or by Studio are at risk, so drop ours from the list.
    owned = set(env['ir.model.data'].search([
        ('model', '=', model_name), ('module', 'in', CUSTOM_MODULES)]).mapped('res_id'))
    for rec in records:
        if rec.id in owned:
            continue
        extras += 1
        print(f"  {label} {rec.display_name}")
print(f"=== {extras} record(s)")

# --- 5. The other direction: our fields pointing at Studio models ----------
# These survive the upgrade (manual models are rebuilt from ir_model), but they
# are worth seeing next to the rest.
print("\n=== 5. our fields pointing at a Studio model")
# Matched in Python: in a SQL LIKE, '_' is a single-character wildcard, so a
# domain of ('relation', 'like', 'x_') also matches 'expense' and friends.
our_to_studio = env['ir.model.fields'].search([
    ('model', 'in', list(custom_models)), ('relation', '!=', False),
]).filtered(lambda f: f.relation.startswith('x_'))
for f in our_to_studio:
    print(f"  FIELD {f.model}.{f.name} -> {f.relation}")
print(f"=== {len(our_to_studio)} field(s)")
