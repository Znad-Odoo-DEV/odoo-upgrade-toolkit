"""The store's history, transaction by transaction, as native transfers.

    odoo-bin shell --no-http --shell-interface=python < tools/import_studio_store_moves.py
    SSC_WRITE=1        actually write
    SSC_RECONCILE=1    after the replay, adjust each store to Studio's balance
    SSC_LIMIT=200      stop after this many transactions (a first look)
    SSC_OUT=~/store_moves.md

Run it after tools/import_studio_store.py, which makes the locations.

Studio recorded 5,546 movements in one model with one date (x_studio_date_2)
and one status (status1 pending, status2 done, "Confirm Received" done and
acknowledged). They become:

    Stock       item and quantity on the header, into the store
                -> a receipt: Partners/Vendors -> the store, in the warehouse's
                   receipt operation type
    Consumed    item and quantity on the header, out of the store, for a job
                -> an internal transfer: the store -> "Site Consumption / <job>",
                   a virtual production location per project, so what a job
                   consumed is readable per job after Studio is gone
    Transfer    lines, from one store to another
                -> an internal transfer between the two stores
    (no type)   72 old receipts with lines (x_studio_items_received)
                -> receipts, like Stock

Done ones are validated and then dated as Studio dated them; pending ones are
confirmed and left waiting. Every picking keeps the Studio id it came from, so
a second run adds nothing.

THE PURCHASE RECEIPTS

The transactions are not the whole history. Studio's store balance was also
fed - mostly fed - by the material received against purchase orders, which is
another model: x_items_ordered, one row per item ordered, credited to the
store by the automation "Send to store /done" when the row was submitted
(single-stage, x_studio_quantity_2) or when each stage line was marked done
(multi-stage, x_items_ordered_line_09115). The automation credited the store
of the row's company and project, not the one the row names, so that is the
store used here. And what was returned to the vendor ("returned items") was
taken out again. Those become:

    a submitted single-stage row    -> a done receipt, Vendors -> the store
    a done stage line               -> a done receipt, one per stage, its date
    a row or stage not yet received -> a receipt left ready
    a returned quantity             -> a done delivery, the store -> Vendors

The vendor is on the receipt, the MR reference is its source document, and
each keeps the Studio row it came from in ssc_studio_source.

THE BALANCE

Replaying a history from zero yields Studio's balance only if the history is
whole. Where a store had stock before the application began, or a figure was
corrected by hand, it will not. So the last section compares what the replay
left on hand with what each Studio store says it holds, line by line, and -
with SSC_RECONCILE=1 - writes the difference as one inventory adjustment per
line, today, and names every one. Nothing is silently forced to agree.

Quantities only: every category values stock periodically, so no move here
posts an accounting entry. Negative stock along the way is allowed - it is what
an incomplete history looks like, and the reconciliation closes it.
"""
import os
import re
from datetime import datetime, time, timedelta

from odoo.exceptions import UserError
from odoo.tools import float_compare

WRITE = os.environ.get('SSC_WRITE') == '1'
RECONCILE = os.environ.get('SSC_RECONCILE') == '1'
LIMIT = int(os.environ.get('SSC_LIMIT') or 0)
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/store_moves.md')

TX = 'x_transaction'
STORE_LINES = 'x_studio_one2many_field_113_1if9packl'
DONE_STATES = ('status2', 'Confirm Received')

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
    if not record or name not in record._fields:
        return default
    value = record[name]
    return default if value is False or value is None else value


env = env(context=dict(env.context, lang='en_US', active_test=False,   # noqa: F821
                       tracking_disable=True, mail_create_nolog=True,
                       mail_notrack=True))
cr = env.cr

Tx = env.get(TX)
if Tx is None:
    print("%s is not on this database; nothing to carry." % TX)
    raise SystemExit()
Tx = Tx.sudo()
Product = env['product.template'].sudo()
Location = env['stock.location'].sudo()
Picking = env['stock.picking'].sudo()
Move = env['stock.move'].sudo()
Quant = env['stock.quant'].sudo()
Project = env['project.project'].sudo()

# ---------------------------------------------------------------- lookups
by_name, by_code = {}, {}
for product in Product.search([]):
    by_name.setdefault(norm(product.name), product)
    if product.default_code:
        by_code.setdefault(norm(product.default_code), product)


def product_of(record, *fields):
    """A product named by any of these fields, then by name, then by code."""
    for name in fields:
        value = get(record, name)
        if value and value._name == 'product.template':
            return value
        if value and value._name == 'product.product':
            return value.product_tmpl_id
        if value and hasattr(value, '_name') and 'x_studio_item_name' in value._fields:
            inner = get(value, 'x_studio_item_name')
            if inner and inner._name == 'product.template':
                return inner
    found = by_name.get(norm(get(record, 'x_name', '')))
    if found:
        return found
    for name in ('x_studio_item_sn', 'x_studio_item_serial_no'):
        found = by_code.get(norm(get(record, name, '')))
        if found:
            return found
    return None


store_locations = {loc.ssc_studio_ref_id: loc
                   for loc in Location.search([('ssc_studio_ref_id', '!=', False)])}
if not store_locations:
    print("No store location carries a Studio id. Run tools/import_studio_store.py first.")
    raise SystemExit()

suppliers = env.ref('stock.stock_location_suppliers')
virtual_root = env.ref('stock.stock_location_locations_virtual')
# A transfer between two companies' stores cannot be one picking: Odoo refuses
# a document that belongs to one company and reads a location of another. It
# is what the companies actually do - goods leave SSC, goods arrive at Royal
# Arrow - so it is two pickings through the transit location that belongs to
# nobody, each in its own company, on the same day.
transit = env.ref('stock.stock_location_inter_company', raise_if_not_found=False)
if not transit:
    transit = Location.search([('usage', '=', 'transit'), ('company_id', '=', False)], limit=1)


def consumption_root():
    found = Location.search([('name', '=', 'Site Consumption'),
                             ('location_id', '=', virtual_root.id)], limit=1)
    if found or not WRITE:
        return found
    return Location.create({'name': 'Site Consumption', 'location_id': virtual_root.id,
                            'usage': 'view', 'company_id': False})


_consumption = {}


def consumption_location(project):
    """The virtual location a job's consumption goes to - one per project."""
    key = project.id if project else 0
    if key in _consumption:
        return _consumption[key]
    root = consumption_root()
    name = project.display_name[:60] if project else 'No project'
    found = root and Location.search([('location_id', '=', root.id),
                                      ('ssc_project_id', '=', project.id if project else False),
                                      ('name', '=', name)], limit=1)
    if not found and WRITE and root:
        found = Location.create({'name': name, 'location_id': root.id, 'usage': 'production',
                                 'company_id': False,
                                 'ssc_project_id': project.id if project else False})
    _consumption[key] = found or None
    return _consumption[key]


def as_datetime(day):
    return datetime.combine(day, time(hour=12)) if day else False


# ------------------------------------------------------------ the plan
title("what Studio holds")
rows = Tx.search([], order='x_studio_date_2, id')
kinds = {}
for row in rows:
    kind = get(row, 'x_studio_type_of_transaction') or 'receipt-with-lines'
    state = 'done' if get(row, 'x_studio_selection_field_64t_1ipgtrlhm') in DONE_STATES else 'pending'
    kinds.setdefault((kind, state), 0)
    kinds[(kind, state)] += 1
say("  %s transaction(s), %s to %s" % (len(rows), rows[:1].x_studio_date_2, rows[-1:].x_studio_date_2))
for (kind, state), count in sorted(kinds.items()):
    say("  %-22s %-8s %5s" % (kind, state, count))
say("  %s already carried" % Picking.search_count([('ssc_studio_ref_id', '!=', False)]))


def lines_of(row):
    """(product, quantity, name) for each thing the transaction moves."""
    kind = get(row, 'x_studio_type_of_transaction')
    out = []
    if kind == 'Transfer':
        for line in get(row, 'x_studio_transfering_details') or []:
            out.append((product_of(line, 'x_studio_item', 'x_studio_product', 'x_studio_item_name'),
                        get(line, 'x_studio_quantity', 0.0) or get(line, 'x_studio_quantity_2', 0.0) or 0.0,
                        get(line, 'x_name', '')))
    elif not kind:
        for line in get(row, 'x_studio_items_received') or []:
            out.append((product_of(line, 'x_studio_item_name', 'x_studio_item', 'x_studio_product'),
                        get(line, 'x_studio_quantity', 0.0) or 0.0,
                        get(line, 'x_name', '')))
    else:
        out.append((product_of(row, 'x_studio_item_1', 'x_studio_item'),
                    get(row, 'x_studio_quantity', 0.0) or 0.0,
                    get(row, 'x_name', '')))
    return out


def route_of(row):
    """The legs a transaction becomes: [(source, destination, picking type, project)],
    or ([], reason) when it cannot be routed."""
    kind = get(row, 'x_studio_type_of_transaction')
    store = get(row, 'x_studio_store')
    project = get(row, 'x_studio_project')
    dest_store = store_locations.get(store.id) if store else None
    if kind == 'Transfer':
        from_store = get(row, 'x_studio_from_store')
        source = store_locations.get(from_store.id) if from_store else None
        if not source or not dest_store:
            return [], "store %s or %s has no location" % (
                from_store and from_store.x_name, store and store.x_name)
        job = project or dest_store.ssc_project_id
        if source.company_id == dest_store.company_id:
            return [(source, dest_store, dest_store.warehouse_id.int_type_id, job)], None
        if not transit:
            return [], "no company-less transit location for a cross-company transfer"
        return [(source, transit, source.warehouse_id.int_type_id, job),
                (transit, dest_store, dest_store.warehouse_id.int_type_id, job)], None
    if kind == 'Consumed':
        if not dest_store:
            return [], "store %s has no location" % (store and store.x_name)
        job = project or dest_store.ssc_project_id
        return [(dest_store, consumption_location(job), dest_store.warehouse_id.int_type_id, job)], None
    # Stock, and the 72 typeless receipts
    if not dest_store:
        return [], "store %s has no location" % (store and store.x_name)
    return [(suppliers, dest_store, dest_store.warehouse_id.in_type_id,
             project or dest_store.ssc_project_id)], None


title("what would be made")
plan, refused, empty = [], [], []
for row in rows:
    legs, why = route_of(row)
    if why:
        refused.append((row, why))
        continue
    moves = [(p, q, n) for p, q, n in lines_of(row) if p and q > 0]
    missing = [(n, q) for p, q, n in lines_of(row) if not p and q > 0]
    if not moves:
        empty.append((row, missing))
        continue
    plan.append((row, legs, moves, missing))
two_legged = sum(1 for item in plan if len(item[1]) == 2)
say("  %s transaction(s) become a picking; %s of them cross companies and become two"
    % (len(plan), two_legged))
left_by_kind = {}
for row, missing in empty:
    key = (get(row, 'x_studio_type_of_transaction') or '(none)',
           'no product' if missing else 'no quantity or no lines')
    left_by_kind[key] = left_by_kind.get(key, 0) + 1
say("  %s move nothing and are left: %s" % (len(empty), sorted(left_by_kind.items())))
say("  %s cannot be routed and are left" % len(refused))
for row, missing in empty[:12]:
    say("      %-8s %-10s %-12s %s" % (row.id, get(row, 'x_studio_type_of_transaction') or '(none)',
                                        get(row, 'x_studio_date_2'), missing[:3]))
for row, why in refused[:12]:
    say("      %-8s %s" % (row.id, why))
partial = sum(1 for item in plan if item[3])
if partial:
    say("  %s of the pickings have a line that names no product; the line is dropped and "
        "the rest is carried" % partial)

# ---------------------------------------------- the purchase receipts
title("what the purchase receipts would make")
Item = env.get('x_items_ordered')
Item = Item.sudo() if Item is not None else None
StoreModel = env['x_inventory_stores_pro'].sudo()
_store_of = {}


def store_credited(item):
    """The store Studio credited: the company's store on the item's project,
    as the automation searched it; the store the item names otherwise."""
    company = get(item, 'x_studio_company_id')
    project = get(item, 'x_studio_project')
    key = (company.id if company else 0, project.id if project else 0)
    if key not in _store_of:
        found = StoreModel
        if company and project:
            found = StoreModel.search([('x_studio_company', '=', company.id),
                                       ('x_studio_project_1', '=', project.id)], limit=1)
        _store_of[key] = found
    return _store_of[key] or get(item, 'x_studio_store')


# (source key, item, product, quantity, done, day, location, direction)
receipts = []
left_receipts = {}
if Item is None:
    say("  x_items_ordered is not on this database; no purchase receipts to carry")
elif 'ssc_studio_source' not in Picking._fields:
    say("  ! stock.picking has no ssc_studio_source: ssc_store must be 1.2.0 before the")
    say("    purchase receipts can be carried. Nothing of them is planned.")
else:
    for item in Item.search([], order='x_studio_date, id'):
        if not get(item, 'x_studio_store'):
            # Studio's rule: a row naming no store credited nothing
            left_receipts['no store'] = left_receipts.get('no store', 0) + 1
            continue
        stage = get(item, 'x_studio_receipt_stages')
        if not stage:
            left_receipts['no receipt stage'] = left_receipts.get('no receipt stage', 0) + 1
            continue
        product = product_of(item, 'x_studio_item_name', 'x_studio_product')
        if not product:
            left_receipts['no product'] = left_receipts.get('no product', 0) + 1
            continue
        target = store_credited(item)
        location = store_locations.get(target.id) if target else None
        if not location:
            left_receipts['store has no location'] = left_receipts.get('store has no location', 0) + 1
            continue
        day = get(item, 'x_studio_date') or item.create_date.date()
        if stage == 'Single-stage receipt':
            done = bool(get(item, 'x_studio_submit'))
            quantity = (get(item, 'x_studio_quantity_2', 0.0) if done
                        else get(item, 'x_studio_quantity', 0.0)) or 0.0
            if quantity > 0:
                receipts.append(('x_items_ordered,%s' % item.id, item, product, quantity,
                                 done, day, location, 'in'))
        else:
            for line in get(item, 'x_studio_multi_stage_receipt') or []:
                quantity = get(line, 'x_studio_quantity', 0.0) or 0.0
                if quantity > 0:
                    receipts.append(('x_items_ordered_line_09115,%s' % line.id, item, product,
                                     quantity, bool(get(line, 'x_studio_done')),
                                     get(line, 'x_studio_date') or day, location, 'in'))
        returned = get(item, 'x_studio_returned_quantity', 0.0) or 0.0
        if get(item, 'x_studio_returned') and returned > 0:
            receipts.append(('x_items_ordered,%s,return' % item.id, item, product, returned,
                             True, item.write_date.date(), location, 'out'))
    say("  %s receipt(s) from %s ordered item(s): %s done, %s left ready, %s return(s)"
        % (len(receipts), len(set(r[1].id for r in receipts)),
           sum(1 for r in receipts if r[4] and r[7] == 'in'),
           sum(1 for r in receipts if not r[4]),
           sum(1 for r in receipts if r[7] == 'out')))
    say("  received %.0f, returned %.0f"
        % (sum(r[3] for r in receipts if r[4] and r[7] == 'in'),
           sum(r[3] for r in receipts if r[7] == 'out')))
    say("  ordered items that credited no store in Studio and make nothing here: %s"
        % sorted(left_receipts.items()))
    say("  already carried: %s" % Picking.search_count([('ssc_studio_source', '!=', False)]))

if not WRITE:
    title("nothing was written")
    say("  Run again with SSC_WRITE=1. Add SSC_LIMIT=200 for a first look, and")
    say("  SSC_RECONCILE=1 only on the full run, once the replay is read.")
    finish()

# ------------------------------------------------------------- writing
title("writing")
carried = Picking.search([('ssc_studio_ref_id', '!=', False)]).mapped('ssc_studio_ref_id')
carried = set(carried)
made = validated = 0
left_open = []
storable = set()
for index, (row, legs, moves, missing) in enumerate(plan):
    if LIMIT and made >= LIMIT:
        break
    if row.id in carried:
        continue
    if any(not picking_type for source, dest, picking_type, project in legs):
        refused.append((row, "the warehouse has no operation type"))
        continue
    when = as_datetime(get(row, 'x_studio_date_2'))
    products = Product.browse([p.id for p, q, n in moves])
    turned = products.filtered(lambda p: not p.is_storable)
    if turned:
        turned.write({'is_storable': True})
    done = get(row, 'x_studio_selection_field_64t_1ipgtrlhm') in DONE_STATES
    note = get(row, 'x_studio_remarks') or get(row, 'x_studio_remarks_1')
    for source, dest, picking_type, project in legs:
        # In the company of the operation type, all the way down: a move made
        # from the shell takes the shell's company otherwise, and Royal
        # Arrow's transfer arrives carrying SSC's moves.
        company = picking_type.company_id
        picking = Picking.with_company(company).create({
            'picking_type_id': picking_type.id,
            'location_id': source.id,
            'location_dest_id': dest.id,
            'origin': (get(row, 'x_name') or 'Studio %s' % row.id)[:64],
            'scheduled_date': when,
            'ssc_project_id': project.id if project else False,
            'ssc_studio_ref_id': row.id,
            'company_id': picking_type.company_id.id,
            'move_ids': [(0, 0, {
                'product_id': product.product_variant_id.id,
                'product_uom_qty': quantity,
                'product_uom': product.uom_id.id,
                'location_id': source.id,
                'location_dest_id': dest.id,
                'date': when,
                'company_id': company.id,
            }) for product, quantity, name in moves],
        })
        if note:
            picking.note = note
        picking.action_confirm()
        if done:
            # One transfer Odoo will not validate must not stop five thousand.
            # A quantity below the unit's rounding (0.5 of a "Unit") reads as
            # zero and is refused; the picking is left ready, named, with the
            # reason on it, for a person to settle.
            try:
                with cr.savepoint():
                    for move in picking.move_ids:
                        move.quantity = move.product_uom_qty
                        move.picked = True
                    picking.with_context(skip_backorder=True, skip_sms=True,
                                         skip_immediate=True).button_validate()
                    if picking.state != 'done':
                        raise UserError("stayed %s" % picking.state)
                picking.move_ids.write({'date': when})
                picking.move_line_ids.write({'date': when})
                picking.write({'date_done': when})
                validated += 1
            except Exception as exc:
                reason = ' '.join(str(exc).split())[:160]
                left_open.append((picking.name, row.id, reason))
                picking.message_post(body="Carried from Studio transaction %s but not validated: %s"
                                     % (row.id, reason), message_type='comment',
                                     subtype_xmlid='mail.mt_note')
    made += 1
    if made % 200 == 0:
        cr.commit()
        say("  %s / %s" % (made, len(plan)))
cr.commit()
say("  %s picking(s) made, %s of them done" % (made, validated))
if left_open:
    say("  %s should have been done and were left ready, with the reason in their chatter:"
        % len(left_open))
    for name, ref, reason in left_open[:30]:
        say("      %-14s studio %-6s %s" % (name, ref, reason[:90]))
if LIMIT:
    say("  stopped at SSC_LIMIT=%s" % LIMIT)

# ------------------------------------------------ the purchase receipts
title("writing the purchase receipts")
carried_sources = set(Picking.search([('ssc_studio_source', '!=', False)]).mapped('ssc_studio_source'))
made_receipts = validated_receipts = 0
left_open_receipts = []
for key, item, product, quantity, done, day, location, direction in receipts:
    if LIMIT and made_receipts >= LIMIT:
        break
    if key in carried_sources:
        continue
    warehouse = location.warehouse_id
    picking_type = warehouse.in_type_id if direction == 'in' else warehouse.out_type_id
    if not picking_type:
        left_open_receipts.append(('-', key, "the warehouse has no operation type"))
        continue
    source, dest = (suppliers, location) if direction == 'in' else (location, suppliers)
    if not product.is_storable:
        product.write({'is_storable': True})
    when = as_datetime(day)
    project = get(item, 'x_studio_project') or location.ssc_project_id
    vendor = get(item, 'x_studio_vendor')
    receipt = get(item, 'x_studio_material_receipt_ref')
    origin = (get(item, 'x_studio_mr_reference') or get(item, 'x_studio_mr_reference_1')
              or (receipt and get(receipt, 'x_name')) or get(item, 'x_name') or key)
    company = picking_type.company_id
    picking = Picking.with_company(company).create({
        'picking_type_id': picking_type.id,
        'location_id': source.id,
        'location_dest_id': dest.id,
        'partner_id': vendor.id if vendor else False,
        'origin': str(origin)[:64],
        'scheduled_date': when,
        'ssc_project_id': project.id if project else False,
        'ssc_studio_source': key,
        'company_id': company.id,
        'move_ids': [(0, 0, {
            'product_id': product.product_variant_id.id,
            'product_uom_qty': quantity,
            'product_uom': product.uom_id.id,
            'location_id': source.id,
            'location_dest_id': dest.id,
            'date': when,
            'company_id': company.id,
        })],
    })
    label = get(item, 'x_name') or product.name
    if direction == 'out':
        picking.note = "Returned to the vendor: %s" % label
    picking.action_confirm()
    if done:
        try:
            with cr.savepoint():
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                    move.picked = True
                picking.with_context(skip_backorder=True, skip_sms=True,
                                     skip_immediate=True).button_validate()
                if picking.state != 'done':
                    raise UserError("stayed %s" % picking.state)
            picking.move_ids.write({'date': when})
            picking.move_line_ids.write({'date': when})
            picking.write({'date_done': when})
            validated_receipts += 1
        except Exception as exc:
            reason = ' '.join(str(exc).split())[:160]
            left_open_receipts.append((picking.name, key, reason))
            picking.message_post(body="Carried from Studio %s but not validated: %s" % (key, reason),
                                 message_type='comment', subtype_xmlid='mail.mt_note')
    made_receipts += 1
    if made_receipts % 200 == 0:
        cr.commit()
        say("  %s / %s" % (made_receipts, len(receipts)))
cr.commit()
say("  %s receipt(s) made, %s of them done" % (made_receipts, validated_receipts))
if left_open_receipts:
    say("  %s should have been done and were left ready, with the reason in their chatter:"
        % len(left_open_receipts))
    for name, key, reason in left_open_receipts[:30]:
        say("      %-14s %-36s %s" % (name, key, reason[:90]))

# --------------------------------------------------------- the balance
title("the balance, replay against Studio")
Store = env['x_inventory_stores_pro'].sudo()
differences = []
for store in Store.search([]):
    location = store_locations.get(store.id)
    if not location:
        continue
    said = {}
    for line in store[STORE_LINES]:
        product = product_of(line, 'x_studio_item', 'x_studio_product')
        if product:
            said[product.id] = said.get(product.id, 0.0) + (get(line, 'x_studio_available_quantity', 0.0) or 0.0)
    on_hand = {}
    for quant in Quant.search([('location_id', '=', location.id)]):
        on_hand[quant.product_id.product_tmpl_id.id] = on_hand.get(
            quant.product_id.product_tmpl_id.id, 0.0) + quant.quantity
    for product_id in set(said) | set(on_hand):
        studio_qty = said.get(product_id, 0.0)
        replayed = on_hand.get(product_id, 0.0)
        product = Product.browse(product_id)
        # at the unit's own rounding: 35.45 and 35.449999 are the same bar
        if float_compare(studio_qty, replayed, precision_rounding=product.uom_id.rounding or 0.01):
            differences.append((location, product, studio_qty, replayed))
say("  %s store/product line(s) differ between the replay and Studio's balance" % len(differences))
say("  %-30s %-34s %10s %10s %10s" % ("store", "product", "Studio", "replayed", "adjust"))
for location, product, studio_qty, replayed in sorted(differences, key=lambda d: -abs(d[2] - d[3]))[:40]:
    say("  %-30s %-34s %10.2f %10.2f %10.2f" % (location.name[:30], (product.name or '')[:34],
                                                 studio_qty, replayed, studio_qty - replayed))
if len(differences) > 40:
    say("  ... and %s more" % (len(differences) - 40))

if RECONCILE and not LIMIT:
    # The adjustment is dated the day after the last thing Studio recorded,
    # not today: from that day on the store holds what Studio said, and a
    # stock report for June does not show the months between as negative.
    # Each move is named for what it is, so it reads in the ledger as a
    # carried balance and not as somebody's count.
    # One stage line in Studio is dated 2027; a date after today is a typo,
    # not the last movement, and does not set the cutover.
    today = datetime.now().date()
    last_day = max([d for d in rows.mapped('x_studio_date_2') if d and d <= today]
                   + [r[5] for r in receipts if r[5] and r[5] <= today])
    cutover = as_datetime(last_day + timedelta(days=1))
    # A carried balance written on an earlier run with a wrong cutover is
    # re-dated, moves and lines both, so the ledger reads one date for it.
    stray = Move.search([('is_inventory', '=', True),
                         ('reference', 'ilike', 'Studio store balance carried'),
                         ('date', '!=', cutover)])
    if stray:
        stray.write({'date': cutover})
        stray.move_line_ids.write({'date': cutover})
        say("  %s carried-balance move(s) re-dated to %s" % (len(stray), cutover.date()))
    adjusted = 0
    for location, product, studio_qty, replayed in differences:
        variant = product.product_variant_id
        if not variant:
            continue
        quant = Quant.with_context(inventory_mode=True)
        existing = quant.search([('product_id', '=', variant.id), ('location_id', '=', location.id),
                                 ('lot_id', '=', False), ('package_id', '=', False),
                                 ('owner_id', '=', False)], limit=1)
        if not existing:
            existing = quant.create({'product_id': variant.id, 'location_id': location.id,
                                     'company_id': location.company_id.id})
        existing.write({'inventory_quantity': studio_qty})
        existing.with_context(inventory_name="Studio store balance carried (%s)" % location.name[:40])\
                ._apply_inventory(date=cutover)
        adjusted += 1
        if adjusted % 300 == 0:
            cr.commit()
    cr.commit()
    say("  %s line(s) adjusted to Studio's balance, dated %s" % (adjusted, cutover.date()))
elif differences:
    say("  Not adjusted. Read the list; then SSC_RECONCILE=1 sets each line to Studio's figure.")

title("done")
finish()
