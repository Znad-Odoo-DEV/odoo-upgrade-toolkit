"""Point the legacy related fields at the names the product actually uses.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/fix_item_related_paths.py

Repointing the item fields at product.template left every related field that
read an attribute THROUGH one of them reading a name that is not there:
x_studio_item.x_studio_type_of_material, when the product carries it as
x_type_of_material. Odoo drops a related field whose path does not resolve, so
the field disappears from the model and the form that shows it dies with
"field is undefined".

Every related path in the database is walked hop by hop. Where a hop lands on
product.template and the next name is one the migration renamed, the path is
rewritten to the new one. Where the product has no counterpart at all - the
sequence, the stock figure, the odd leftover - the attribute is carried across
first, so the path has something real to land on rather than being cut.

Nothing else is touched: paths that never reach a product are left exactly as
they are.
"""
import json
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

LEGACY_MODEL = 'x_all_items_list'
TARGET_MODEL = 'product.template'
ID_MAP_KEY = 'ssc.item_migration.id_map'

# What the migration already carried, under its new name.
RENAMED = {
    'x_studio_item_serial_no': 'x_item_serial_no',
    'x_studio_unit': 'x_unit',
    'x_studio_type': 'x_item_type',
    'x_studio_type_of_material': 'x_type_of_material',
    'x_studio_quantifiable': 'x_quantifiable',
    'x_studio_description_specifications': 'x_specifications',
    'x_studio_html': 'x_item_notes',
    # the two the product has natively
    'x_name': 'name',
    'x_active': 'active',
}

cr = env.cr                                                      # noqa: F821
param = env['ir.config_parameter'].sudo()                        # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821

Legacy = env.get(LEGACY_MODEL)                                   # noqa: F821
Legacy = Legacy.sudo().with_context(active_test=False) if Legacy is not None else None
Product = env[TARGET_MODEL].sudo().with_context(active_test=False)  # noqa: F821
target_model_id = IrModel.search([('model', '=', TARGET_MODEL)], limit=1).id
id_map = {int(k): int(v) for k, v in
          json.loads(param.get_param(ID_MAP_KEY) or '{}').items()}


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def lands_on_product(model_name, parts):
    """Walk a related path; True when the last hop before the leaf is a product."""
    current = env.get(model_name)                                # noqa: F821
    for part in parts[:-1]:
        if current is None or part not in current._fields:
            return False
        field = current._fields[part]
        if not field.relational:
            return False
        current = env.get(field.comodel_name)                     # noqa: F821
    return current is not None and current._name == TARGET_MODEL


# --- 1. the paths that need turning ----------------------------------------

title("1. related paths reading through an item")

fixes, missing = [], {}
for field in IrField.search([('related', '!=', False)]):
    parts = (field.related or '').split('.')
    if len(parts) < 2:
        continue
    leaf = parts[-1]
    if leaf in Product._fields:
        continue                       # already resolves
    if not lands_on_product(field.model, parts):
        continue
    new_leaf = RENAMED.get(leaf)
    if not new_leaf or new_leaf not in Product._fields:
        missing.setdefault(leaf, []).append('%s.%s' % (field.model, field.name))
        continue
    fixes.append((field.id, field.model, field.name, field.related,
                  '.'.join(parts[:-1] + [new_leaf])))
    print("  %-38s %-30s %s" % (field.model, field.name, fixes[-1][4]))
print("\n  %s path(s) to rewrite" % len(fixes))

if missing:
    title("2. attributes the product does not have yet")
    for leaf, readers in missing.items():
        on_legacy = Legacy is not None and leaf in Legacy._fields
        print("  %-42s %s reader(s)%s" % (
            leaf, len(readers), '' if on_legacy else '   (not on the legacy model either)'))
        for reader in readers[:4]:
            print("      %s" % reader)

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 3. carry what is missing ----------------------------------------------

if missing and Legacy is not None and id_map:
    title("3. carrying the missing attributes")
    for leaf in list(missing):
        if leaf not in Legacy._fields:
            print("  - %s is on neither side - its readers stay broken" % leaf)
            continue
        source = IrField.search([('model', '=', LEGACY_MODEL), ('name', '=', leaf)], limit=1)
        new_name = 'x_' + leaf[len('x_studio_'):] if leaf.startswith('x_studio_') else leaf
        if new_name not in Product._fields:
            IrField.create({
                'model_id': target_model_id,
                'model': TARGET_MODEL,
                'name': new_name,
                'field_description': source.field_description or new_name,
                'ttype': 'char' if source.ttype == 'many2one' else source.ttype,
                'state': 'manual',
                'copied': True,
            })
            env.flush_all()                                      # noqa: F821
            print("  + %s (%s)" % (new_name, source.ttype))
        RENAMED[leaf] = new_name
    Product = env[TARGET_MODEL].sudo().with_context(active_test=False)  # noqa: F821

    written = 0
    for r in Legacy.search([]):
        product = Product.browse(id_map.get(r.id)).exists()
        if not product:
            continue
        vals = {}
        for leaf in missing:
            new_name = RENAMED.get(leaf)
            if not new_name or new_name not in Product._fields:
                continue
            value = r[leaf]
            if not value or product[new_name]:
                continue
            vals[new_name] = (value.display_name
                              if hasattr(value, 'display_name') else value)
        if vals:
            product.write(vals)
            written += 1
    print("  %s product(s) written" % written)

    # now those paths can be turned too
    for field in IrField.search([('related', '!=', False)]):
        parts = (field.related or '').split('.')
        if len(parts) < 2 or parts[-1] in Product._fields:
            continue
        if not lands_on_product(field.model, parts):
            continue
        new_leaf = RENAMED.get(parts[-1])
        if new_leaf and new_leaf in Product._fields:
            fixes.append((field.id, field.model, field.name, field.related,
                          '.'.join(parts[:-1] + [new_leaf])))


# --- 4. rewrite -------------------------------------------------------------

title("4. rewriting")

for field_id, model, name, old, new in fixes:
    cr.execute("UPDATE ir_model_fields SET related = %s WHERE id = %s", (new, field_id))
    print("  %-38s %-30s %s" % (model, name, new))
cr.commit()

title("summary")
print("  %s path(s) rewritten" % len(fixes))
print("\n  NEXT: odoosh-restart http, then open the screen that failed.")
