"""Keep the name of what a Studio link points at, before the target is deleted.

    cd ~/src/user
    SSC_LINKS=x_all_payments_invoice.x_studio_type_of_materials,x_subcontractors_line_dd3e4.x_studio_type_of_work \\
        odoo-bin shell --no-http --shell-interface=python < tools/carry_studio_links_as_names.py
    APPLY=1   write. Without it nothing is touched and everything is counted.

drop_studio_models drops every many2one column that points at a model it
deletes: the column cannot outlive its target. Where that column is on a
Studio model that is itself still in use - a petty cash line naming its type
of material, a subcontract line naming its sector - the value would be gone
before that model gets its own turn.

So for each named link this adds a Char field beside it, "<field>_name",
made the way Studio makes fields (a manual ir.model.fields row, so it is a
real column the model's views can show), and writes the display name of the
target into it. The link itself is left alone; the deletion drops it later.
Idempotent: a field already there is reused, a row already filled is skipped.
A link whose model, field or target is already gone is reported and skipped.
"""
import os

APPLY = os.environ.get('APPLY') == '1'
LINKS = [l.strip() for l in (os.environ.get('SSC_LINKS') or '').split(',') if l.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
Field = env['ir.model.fields'].sudo()
IrModel = env['ir.model'].sudo()

if not LINKS:
    print("Name the links: SSC_LINKS=x_model.x_field,x_other.x_field")
    raise SystemExit()

for link in LINKS:
    model, field = link.rsplit('.', 1)
    Model = env.get(model)
    if Model is None or field not in Model._fields:
        print("  %-60s absent; skipped" % link)
        continue
    definition = Model._fields[field]
    if definition.type != 'many2one':
        print("  %-60s is %s, not many2one; skipped" % (link, definition.type))
        continue
    if definition.comodel_name not in env:
        print("  %-60s points at %s, already gone; skipped" % (link, definition.comodel_name))
        continue
    Model = Model.sudo()
    name_field = field + '_name'
    rows = Model.search([(field, '!=', False)])
    have = name_field in Model._fields
    print("  %-60s -> %-28s %5s row(s) with a value; %s"
          % (link, definition.comodel_name, len(rows),
             "field %s exists" % name_field if have else "field %s to make" % name_field))
    if not APPLY:
        continue
    if not have:
        Field.create({
            'model_id': IrModel.search([('model', '=', model)], limit=1).id,
            'name': name_field,
            'field_description': (definition.string or field) + " (name)",
            'ttype': 'char',
            'state': 'manual',
            'store': True,
            'copied': True,
        })
        # creating a manual field rebuilds the registry the way Studio does;
        # if this registry did not follow, make it
        if name_field not in env[model]._fields:
            env.flush_all()
            env.registry.setup_models(env.cr)
            env.registry.init_models(env.cr, [model], dict(env.context, update_custom_fields=True))
        Model = env[model].sudo()
        rows = Model.search([(field, '!=', False)])
    written = 0
    for row in rows:
        if row[name_field]:
            continue
        target = row[field]
        name = target.display_name if target else ''
        if name:
            row[name_field] = name[:255]
            written += 1
    env.cr.commit()
    print("      %s name(s) written" % written)

if not APPLY:
    print("\nNothing was written. APPLY=1 makes the fields and writes the names.")
