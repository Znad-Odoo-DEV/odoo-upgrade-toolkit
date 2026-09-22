"""Tie the legacy item list to the products, and carry what only it holds.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/migrate_items_to_native.py

Step 0 for the items, and it is a linking job rather than a creation one: the
3,727 rows of x_all_items_list already exist as products - matched by code for
most of them and by name for the rest - so nothing new is made here. Making
them again would leave the catalogue holding everything twice.

 1. each item is matched to a product.template: by default_code first, which is
    exact, then by name, and only when that name is unique on both sides. An
    ambiguous name is reported and left alone rather than guessed at.
 2. the map is written to a config parameter, which is what the repointing
    script reads afterwards.
 3. the attributes only the legacy row holds - the unit as it was written, the
    material type, the kind of item, whether it is counted, the specifications -
    are carried onto the product under x_ names of their own.

What it deliberately does not touch: categ_id and uom_id. The catalogue is
live, its categories are wired into accounting and stock, and the legacy unit
strings ("Nos", "L.m", "ROLL", and a long tail besides) are labels, not units
of measure with conversions behind them. Both are carried as plain fields, to
be turned into real configuration later by a decision made on purpose.
"""
import json
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

LEGACY_MODEL = 'x_all_items_list'
TARGET_MODEL = 'product.template'
ID_MAP_KEY = 'ssc.item_migration.id_map'

# legacy field -> (new name on the product, label)
CARRY = [
    ('x_studio_item_serial_no', 'x_item_serial_no', "Item Serial No."),
    ('x_studio_unit', 'x_unit', "Unit (as written)"),
    ('x_studio_type', 'x_item_type', "Item Type"),
    ('x_studio_type_of_material', 'x_type_of_material', "Type of Material"),
    ('x_studio_quantifiable', 'x_quantifiable', "Quantifiable"),
    ('x_studio_description_specifications', 'x_specifications', "Specifications"),
    ('x_studio_html', 'x_item_notes', "Notes"),
]

cr = env.cr                                                      # noqa: F821
param = env['ir.config_parameter'].sudo()                        # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821

Legacy = env[LEGACY_MODEL].sudo().with_context(active_test=False)  # noqa: F821
Product = env[TARGET_MODEL].sudo().with_context(active_test=False)  # noqa: F821
target_model_id = IrModel.search([('model', '=', TARGET_MODEL)], limit=1).id


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# --- 1. match ---------------------------------------------------------------

title("1. matching items to products")

products = Product.search([])
by_code, by_name = {}, {}
for p in products:
    code = (p.default_code or '').strip()
    if code:
        by_code.setdefault(code, []).append(p)
    name = (p.name or '').strip().lower()
    if name:
        by_name.setdefault(name, []).append(p)

items = Legacy.search([], order='id')


def pick(candidates, item_code):
    """The best of several products for one item, chosen the same way every run.

    A product already spoken for is never offered twice: where a name is shared
    by two items and two products, each ends up with one rather than both
    pointing at the same record.
    """
    free = [p for p in candidates if p.id not in claimed]
    if not free:
        # Every product of that name is already spoken for, which happens where
        # the legacy list holds the same material twice under two codes and the
        # catalogue only ever got one of them. The twin belongs on the same
        # product: both codes name one thing, and everything pointing at either
        # should end up in the same place.
        free = list(candidates)
        shared.append(candidates[0].id if candidates else None)
    if not free:
        return None
    if len(free) == 1:
        return free[0]
    if item_code:
        exact = [p for p in free if (p.default_code or '').strip() == item_code]
        if exact:
            free = exact
    else:
        # an item with no code belongs with the product that has none either
        blank = [p for p in free if not (p.default_code or '').strip()]
        if blank:
            free = blank
    live = [p for p in free if p.active]
    if live:
        free = live
    return sorted(free, key=lambda p: p.id)[0]


id_map, claimed, shared = {}, set(), []
by_code_hits = by_name_hits = 0
unmatched, ambiguous = [], []

# Codes first, and only where the code says one thing on both sides.
for r in items:
    code = (r.x_studio_item_serial_no or '').strip()
    if not code:
        continue
    candidates = by_code.get(code) or []
    chosen = pick(candidates, code) if candidates else None
    if chosen:
        id_map[r.id] = chosen.id
        claimed.add(chosen.id)
        by_code_hits += 1

# Then names, over what is left on both sides.
for r in items:
    if r.id in id_map:
        continue
    code = (r.x_studio_item_serial_no or '').strip()
    name = (r.x_name or '').strip().lower()
    chosen = pick(by_name.get(name) or [], code) if name else None
    if chosen:
        id_map[r.id] = chosen.id
        claimed.add(chosen.id)
        by_name_hits += 1
    elif name in by_name:
        ambiguous.append((r.id, code, r.x_name))
    else:
        unmatched.append((r.id, code, r.x_name))

print("  %s item(s)" % len(items))
print("  matched by code      : %s" % by_code_hits)
print("  matched by name      : %s" % by_name_hits)
print("  every product taken once, so a name shared by two items")
print("  gives each of them its own record")
print("  duplicates consolidated: %s item(s) share a product with their twin"
      % len(shared))
print("  still unmatched      : %s" % (len(ambiguous) + len(unmatched)))
for group, label in ((ambiguous, 'no product left'), (unmatched, 'no product at all')):
    for item_id, code, name in group[:10]:
        print("    %-18s %-14s %s" % (label, code or '-', (name or '')[:44]))
    if len(group) > 10:
        print("    ... and %s more" % (len(group) - 10))


# --- 2. the fields to carry -------------------------------------------------

title("2. attributes to carry onto the product")

existing = {f.name for f in IrField.search([('model', '=', TARGET_MODEL)])}
plan = []
for legacy_name, new_name, label in CARRY:
    if legacy_name not in Legacy._fields:
        print("  ! %s is not on the legacy model" % legacy_name)
        continue
    field = IrField.search([('model', '=', LEGACY_MODEL),
                            ('name', '=', legacy_name)], limit=1)
    filled = sum(1 for r in items if r[legacy_name])
    plan.append((field, new_name, label, filled))
    print("  %-40s -> %-24s %-9s %s row(s)"
          % (legacy_name, new_name, field.ttype,
             filled if new_name not in existing else '%s (field exists)' % filled))

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 3. create the fields ---------------------------------------------------

title("3. fields on the product")

for field, new_name, label, _filled in plan:
    if new_name in existing:
        print("  = %s already there" % new_name)
        continue
    vals = {
        'model_id': target_model_id,
        'model': TARGET_MODEL,
        'name': new_name,
        'field_description': label,
        'ttype': 'char' if field.ttype == 'many2one' else field.ttype,
        'state': 'manual',
        'copied': True,
    }
    if field.ttype == 'selection':
        vals['selection_ids'] = [
            (0, 0, {'value': s.value, 'name': s.name, 'sequence': s.sequence})
            for s in field.selection_ids
        ]
    IrField.create(vals)
    print("  + %s (%s)" % (new_name, vals['ttype']))
env.flush_all()                                                  # noqa: F821
Product = env[TARGET_MODEL].sudo().with_context(active_test=False)  # noqa: F821


# --- 4. carry the values ----------------------------------------------------

title("4. values")

written = 0
for r in items:
    product = Product.browse(id_map.get(r.id)).exists()
    if not product:
        continue
    vals = {}
    for field, new_name, _label, _filled in plan:
        if new_name not in Product._fields:
            continue
        value = r[field.name]
        if not value or product[new_name]:
            continue
        # a many2one is carried as the name it reads under, not as a link into
        # a model that is on its way out
        vals[new_name] = value.display_name if field.ttype == 'many2one' else value
    if vals:
        product.write(vals)
        written += 1
print("  %s product(s) written" % written)


# --- 5. the map -------------------------------------------------------------

param.set_param(ID_MAP_KEY, json.dumps({str(k): v for k, v in sorted(id_map.items())}))
cr.commit()

title("summary")
print("  %s pair(s) in %s" % (len(id_map), ID_MAP_KEY))
print("  %s product(s) carry the legacy attributes" % written)
if ambiguous or unmatched:
    print("  %s item(s) left unmapped - the repointing script will refuse to run "
          "until they are settled" % (len(ambiguous) + len(unmatched)))
