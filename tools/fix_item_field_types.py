"""Give the carried attributes the type their readers expect.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/fix_item_field_types.py

The material type was carried onto the product as text, to keep the product
from depending on a Studio model. But the model it pointed at - x_type_of_material -
is not part of this migration and is not going anywhere, and nine fields out in
the legacy estate read the material type THROUGH the item as a many2one. A
related field whose type disagrees with what it reads is dropped by Odoo, which
is why the ordered-items form went looking for a field that was no longer there.

So the product carries it as the many2one it always was. The readers then need
no change at all, which is the whole point.

The text field is replaced rather than kept alongside: two fields holding the
same fact, one of them wrong, is how a database starts lying.

It also reports every other related field whose type disagrees with what it now
reads, so the same mistake elsewhere is found here rather than by someone
opening a screen.
"""
import json
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

LEGACY_MODEL = 'x_all_items_list'
TARGET_MODEL = 'product.template'
ID_MAP_KEY = 'ssc.item_migration.id_map'

# legacy field on the item -> the name it was carried under
CARRIED_AS_TEXT = [('x_studio_type_of_material', 'x_type_of_material')]

cr = env.cr                                                      # noqa: F821
param = env['ir.config_parameter'].sudo()                        # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821

Legacy = env[LEGACY_MODEL].sudo().with_context(active_test=False)  # noqa: F821
Product = env[TARGET_MODEL].sudo().with_context(active_test=False)  # noqa: F821
target_model_id = IrModel.search([('model', '=', TARGET_MODEL)], limit=1).id
id_map = {int(k): int(v) for k, v in
          json.loads(param.get_param(ID_MAP_KEY) or '{}').items()}


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# --- 1. what disagrees ------------------------------------------------------

title("1. readers whose type disagrees with what they read")

def leaf_of(model_name, parts):
    current = env.get(model_name)                                # noqa: F821
    for part in parts[:-1]:
        if current is None or part not in current._fields:
            return None, None
        field = current._fields[part]
        if not field.relational:
            return None, None
        current = env.get(field.comodel_name)                     # noqa: F821
    if current is None:
        return None, None
    return current, current._fields.get(parts[-1])


mismatched = []
for field in IrField.search([('related', '!=', False)]):
    parts = (field.related or '').split('.')
    if len(parts) < 2:
        continue
    model, leaf = leaf_of(field.model, parts)
    if model is None or leaf is None or model._name != TARGET_MODEL:
        continue
    if leaf.type != field.ttype:
        mismatched.append((field, leaf))
        print("  %-38s %-28s wants %-10s reads %s"
              % (field.model, field.name, field.ttype, leaf.type))
print("\n  %s reader(s) disagree" % len(mismatched))


# --- 2. the plan ------------------------------------------------------------

title("2. what will change on the product")

plan = []
for legacy_name, product_name in CARRIED_AS_TEXT:
    source = IrField.search([('model', '=', LEGACY_MODEL),
                             ('name', '=', legacy_name)], limit=1)
    current = IrField.search([('model', '=', TARGET_MODEL),
                              ('name', '=', product_name)], limit=1)
    if not source:
        print("  ! %s is not on the legacy model" % legacy_name)
        continue
    if current and current.ttype == source.ttype:
        print("  = %s is already %s" % (product_name, source.ttype))
        continue
    filled = sum(1 for r in Legacy.search([]) if r[legacy_name])
    plan.append((source, current, product_name, filled))
    print("  %s: %s -> %s (%s), %s row(s) to carry again"
          % (product_name, current.ttype if current else 'missing',
             source.ttype, source.relation, filled))

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 3. replace -------------------------------------------------------------

title("3. replacing")

for source, current, product_name, _filled in plan:
    if current:
        current.unlink()
        print("  - %s (text) removed" % product_name)
    IrField.create({
        'model_id': target_model_id,
        'model': TARGET_MODEL,
        'name': product_name,
        'field_description': source.field_description or product_name,
        'ttype': source.ttype,
        'relation': source.relation,
        'state': 'manual',
        'copied': True,
        'on_delete': 'set null' if source.ttype == 'many2one' else False,
    })
    env.flush_all()                                              # noqa: F821
    print("  + %s (%s -> %s)" % (product_name, source.ttype, source.relation))

cr.commit()
Product = env[TARGET_MODEL].sudo().with_context(active_test=False)  # noqa: F821


# --- 4. carry the values again ---------------------------------------------

title("4. values")

written = 0
for source, _current, product_name, _filled in plan:
    if product_name not in Product._fields:
        print("  ! %s is not on the model yet - restart and run again" % product_name)
        continue
    for r in Legacy.search([]):
        product = Product.browse(id_map.get(r.id)).exists()
        if not product:
            continue
        value = r[source.name]
        if not value or product[product_name]:
            continue
        product.write({product_name: value.id if source.ttype == 'many2one' else value})
        written += 1
cr.commit()
print("  %s product(s) written" % written)

title("summary")
print("  %s field(s) replaced, %s value(s) carried" % (len(plan), written))
print("\n  NEXT: odoosh-restart http, then open the screen that failed.")
