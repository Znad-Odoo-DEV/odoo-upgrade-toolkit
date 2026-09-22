"""The files on Studio's approved material requests, onto the requests they mirror.

    odoo-bin shell --no-http --shell-interface=python < tools/migrate_studio_mr_attachments.py
    SSC_WRITE=1     actually write

x_approved_mr is Studio's mirror of an approved material request: one row per
request, holding the vendor's delivery note and the bank's swift copy as
binary fields, and a list of further files (x_studio_attachments_list). The
bill shows those files through related fields on account.move; when
x_approved_mr goes, the related fields go with it, and the files with them.

Every file on the mirror, its own binaries and its list's, is copied onto
the chatter of the ssc.request it stands for - the row copied, res_field
cleared, the origin in the description so a second run adds nothing.

Which request a mirror stands for is found three ways, tried in order,
because the database decides which are left: the reference column
(x_studio_mr_reference = the x_all_requests id the request carries as
studio_ref_id), gone on a database where the Requests app already went; the
documents that name both the mirror and the request (order, bill, payment);
and the mirror's own name, which is the request's number. A mirror none of
them place is listed, with its files.
"""
import os

WRITE = os.environ.get('SSC_WRITE') == '1'

env = env(context=dict(env.context, lang='en_US', active_test=False,   # noqa: F821
                       tracking_disable=True, mail_notrack=True))
cr = env.cr
Attachment = env['ir.attachment'].sudo()
Request = env['ssc.request'].sudo()
MR = env.get('x_approved_mr')
if MR is None:
    print("x_approved_mr is not on this database; nothing to carry.")
    raise SystemExit()
MR = MR.sudo()

requests = {r.studio_ref_id: r for r in Request.search([('studio_ref_id', '!=', False)])}
by_name = {}
for r in Request.search([]):
    for key in (r.name, getattr(r, 'reference', None)):
        if key:
            by_name.setdefault(key.strip().upper(), r)
cr.execute("""SELECT 1 FROM information_schema.columns
               WHERE table_name = 'x_approved_mr' AND column_name = 'x_studio_mr_reference'""")
has_reference = bool(cr.fetchone())
cr.execute("SELECT id, x_name%s FROM x_approved_mr" % (", x_studio_mr_reference" if has_reference else ""))
# x_name is a translated column and comes back as {"en_US": ...}, not text
mirror_rows = {row[0]: ((row[1] or {}).get('en_US') if isinstance(row[1], dict) else row[1],
                        row[2] if has_reference else None) for row in cr.fetchall()}
via_documents = {}
for table, column in (('purchase_order', 'x_studio_mr_link'), ('account_move', 'x_studio_approved_mr'),
                      ('account_payment', 'x_studio_approved_mr')):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    if not cr.fetchone():
        continue
    cr.execute("SELECT %s, ssc_request_id FROM %s WHERE %s IS NOT NULL AND ssc_request_id IS NOT NULL"
               % (column, table, column))
    for mirror_id, request_id in cr.fetchall():
        via_documents.setdefault(mirror_id, request_id)
how = {}


def request_of(mirror_id):
    name, reference = mirror_rows.get(mirror_id, (None, None))
    if reference and reference in requests:
        how['reference'] = how.get('reference', 0) + 1
        return requests[reference]
    if mirror_id in via_documents:
        how['documents'] = how.get('documents', 0) + 1
        return Request.browse(via_documents[mirror_id])
    found = by_name.get((name or '').strip().upper())
    if found:
        how['name'] = how.get('name', 0) + 1
        return found
    return None


def file_is_really_there(attachment):
    if not attachment.store_fname:
        return bool(attachment.db_datas)
    try:
        return os.path.exists(attachment._full_path(attachment.store_fname))
    except Exception:
        return False


# the models holding files: the mirror, and every line model hanging off it
models = {'x_approved_mr': None}
for name, field in MR._fields.items():
    if field.type == 'one2many' and field.comodel_name.startswith('x_approved_mr'):
        models[field.comodel_name] = field.inverse_name

jobs, unmatched, lost = [], [], []
for model, inverse in models.items():
    Model = env[model].sudo()
    per_field = {}
    for attachment in Attachment.search([('res_model', '=', model), ('res_field', '!=', False)]):
        row = Model.browse(attachment.res_id).exists()
        if not row:
            continue
        per_field[attachment.res_field] = per_field.get(attachment.res_field, 0) + 1
        mirror = row if model == 'x_approved_mr' else row[inverse]
        if not mirror:
            unmatched.append((model, row.id, attachment.name, "line with no request"))
            continue
        request = request_of(mirror.id)
        if not request:
            unmatched.append((model, row.id, attachment.name,
                              "mirror %s matches no request" % mirror_rows.get(mirror.id, ('?',))[0]))
            continue
        if not file_is_really_there(attachment):
            lost.append((model, row.id, attachment.name))
            continue
        jobs.append((model, row, attachment, request))
    for field, count in sorted(per_field.items()):
        print("  %-30s %-40s %s file(s)" % (model, field, count))

print("")
print("  %s file(s) go onto %s request(s); matched by %s"
      % (len(jobs), len(set(j[3].id for j in jobs)), how))
print("  %s file(s) have no request to go to:" % len(unmatched))
for model, row_id, name, why in unmatched[:15]:
    print("      %-24s %-6s %-30s %s" % (model, row_id, (name or '')[:30], why))
print("  %s file(s) are missing from the filestore" % len(lost))

if not WRITE:
    print("")
    print("Nothing was written. SSC_WRITE=1 does it.")
    raise SystemExit()

made = already = 0
for model, row, attachment, request in jobs:
    origin = "studio:%s:%s:%s" % (model, row.id, attachment.res_field)
    if Attachment.search_count([('description', '=', origin), ('res_model', '=', 'ssc.request'),
                                ('res_id', '=', request.id)]):
        already += 1
        continue
    attachment.copy({'name': attachment.name, 'res_model': 'ssc.request', 'res_id': request.id,
                     'res_field': False, 'description': origin})
    made += 1
cr.commit()
print("")
print("  %s attachment(s) made on the requests, %s already there" % (made, already))
