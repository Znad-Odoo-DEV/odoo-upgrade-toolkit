"""Studio's contractor agreements, as purchase agreements; its certificates, told which.

    odoo-bin shell --no-http --shell-interface=python < tools/import_studio_agreements.py
    SSC_WRITE=1     actually write
    SSC_OUT=~/agreements.md

Dry by default, idempotent: every agreement made carries the Studio id it
came from (ssc_studio_ref_id), and a link already set is left alone.

WHAT AN AGREEMENT IS

x_contractor_agreement (64 rows) owns four things: which subcontract, which
project, one purchase order, and where it has got to. Everything else on it
is read through the subcontract. Odoo's own document for that is the
purchase agreement (purchase.requisition, a blanket order) with the orders
raised against it. So each becomes one:

    x_studio_ref_no / x_name         -> reference, and the name
    the vendor of its purchase order -> vendor
    x_studio_date_of_agreement       -> start date
    x_studio_scope_description       -> scope (ssc_scope) and description
    Pending / LPO / On-going / Closed -> draft / confirmed / confirmed / done
    x_studio_project                 -> ssc_project_id
    x_studio_contractor              -> ssc_subcontract_id, through the
                                        subcontract's own studio_ref_id
    the purchase order's lines       -> the agreement's lines (product,
                                        quantity, price), which is the only
                                        place the agreed items are actually
                                        stored as products
    the purchase order               -> requisition_id, so it lists under
                                        the agreement's Purchase Orders

WHAT A CERTIFICATE KNOWS

x_site_payment_certifi (181 rows) holds one fact of its own: which agreement
it claims against. The certificate itself is already ssc.request (type SPC),
matched by its number; that request gets requisition_id. And a vendor bill
Studio tied to the certificate (account.move.x_studio_spc) is tied to the
request instead (ssc_request_id), so bill -> certificate -> agreement holds
after both Studio models are gone. A certificate whose request cannot be
found by number is listed, not guessed.
"""
import os
import re

WRITE = os.environ.get('SSC_WRITE') == '1'
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/agreements.md')

STATE = {'status1': 'draft', 'status2': 'confirmed', 'status3': 'confirmed', 'status4': 'done'}

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


def get(record, name, default=False):
    if not record or name not in record._fields:
        return default
    value = record[name]
    return default if value is False or value is None else value


env = env(context=dict(env.context, lang='en_US', active_test=False,   # noqa: F821
                       tracking_disable=True, mail_create_nolog=True, mail_notrack=True))
cr = env.cr

Agreement = env.get('x_contractor_agreement')
if Agreement is None:
    print("x_contractor_agreement is not on this database; nothing to carry.")
    raise SystemExit()
Agreement = Agreement.sudo()
Certificate = env.get('x_site_payment_certifi')
Certificate = Certificate.sudo() if Certificate is not None else None
Requisition = env['purchase.requisition'].sudo()
Request = env['ssc.request'].sudo()
Subcontract = env['ssc.subcontract'].sudo()
Move = env['account.move'].sudo()

for field in ('ssc_studio_ref_id', 'ssc_project_id', 'ssc_subcontract_id'):
    if field not in Requisition._fields:
        print("purchase.requisition has no %s: ssc_requests_purchase must be 1.3.0." % field)
        raise SystemExit()
if 'requisition_id' not in Request._fields:
    print("ssc.request has no requisition_id: ssc_requests_purchase must be 1.3.0.")
    raise SystemExit()

subcontracts = {s.studio_ref_id: s for s in Subcontract.search([('studio_ref_id', '!=', False)])}
subcontracts_by_name = {(s.name or '').strip(): s for s in Subcontract.search([])}
Partner = env['res.partner'].sudo()


def vendor_of(row, po, subcontract):
    """The purchase order's vendor; the subcontract's; or the one the agreement
    reads through its contractor (x_studio_vendor), a partner or a name."""
    if po and po.partner_id:
        return po.partner_id
    if subcontract and subcontract.partner_id:
        return subcontract.partner_id
    vendor = get(row, 'x_studio_vendor')
    if vendor and hasattr(vendor, '_name') and vendor._name == 'res.partner':
        return vendor
    if vendor and isinstance(vendor, str):
        return Partner.search([('name', '=ilike', vendor.strip())], limit=1)
    # A pending stub whose subcontract Studio itself deleted: the name is
    # "<vendor>-<scope>-<ref>", and the vendor is the part before the dash.
    head = (row.x_name or '').split('-')[0].strip()
    return Partner.search([('name', '=ilike', head)], limit=1) if head else None
carried = {r.ssc_studio_ref_id: r for r in Requisition.search([('ssc_studio_ref_id', '!=', False)])}

# ------------------------------------------------------------- the plan
title("the agreements, as they are")
rows = Agreement.search([], order='id')
say("  %s agreement(s); %s already carried" % (len(rows), len(carried)))
plan, refused = [], []
for row in rows:
    po = get(row, 'x_studio_po')
    contractor = get(row, 'x_studio_contractor')
    subcontract = subcontracts.get(contractor.id) if contractor else None
    if not subcontract:
        # a subcontract rebuilt from its reference rather than carried by id
        subcontract = subcontracts_by_name.get((get(row, 'x_studio_ref_no') or '').strip())
    project = get(row, 'x_studio_project')
    vendor = vendor_of(row, po, subcontract)
    if not vendor:
        refused.append((row, "no purchase order and no subcontract to take the vendor from"))
        continue
    if not project:
        refused.append((row, "no project"))
        continue
    plan.append((row, po, subcontract, project, vendor))
say("  %s become a purchase agreement; %s cannot:" % (len(plan), len(refused)))
for row, why in refused:
    say("      %-8s %-60s %s" % (row.id, (row.x_name or '')[:60], why))
say("  %s have a purchase order to list under them; %s name a subcontract that was carried"
    % (sum(1 for p in plan if p[1]), sum(1 for p in plan if p[2])))
say("  states: %s" % {k: sum(1 for p in plan if get(p[0], 'x_studio_selection_field_97j_1irpbgcdj') == k)
                      for k in STATE})

# ------------------------------------------------------- the certificates
title("the certificates, and the requests they are")
cert_plan, cert_orphans = [], []
if Certificate is not None:
    certs = Certificate.search([], order='id')
    by_name = {}
    for request in Request.search([('type_code', '=', 'SPC')]):
        for key in (request.name, request.reference):
            if key:
                by_name.setdefault(key.strip(), request)
    for cert in certs:
        # "SSC/ARJ-672/SPC0038 - Advance Payment" is the certificate
        # SSC/ARJ-672/SPC0038 with a note after the dash
        name = (cert.x_name or '').strip()
        request = by_name.get(name) or by_name.get(name.split(' - ')[0].strip())
        agreement = get(cert, 'x_studio_contract')
        if not request:
            cert_orphans.append((cert, "no request named %s" % cert.x_name))
            continue
        if not agreement:
            cert_orphans.append((cert, "names no agreement"))
            continue
        cert_plan.append((cert, request, agreement))
    say("  %s certificate(s): %s match a request by number, %s do not:"
        % (len(certs), len(cert_plan), len(cert_orphans)))
    for cert, why in cert_orphans:
        say("      %-8s %-28s %s" % (cert.id, (cert.x_name or '')[:28], why))
    bills = Move.search([('x_studio_spc', '!=', False)]) if 'x_studio_spc' in Move._fields else Move
    say("  %s vendor bill(s) tied to a certificate; %s already tied to a request"
        % (len(bills), len(bills.filtered('ssc_request_id'))))
else:
    say("  x_site_payment_certifi is not here")

if not WRITE:
    title("nothing was written")
    say("  Run again with SSC_WRITE=1.")
    finish()

# ---------------------------------------------------------------- writing
title("writing the agreements")
made = linked_po = 0
requisition_of = dict(carried)
for row, po, subcontract, project, vendor in plan:
    requisition = carried.get(row.id)
    if not requisition:
        # "<vendor>-<scope>-<reference>", and the reference itself carries a
        # dash (SSC/KHAN-211/2025/SC006): it is the tail from the company code on
        name = row.x_name or ''
        found = re.search(r'(SSC|RA|RW|MALAK)/\S+$', name)
        reference = get(row, 'x_studio_ref_no') or (found.group(0) if found else name)[:64]
        scope = get(row, 'x_studio_scope_description') or ''
        if not scope and found:
            middle = name[:found.start()].rstrip(' -')
            scope = middle.split('-', 1)[1].strip() if '-' in middle else ''
        company = get(row, 'x_studio_company_id') or project.company_id or env.company
        lines = [(0, 0, {
            'product_id': line.product_id.id,
            'product_qty': line.product_qty,
            'product_uom_id': line.product_uom_id.id if 'product_uom_id' in line._fields else line.product_uom.id,
            'price_unit': line.price_unit,
            'product_description_variants': (line.name or '')[:200],
        }) for line in (po.order_line if po else [])
            if line.product_id]
        requisition = Requisition.with_company(company).create({
            'name': reference,
            'reference': reference,
            'requisition_type': 'blanket_order',
            'vendor_id': vendor.id,
            'company_id': company.id,
            'currency_id': (get(row, 'x_studio_currency_id') or company.currency_id).id,
            'date_start': get(row, 'x_studio_date_of_agreement') or False,
            'description': scope or False,
            'ssc_scope': scope[:200] or False,
            'ssc_project_id': project.id,
            'ssc_subcontract_id': subcontract.id if subcontract else False,
            'ssc_studio_ref_id': row.id,
            'line_ids': lines,
        })
        # create() numbers every blanket order from its own sequence; the
        # office reads the agreement by the subcontract's number, so that
        # is what the record is called, and the sequence number stays in
        # the chatter's creation line.
        requisition.write({'name': reference})
        state = STATE.get(get(row, 'x_studio_selection_field_97j_1irpbgcdj'), 'draft')
        if state != 'draft':
            requisition.write({'state': state})
        made += 1
    requisition_of[row.id] = requisition
    if po and 'requisition_id' in po._fields and not po.requisition_id:
        po.write({'requisition_id': requisition.id})
        linked_po += 1
cr.commit()
say("  %s agreement(s) made, %s purchase order(s) listed under theirs" % (made, linked_po))

title("writing the signed agreements")
# The signed contract - the terms themselves - sits in x_studio_approved_contract,
# a binary stored in the row (no ir.attachment behind it). It becomes a file on
# the purchase agreement's chatter, named as it was uploaded, once.
Attachment = env['ir.attachment'].sudo()
files = 0
for row, po, subcontract, project, vendor in plan:
    requisition = requisition_of.get(row.id)
    data = get(row, 'x_studio_approved_contract')
    if not (requisition and data):
        continue
    origin = "studio:x_contractor_agreement:%s:x_studio_approved_contract" % row.id
    if Attachment.search_count([('description', '=', origin), ('res_model', '=', 'purchase.requisition'),
                                ('res_id', '=', requisition.id)]):
        continue
    Attachment.create({
        'name': get(row, 'x_studio_approved_contract_filename') or "Approved Agreement.pdf",
        'datas': data,
        'res_model': 'purchase.requisition',
        'res_id': requisition.id,
        'description': origin,
    })
    files += 1
cr.commit()
say("  %s signed agreement(s) filed on their purchase agreement" % files)

title("writing the certificates")
linked = bills_linked = 0
for cert, request, agreement in cert_plan:
    requisition = requisition_of.get(agreement.id)
    if requisition and not request.requisition_id:
        request.write({'requisition_id': requisition.id})
        linked += 1
    if 'x_studio_spc' in Move._fields:
        for bill in Move.search([('x_studio_spc', '=', cert.id), ('ssc_request_id', '=', False)]):
            bill.write({'ssc_request_id': request.id})
            bills_linked += 1
cr.commit()
say("  %s certificate(s) told their agreement, %s vendor bill(s) told their certificate"
    % (linked, bills_linked))

title("done")
finish()
