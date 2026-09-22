"""The Studio site stores, as locations and quantities of the native inventory.

    odoo-bin shell --no-http --shell-interface=python < tools/import_studio_store.py
    SSC_WRITE=1     actually write
    SSC_OUT=~/store_migration.md

Dry by default, and idempotent: every location carries the Studio store it was
made from, and a quantity already counted is never counted twice.

WHAT IS CARRIED, AND WHAT IS NOT

    x_type_of_material (121)      -> product.category, keeping the expense
                                     account each type carried
    the item on a store line      -> the product it already names; where it
                                     names none, the product of the same name,
                                     then of the same internal reference
    x_inventory_stores_pro (18)   -> stock.location, one per store, under the
                                     warehouse of its company, carrying the
                                     project and the storekeeper
    the line's available quantity -> read by import_studio_store_moves.py, which
                                     replays the history and adjusts to it
    the threshold a store line points at (x_minimum_material)
                                  -> stock.warehouse.orderpoint on that product in that store

    the 5,546 transactions        -> tools/import_studio_store_moves.py, as
                                     receipts, consumptions and transfers with
                                     their dates and their states

QUANTITIES ONLY, DELIBERATELY

Every product category on this database values stock periodically, and the
store's own rates are zero on all but three of the eighteen stores. The cost of
material is already on the project through the bill that bought it; valuing the
same material again as it leaves the store would count it twice. So this writes
counts, not money, and posts no accounting entry.

A product that is not storable holds no quantity. The ones this carries are
made storable - only those, and only where a store actually has some of them.
"""
import os
import re

WRITE = os.environ.get('SSC_WRITE') == '1'
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/store_migration.md')

STORES = 'x_inventory_stores_pro'
STORE_LINES = 'x_studio_one2many_field_113_1if9packl'
TYPES = 'x_type_of_material'
MINIMUM = 'x_minimum_material'

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say('')
    say(rule * 96)
    say(text)
    say(rule * 96)


def finish():
    with open(OUT, 'w', encoding='utf-8') as handle:
        handle.write("\n".join(report) + "\n")
    print("\nwritten to %s" % OUT)
    raise SystemExit()


def norm(text):
    return re.sub(r'[^a-z0-9]', '', (text or '').lower())


def get(record, name, default=False):
    """A field Studio may or may not have here.

    x_studio_item_serial_no exists on production and not on the branch that
    deleted the item catalogue it came from, so nothing may assume a column.
    """
    if not record or name not in record._fields:
        return default
    value = record[name]
    return default if value is False or value is None else value


env = env(context=dict(env.context, lang='en_US', active_test=False))   # noqa: F821
cr = env.cr

Store = env.get(STORES)
if Store is None:
    print("%s is not on this database; nothing to carry." % STORES)
    raise SystemExit()
Store = Store.sudo()
Type = env.get(TYPES)
Minimum = env.get(MINIMUM)

Product = env['product.template'].sudo()
Category = env['product.category'].sudo()
Location = env['stock.location'].sudo()
Warehouse = env['stock.warehouse'].sudo()
Quant = env['stock.quant'].sudo()
Orderpoint = env['stock.warehouse.orderpoint'].sudo()

title("the stores, as they are")
say("  %s store(s) in Studio" % Store.search_count([]))
say("  %s already carried" % Location.search_count([('ssc_studio_ref_id', '!=', False)]))


# ---------------------------------------------------------------- products
def product_of(line, by_name, by_code):
    """The product a store line is about."""
    linked = get(line, 'x_studio_item') or get(line, 'x_studio_product')
    if linked:
        return linked
    found = by_name.get(norm(get(line, 'x_name', '')))
    if found:
        return found
    return by_code.get(norm(get(line, 'x_studio_item_serial_no', '')))


by_name, by_code = {}, {}
for product in Product.search([]):
    by_name.setdefault(norm(product.name), product)
    if product.default_code:
        by_code.setdefault(norm(product.default_code), product)

lines_by_store = {}
unmatched = []
for store in Store.search([], order='id'):
    live = [line for line in store[STORE_LINES]
            if (get(line, 'x_studio_available_quantity', 0) or 0) > 0]
    lines_by_store[store] = live
    for line in live:
        if not product_of(line, by_name, by_code):
            unmatched.append((store, line))

title("what the stores hold")
say("  %-42s %6s %10s %12s" % ("store", "items", "quantity", "value"))
for store, live in lines_by_store.items():
    if not live:
        continue
    say("  %-42s %6s %10.2f %12.2f"
        % ((store.x_name or '')[:42], len(live),
           sum(get(l, 'x_studio_available_quantity', 0) or 0 for l in live),
           sum(get(l, 'x_studio_total_amount', 0) or 0 for l in live)))
say("")
say("  %s line(s) with a quantity, %s of them naming a product this database "
    "does not have:" % (sum(len(v) for v in lines_by_store.values()), len(unmatched)))
for store, line in unmatched[:20]:
    say("      %-40s %-30s %s" % ((store.x_name or '')[:40], (get(line, 'x_name', '') or '')[:30],
                                  get(line, 'x_studio_available_quantity', 0)))
if unmatched:
    say("  Those lines are left where they are: a quantity on a product nobody "
        "can name is a quantity nobody can use.")


# -------------------------------------------------------------- categories
title("the material types, as product categories")
category_of_type = {}
made = reused = 0
if Type is None:
    say("  %s is not here; the products keep the category they have" % TYPES)
else:
    root = env.ref('product.product_category_all', raise_if_not_found=False)
    for source in Type.sudo().search([], order='x_studio_sequence, id'):
        name = (source.x_name or '').strip()
        if not name:
            continue
        found = Category.search([('name', '=', name)], limit=1)
        if found:
            category_of_type[source.id] = found
            reused += 1
            continue
        values = {'name': name}
        if root:
            values['parent_id'] = root.id
        account = get(source, 'x_studio_account')
        if WRITE:
            category = Category.create(values)
            if account and 'property_account_expense_categ_id' in Category._fields:
                category.property_account_expense_categ_id = account.id
            category_of_type[source.id] = category
        made += 1
say("  %s to make, %s already there" % (made, reused))


# ------------------------------------------------------------------ stores
title("the stores, as locations")


def warehouse_of(store):
    """The warehouse a store's location hangs under: its company's."""
    project = get(store, 'x_studio_project_1')
    company = get(store, 'x_studio_company') or (project.company_id if project else False)
    if not company:
        company = env.company
    found = Warehouse.search([('company_id', '=', company.id)], order='id', limit=1)
    return found


plan_locations = []
for store, live in lines_by_store.items():
    existing = Location.search([('ssc_studio_ref_id', '=', store.id)], limit=1)
    warehouse = warehouse_of(store)
    plan_locations.append((store, live, warehouse, existing))
    say("  %-42s -> %-28s %s"
        % ((store.x_name or '')[:42],
           (warehouse.name or '(no warehouse)')[:28],
           "already made" if existing else ("%s item(s)" % len(live) if live else "empty")))


# ------------------------------------------------------------------ writing
if not WRITE:
    title("nothing was written")
    say("  Run again with SSC_WRITE=1 once the two lists above are the ones you")
    say("  expect: what each store holds, and the items nobody can name.")
    finish()

title("writing")

locations = {}
for store, live, warehouse, existing in plan_locations:
    location = existing
    if not location:
        if not warehouse:
            say("  ! %s has no warehouse for its company; skipped" % (store.x_name or store.id))
            continue
        location = Location.create({
            'name': (store.x_name or 'Store')[:64],
            'location_id': warehouse.lot_stock_id.id,
            'usage': 'internal',
            'company_id': warehouse.company_id.id,
            'ssc_studio_ref_id': store.id,
            'ssc_project_id': get(store, 'x_studio_project_1') and get(store, 'x_studio_project_1').id,
            'ssc_storekeeper_id': (get(store, 'x_studio_store_keeper')
                                   and get(store, 'x_studio_store_keeper').id),
        })
    locations[store.id] = location
cr.commit()
say("  %s location(s) in place" % len(locations))

# the products that will hold a quantity have to be storable
storable = set()
for store, live in lines_by_store.items():
    for line in live:
        product = product_of(line, by_name, by_code)
        if product:
            storable.add(product.id)
products = Product.browse(sorted(storable))
turned = products.filtered(lambda p: not p.is_storable)
if turned:
    turned.write({'is_storable': True})
    cr.commit()
say("  %s product(s) hold stock, %s of them made storable" % (len(products), len(turned)))

# the category each product belongs to, where Studio said one: on the
# product itself (x_type_of_material, 3,455 of them), and on the store line
moved = 0
if 'x_type_of_material' in Product._fields:
    for product in Product.search([('x_type_of_material', '!=', False)]):
        category = category_of_type.get(product.x_type_of_material.id)
        if category and product.categ_id != category:
            product.categ_id = category.id
            moved += 1
for store, live in lines_by_store.items():
    for line in live:
        product = product_of(line, by_name, by_code)
        source_type = get(line, 'x_studio_type_of_material')
        category = source_type and category_of_type.get(source_type.id)
        if product and category and product.categ_id != category:
            product.categ_id = category.id
            moved += 1
cr.commit()
say("  %s product(s) put in the category their material type names" % moved)

title("the opening count")
say("  Not taken here. The history is replayed transaction by transaction by")
say("  tools/import_studio_store_moves.py, which then compares what the replay")
say("  left on hand with what each store says and adjusts the difference.")

title("the minimum quantities")
# x_minimum_material is not a list of items: it is a list of thresholds
# ("Less than (200.0)") that a store line points at through
# x_studio_minimum_material, with the number in x_studio_below. So the rule
# belongs to the store line: this product, in this store, below this much.
made = 0
for store, live in lines_by_store.items():
    location = locations.get(store.id)
    if not location:
        continue
    for line in store[STORE_LINES]:
        threshold = get(line, 'x_studio_minimum_material')
        below = get(threshold, 'x_studio_below', 0.0) if threshold else get(line, 'x_studio_below', 0.0)
        if not threshold or not below:
            continue
        product = product_of(line, by_name, by_code)
        if not product or not product.product_variant_id:
            continue
        if Orderpoint.search_count([('product_id', '=', product.product_variant_id.id),
                                    ('location_id', '=', location.id)]):
            continue
        # in the company of the store, not the shell's: a rule on Royal
        # Arrow's store made from SSC's side is a company crossover
        Orderpoint.with_company(location.company_id).create({
            'product_id': product.product_variant_id.id,
            'location_id': location.id,
            'warehouse_id': location.warehouse_id.id,
            'company_id': location.company_id.id,
            'product_min_qty': below,
            'product_max_qty': below,
            'trigger': 'manual',
        })
        made += 1
cr.commit()
say("  %s reordering rule(s) made from the store lines that carry a threshold" % made)

title("done")
say("  The stores are locations, what they hold is on hand, and the history")
say("  stays in Studio until it is archived and the models are deleted.")
say("  Open Inventory > Reporting > Stock and group by location.")
finish()
