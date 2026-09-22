"""What the store carry left for a person to decide, decided.

    odoo-bin shell --no-http --shell-interface=python < tools/settle_store_residue.py
    SSC_WRITE=1     actually write

Three things the replay named and did not settle:

  the gloves        two Studio store lines, "BLUE DOTTED GLOVES", 38 and 13,
                    naming no product. The product exists, spelt "Blue dotts
                    gloves"; each store is adjusted to what its lines add up
                    to, the same way the rest of the balance was: named, and
                    dated the cutover.
  the 2027 receipt  one receipt stage Studio dated 2027-07-03; the other
                    stages of the same material receipt are dated 2025-07-03.
                    The year is a slip. The picking, its moves and its lines
                    take the date its siblings have.
  the broken views  Studio views that were broken before the store went and
                    would stay broken after everything else is clean: a view
                    on a model that no longer exists is removed; a view whose
                    button names an action that no longer exists loses that
                    button and nothing else.

Idempotent: each is checked before it is done.
"""
import os
import re
from datetime import datetime, time

from lxml import etree

WRITE = os.environ.get('SSC_WRITE') == '1'
CUTOVER = datetime(2026, 5, 7, 12)
# Studio held the same gloves twice at RA-Ajman, under two serial numbers:
# "Blue dotts gloves" 119 (carried with the balance) and "BLUE DOTTED GLOVES"
# 13 (the line naming no product). One product, one shelf: 132.
GLOVES = [("SSC-G+1 Arjan", 38.0), ("RA-Ajman - Main", 132.0)]

env = env(context=dict(env.context, lang='en_US', active_test=False,   # noqa: F821
                       tracking_disable=True, mail_notrack=True))
cr = env.cr
Product = env['product.template'].sudo()
Location = env['stock.location'].sudo()
Quant = env['stock.quant'].sudo()
Picking = env['stock.picking'].sudo()
View = env['ir.ui.view'].sudo()

print("\n== the gloves")
# The product exists, spelt "Blue dotts gloves"; that is the one the store
# line meant, and the one the balance goes on. A "BLUE DOTTED GLOVES" made
# by an earlier run of this tool is emptied and archived.
product = Product.search([('name', '=ilike', 'blue dott%gloves'), ('name', 'not ilike', 'dotted')],
                         limit=1) or Product.search([('name', 'ilike', 'dott'), ('name', 'ilike', 'glove')], limit=1)
if product:
    print("  product: %s (%s)" % (product.name, product.categ_id.name))
    if not product.is_storable and WRITE:
        product.is_storable = True
else:
    category = env.ref('product.product_category_all')
    print("  product to make: BLUE DOTTED GLOVES")
    if WRITE:
        product = Product.create({'name': "BLUE DOTTED GLOVES", 'type': 'consu',
                                  'is_storable': True, 'categ_id': category.id})
twin = Product.search([('name', '=', 'BLUE DOTTED GLOVES'), ('id', '!=', product.id if product else 0)], limit=1)
if twin:
    held = Quant.search([('product_id.product_tmpl_id', '=', twin.id), ('location_id.usage', '=', 'internal'),
                         ('quantity', '!=', 0)])
    print("  twin %s made earlier: %s quant(s) to empty, then archived" % (twin.name, len(held)))
    if WRITE:
        for quant in held:
            quant.with_context(inventory_mode=True).write({'inventory_quantity': 0})
            quant.with_context(inventory_name="Studio store balance carried (%s)" % quant.location_id.name[:40])                 ._apply_inventory(date=CUTOVER)
        twin.active = False
for prefix, quantity in GLOVES:
    location = Location.search([('ssc_studio_ref_id', '!=', False), ('name', 'ilike', prefix)], limit=1)
    if not location:
        print("  ! no store location named %s" % prefix)
        continue
    on_hand = sum(Quant.search([('product_id.product_tmpl_id', '=', product.id),
                                ('location_id', '=', location.id)]).mapped('quantity')) if product else 0.0
    print("  %-45s has %.0f, Studio said %.0f%s" % (location.name[:45], on_hand, quantity,
                                                     "" if abs(on_hand - quantity) < 0.01 else " -> adjust"))
    if WRITE and product and abs(on_hand - quantity) >= 0.01:
        variant = product.product_variant_id
        quant = Quant.with_context(inventory_mode=True)
        existing = quant.search([('product_id', '=', variant.id), ('location_id', '=', location.id)], limit=1)
        if not existing:
            existing = quant.create({'product_id': variant.id, 'location_id': location.id,
                                     'company_id': location.company_id.id})
        existing.write({'inventory_quantity': quantity})
        existing.with_context(inventory_name="Studio store balance carried (%s)" % location.name[:40])\
                ._apply_inventory(date=CUTOVER)

print("\n== the receipt dated 2027")
for picking in Picking.search([('ssc_studio_source', '!=', False), ('date_done', '>', '2026-12-31')]):
    siblings = Picking.search([('origin', '=', picking.origin), ('id', '!=', picking.id),
                               ('state', '=', 'done'), ('date_done', '<=', '2026-12-31')],
                              order='date_done desc', limit=1)
    if not siblings:
        print("  %s %s: no sibling to take the date from; left" % (picking.name, picking.date_done))
        continue
    when = datetime.combine(siblings.date_done.date(), time(hour=12))
    print("  %s %s -> %s (as %s)" % (picking.name, picking.date_done.date(), when.date(), siblings.name))
    if WRITE:
        picking.move_ids.write({'date': when})
        picking.move_line_ids.write({'date': when})
        picking.write({'date_done': when, 'scheduled_date': when})

print("\n== the broken views")
studio_views = View.search([('name', 'ilike', 'Odoo Studio:')])
gone_models = studio_views.filtered(lambda v: v.model and v.model not in env)
for view in gone_models:
    print("  view %-6s %-32s model is gone -> remove" % (view.id, view.model))
if WRITE and gone_models:
    gone_models.unlink()
dead_button = re.compile(r"Action (\S+) \(id: \d+\) does not exist for button")
for view in studio_views - gone_models:
    try:
        view._check_xml()
        continue
    except Exception as exc:                                            # noqa: BLE001
        found = dead_button.search(str(exc))
    if not found:
        continue
    name = found.group(1)
    print("  view %-6s %-32s button %s names a dead action -> remove the button" % (view.id, view.model, name))
    if WRITE:
        arch = etree.fromstring(view.arch_db)
        for node in arch.xpath("//button[@name='%s']" % name):
            node.getparent().remove(node)
        view.arch_db = etree.tostring(arch, encoding='unicode')
        try:
            view._check_xml()
        except Exception as exc:                                        # noqa: BLE001
            print("      still broken: %s" % ' '.join(str(exc).split())[:120])

if WRITE:
    cr.commit()
    print("\nwritten")
else:
    print("\nNothing was written. SSC_WRITE=1 does it.")
