"""The delivery notes and photos on the Studio store records, onto the transfers.

    odoo-bin shell --no-http --shell-interface=python \\
        < tools/migrate_studio_store_attachments.py
    SSC_WRITE=1     actually write
    SSC_OUT=~/store_attachments.md

Run it after tools/import_studio_store_moves.py, which makes the transfers.

Four Studio models hold files the site will still ask for - the delivery
note behind a receipt, the photo behind a transfer:

    x_transaction               the chatter's own files, and x_studio_attachment
                                -> the picking(s) carrying ssc_studio_ref_id = the row
    x_items_ordered_line_09115  x_studio_attachment, one per receipt stage
                                -> the picking with ssc_studio_source
                                   "x_items_ordered_line_09115,<id>"
    x_items_ordered             its own binary field
                                -> the picking "x_items_ordered,<id>", or the
                                   pickings of its stages
    x_material_receipt          x_studio_attachment, one document for a whole
                                receipt of several items
                                -> every picking made from an item of that
                                   receipt (the same file on each; the filestore
                                   keeps one copy of the bytes)

Same rules as tools/migrate_studio_attachments.py: the row is copied, not the
bytes; res_field is cleared so the file shows in the chatter; the origin is in
the description and is what a second run looks for; a file missing from the
filestore is listed and not copied; a record with no picking is listed.
"""
import os

WRITE = os.environ.get('SSC_WRITE') == '1'
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/store_attachments.md')

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text):
    say('')
    say('=' * 96)
    say(text)
    say('=' * 96)


def finish():
    with open(OUT, 'w', encoding='utf-8') as handle:
        handle.write("\n".join(report) + "\n")
    print("\nwritten to %s" % OUT)
    raise SystemExit()


env = env(context=dict(env.context, lang='en_US', active_test=False,   # noqa: F821
                       tracking_disable=True, mail_notrack=True))
cr = env.cr
Attachment = env['ir.attachment'].sudo()
Picking = env['stock.picking'].sudo()

if 'ssc_studio_source' not in Picking._fields:
    print("stock.picking has no ssc_studio_source: ssc_store must be 1.2.0.")
    raise SystemExit()


def file_is_really_there(attachment):
    if not attachment.store_fname:
        return bool(attachment.db_datas)
    try:
        return os.path.exists(attachment._full_path(attachment.store_fname))
    except Exception:
        return False


# the pickings, by what they came from
by_ref = {}
for picking in Picking.search([('ssc_studio_ref_id', '!=', False)]):
    by_ref.setdefault(picking.ssc_studio_ref_id, []).append(picking)
by_source = {}
for picking in Picking.search([('ssc_studio_source', '!=', False)]):
    by_source.setdefault(picking.ssc_studio_source, []).append(picking)


def pickings_of_item(item):
    """The pickings an ordered item became: its own, or its stages'."""
    found = list(by_source.get('x_items_ordered,%s' % item.id, []))
    for line in item.x_studio_multi_stage_receipt if 'x_studio_multi_stage_receipt' in item._fields else []:
        found += by_source.get('x_items_ordered_line_09115,%s' % line.id, [])
    return found


# (source model, row, attachment, targets)
jobs = []
no_target = []
lost = []


def plan(model, row, attachments, targets):
    for attachment in attachments:
        if not file_is_really_there(attachment):
            lost.append((model, row.id, attachment.name, attachment.store_fname))
            continue
        if not targets:
            no_target.append((model, row.id, attachment.name))
            continue
        jobs.append((model, row, attachment, targets))


def field_files(model, field):
    """The rows of a model with a file in a binary field, and that file."""
    Model = env.get(model)
    if Model is None or field not in Model._fields:
        return []
    out = []
    for attachment in Attachment.search([('res_model', '=', model), ('res_field', '=', field)]):
        row = Model.sudo().browse(attachment.res_id).exists()
        if row:
            out.append((row, attachment))
    return out


title("what Studio holds")
Tx = env.get('x_transaction')
if Tx is not None:
    chatter = Attachment.search([('res_model', '=', 'x_transaction'), ('res_field', '=', False)])
    say("  x_transaction: %s chatter file(s), %s field file(s)"
        % (len(chatter), Attachment.search_count([('res_model', '=', 'x_transaction'),
                                                   ('res_field', '=', 'x_studio_attachment')])))
    for attachment in chatter:
        row = Tx.sudo().browse(attachment.res_id).exists()
        if row:
            plan('x_transaction', row, attachment, by_ref.get(row.id, []))
    for row, attachment in field_files('x_transaction', 'x_studio_attachment'):
        plan('x_transaction', row, attachment, by_ref.get(row.id, []))

stage_files = field_files('x_items_ordered_line_09115', 'x_studio_attachment')
say("  x_items_ordered_line_09115: %s stage file(s)" % len(stage_files))
for row, attachment in stage_files:
    plan('x_items_ordered_line_09115', row, attachment,
         by_source.get('x_items_ordered_line_09115,%s' % row.id, []))

Item = env.get('x_items_ordered')
if Item is not None:
    binaries = [n for n, f in Item._fields.items() if f.type == 'binary' and n.startswith('x_')]
    for name in binaries:
        files = field_files('x_items_ordered', name)
        if files:
            say("  x_items_ordered.%s: %s file(s)" % (name, len(files)))
        for row, attachment in files:
            plan('x_items_ordered', row, attachment, pickings_of_item(row))

receipt_files = field_files('x_material_receipt', 'x_studio_attachment')
say("  x_material_receipt: %s document(s)" % len(receipt_files))
if Item is not None and receipt_files:
    for row, attachment in receipt_files:
        targets = []
        for item in Item.sudo().search([('x_studio_material_receipt_ref', '=', row.id)]):
            targets += pickings_of_item(item)
        plan('x_material_receipt', row, attachment, targets)

title("what would be made")
say("  %s file(s) go onto %s transfer(s)" % (len(jobs), sum(len(t) for m, r, a, t in jobs)))
say("  %s file(s) belong to a record that became no transfer (left in Studio):" % len(no_target))
for model, row_id, name in no_target[:15]:
    say("      %-28s %-8s %s" % (model, row_id, (name or '')[:50]))
say("  %s file(s) are missing from the filestore and are not copied:" % len(lost))
for model, row_id, name, store in lost[:15]:
    say("      %-28s %-8s %-40s %s" % (model, row_id, (name or '')[:40], store))

if not WRITE:
    title("nothing was written")
    say("  Run again with SSC_WRITE=1.")
    finish()

title("writing")
made = already = 0
for model, row, attachment, targets in jobs:
    origin = "studio:%s:%s:%s" % (model, row.id, attachment.id)
    for target in targets:
        if Attachment.search_count([('description', '=', origin), ('res_model', '=', 'stock.picking'),
                                    ('res_id', '=', target.id)]):
            already += 1
            continue
        attachment.copy({'name': attachment.name, 'res_model': 'stock.picking', 'res_id': target.id,
                         'res_field': False, 'description': origin})
        made += 1
    if (made + already) % 200 == 0:
        cr.commit()
cr.commit()
say("  %s attachment(s) made, %s already there" % (made, already))
title("done")
finish()
