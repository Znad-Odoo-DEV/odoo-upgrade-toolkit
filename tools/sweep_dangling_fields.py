"""Remove field definitions left pointing at models that no longer exist.

    cd ~/src/user
    SSC_MODELS=a,b,c odoo-bin shell -d <database> --no-http < tools/sweep_dangling_fields.py

    APPLY=1   delete. Without it, list only.

When a model is dropped, PostgreSQL drops the foreign-key constraints with the
table, but the columns on the other side stay and so do their ir.model.fields
rows - each one a many2one whose comodel is gone. Odoo tolerates them (it logs
"unknown comodel_name" and points them at _unknown) and the field still shows
on forms as a blank that can never be filled. They are noise, and they are
also exactly the rows drop_studio_models refused once under the "still present
in views" check, before it learned to drop inbound columns under _force_unlink.

Only fields whose relation is one of the NAMED models are touched. Nothing
else: a field pointing at a model that exists is not this script's business,
whatever else may be wrong with it.
"""
import os

APPLY = os.environ.get('APPLY') == '1'
MODELS = [m.strip() for m in (os.environ.get('SSC_MODELS') or '').split(',') if m.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env
IrModel = env['ir.model'].sudo()
IrField = env['ir.model.fields'].sudo()
View = env['ir.ui.view'].sudo().with_context(active_test=False)

if not MODELS:
    print("  Name the deleted models: SSC_MODELS=x_one,x_two")
    raise SystemExit

# Only a model that is actually gone qualifies. A named model that still
# exists is left alone with everything pointing at it.
gone = [m for m in MODELS if not IrModel.search_count([('model', '=', m)])]
still = [m for m in MODELS if m not in gone]
if still:
    print("  still exist, not touched: %s" % ", ".join(still))

dangling = IrField.search([('relation', 'in', gone)]) if gone else IrField.browse()

print()
print("  %s field(s) point at a model that no longer exists:" % len(dangling))
print("  %-34s %-34s %-10s %s" % ("MODEL", "FIELD", "TYPE", "POINTED AT"))
print("  " + "-" * 96)
for field in dangling:
    print("  %-34s %-34s %-10s %s"
          % (field.model[-34:], field.name[-34:], field.ttype, field.relation))

# Views on those models that still carry the field node. Reported, and
# repaired only by removing that one node; a view that will not validate
# afterwards is named so it can be fixed in Studio by hand.
holders = []
for field in dangling:
    token = 'name="%s"' % field.name
    for view in View.search([('model', '=', field.model), ('arch_db', 'like', field.name)]):
        if token in (view.arch_db or ''):
            holders.append((view, field.name))
if holders:
    print()
    print("  %s view(s) still show one of those fields:" % len(holders))
    for view, name in holders:
        print("      %-6s %-50s %s" % (view.id, (view.display_name or '')[:50], name))

if not APPLY:
    print()
    print("  DRY RUN - nothing was touched. Re-run with APPLY=1.")
    env.cr.rollback()
else:
    from lxml import etree

    fixed, broken = 0, []
    for view, name in holders:
        try:
            with env.cr.savepoint():
                arch = etree.fromstring(view.arch_db.encode())
                for node in arch.xpath("//field[@name='%s']" % name):
                    node.getparent().remove(node)
                view.write({'arch': etree.tostring(arch, encoding='unicode')})
            fixed += 1
        except Exception as exc:                                # noqa: BLE001
            broken.append((view, " ".join(str(exc).split())[:90]))
    env.cr.commit()
    if holders:
        print()
        print("  view nodes: %s of %s removed" % (fixed, len(holders)))
    for view, reason in broken:
        print("      view %s (%s) would not validate - fix it in Studio: %s"
              % (view.id, view.model, reason))

    # The same flag the uninstaller uses, for the same reason: without it Odoo
    # LIKEs each field name against every view in the database and refuses.
    forced = dict(env.context, _force_unlink=True)
    killed = 0
    for field in dangling:
        try:
            with env.cr.savepoint():
                field.with_context(forced).unlink()
            killed += 1
        except Exception as exc:                                # noqa: BLE001
            print("      %s.%s kept: %s"
                  % (field.model, field.name, " ".join(str(exc).split())[:90]))
    env.cr.commit()
    print()
    print("  fields: %s of %s removed. Committed." % (killed, len(dangling)))
