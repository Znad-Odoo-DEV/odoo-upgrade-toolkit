"""Carry the subcontracts, their bill of quantities, their sectors and the
certificates raised against them.

    odoo-bin shell --no-http --shell-interface=python < tools/import_studio_subcontracts.py
    SSC_WRITE=1 odoo-bin shell --no-http < tools/import_studio_subcontracts.py

Idempotent throughout: everything is keyed on studio_ref_id.

Run it after tools/import_studio_requests.py. The payment certificates are
requests, and their lines can only be attached to requests that are already
here.

The one thing that cannot be carried mechanically is which contract an item
belongs to. Studio's x_contracts_item had no link to a contract at all: an item
belonged to one by carrying the same contractor and the same project, so where
a subcontractor has two contracts on one project there is no fact in the
database that says which. Those are reported rather than guessed, and they are
the only rows this leaves behind.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

CONTRACTS = 'x_subcontractors'
ITEMS = 'x_contracts_item'
WORKS = 'x_sc_breakdown'
SECTORS = 'x_sc_sectors'
CERT_LINES = 'x_all_requests_line_05c8c'
CERT_CLAIMS = 'x_all_requests_line_05c8c_line_d44ac'

cr = env.cr                                                      # noqa: F821

Contract = env['ssc.subcontract'].sudo().with_context(           # noqa: F821
    active_test=False, tracking_disable=True,
    mail_create_nolog=True, mail_create_nosubscribe=True)
Item = env['ssc.subcontract.item'].sudo().with_context(active_test=False)   # noqa: F821
Work = env['ssc.subcontract.work'].sudo().with_context(active_test=False)   # noqa: F821
Sector = env['ssc.subcontract.sector'].sudo().with_context(active_test=False)  # noqa: F821
Request = env['ssc.request'].sudo().with_context(active_test=False)         # noqa: F821
Line = env.get('ssc.request.certificate.line')                   # noqa: F821
Claim = env.get('ssc.request.certificate.claim')                 # noqa: F821


def title(text):
    print("\n" + "=" * 92)
    print(text)
    print("=" * 92)


def source(name):
    model = env.get(name)                                        # noqa: F821
    return model.sudo().with_context(active_test=False) if model is not None else None


def g(record, name, default=False):
    if not record or name not in record._fields:
        return default
    value = record[name]
    return value if value is not False and value is not None else default


SCOPE = {
    'value1': 'supply_install',
    'value2': 'supply',
    'value3': 'install',
    'value4': 'service',
}
CONTRACT_TYPE = {
    'Unit Price': 'unit_price',
    'Remeasurable': 'remeasurable',
    'Lump Sum': 'lump_sum',
}
# Studio's five units, as the certificates print them.
UNIT = {'NOS.': 'nos', 'cum': 'cum', 'sqm': 'sqm', 'L.m': 'lm', 'L.S': 'ls'}

Source = {name: source(name) for name in
          (CONTRACTS, ITEMS, WORKS, SECTORS, CERT_LINES, CERT_CLAIMS)}
missing = [name for name, model in Source.items() if model is None]
if missing:
    raise SystemExit("Not in this database: %s" % ", ".join(missing))


title("1. what is there")

for label, name in (('contracts', CONTRACTS), ('bill of quantities', ITEMS),
                    ('work categories', WORKS), ('sectors', SECTORS),
                    ('certificate lines', CERT_LINES),
                    ('sector claims', CERT_CLAIMS)):
    print("  %-22s %6s" % (label, Source[name].search_count([])))

print("\n  already carried here:")
for label, model in (('contracts', Contract), ('items', Item),
                     ('work categories', Work), ('sectors', Sector)):
    print("  %-22s %6s" % (label, model.search_count([('studio_ref_id', '!=', False)])))
if Line is not None:
    print("  %-22s %6s" % ('certificate lines',
                           Line.sudo().search_count([('studio_ref_id', '!=', False)])))
    print("  %-22s %6s" % ('sector claims',
                           Claim.sudo().search_count([('studio_ref_id', '!=', False)])))
else:
    print("\n  ssc_requests_subcontract is not installed, so the certificates")
    print("  will not be carried. Install it and run this again.")


title("2. the items that cannot be placed")

# An item belongs to a contract by carrying the same contractor and project.
# Where that pair names more than one contract, nothing in the database says
# which - so it is reported, not guessed.
contracts_by_pair = {}
for record in Source[CONTRACTS].search([]):
    partner = g(record, 'x_studio_contractor')
    project = g(record, 'x_studio_project')
    if partner and project:
        contracts_by_pair.setdefault((partner.id, project.id), []).append(record)

# Where the pair names two contracts, the certificates settle it. A payment
# certificate names both the contract it is claimed against and the items it
# claims, so an item that has only ever been certified under one contract
# belongs to that contract - and that is a fact in the database, not a guess.
# It places forty-five of the forty-seven, and with them four hundred sectors,
# three hundred certificate lines and nearly a thousand claims that would
# otherwise have been left behind by an ambiguity nobody could have resolved by
# hand.
certified_under = {}
_lines = Source[CERT_LINES].search([])
for _line in _lines:
    _item = g(_line, 'x_studio_item_description')
    _parent = g(_line, 'x_all_requests_id')
    _contract = _parent and g(_parent, 'x_studio_contract')
    if _item and _contract:
        certified_under.setdefault(_item.id, set()).add(_contract.id)


# The item does carry a fact the pair does not: x_studio_ref_no, the contract
# reference the item was raised under - "SSC/KHAN-211/2025/SC004". Where a
# contractor has two contracts on a project, that string is the one that says
# which, and it settles all fifteen the pair and the certificates could not.
contracts_by_ref = {}
for record in Source[CONTRACTS].search([]):
    ref = (g(record, 'x_studio_ref_no') or '').strip()
    if ref:
        contracts_by_ref.setdefault(ref, record)


def contract_for(record):
    """The Studio contract an item belongs to, or None if nothing says."""
    ref = (g(record, 'x_studio_ref_no') or '').strip()
    if ref in contracts_by_ref:
        return contracts_by_ref[ref]
    partner = g(record, 'x_studio_contractor')
    project = g(record, 'x_studio_project')
    found = contracts_by_pair.get(
        (partner.id if partner else 0, project.id if project else 0), [])
    if len(found) == 1:
        return found[0]
    if not found:
        return None
    seen = certified_under.get(record.id, set())
    candidates = [c for c in found if c.id in seen]
    return candidates[0] if len(candidates) == 1 else None


ambiguous, orphan, by_certificate = [], [], 0
for record in Source[ITEMS].search([]):
    partner = g(record, 'x_studio_contractor')
    project = g(record, 'x_studio_project')
    found = contracts_by_pair.get(
        (partner.id if partner else 0, project.id if project else 0), [])
    if not found:
        orphan.append(record)
    elif len(found) > 1:
        if contract_for(record):
            by_certificate += 1
        else:
            ambiguous.append((record, found))

# Fifteen x_subcontractors rows were deleted before May 2026 - a Studio
# one2many is ondelete set-null, so their items, sectors, breakdowns, payment
# stages, signed PDFs and certificates all survived with the parent gone and
# the reference still written on every row. A contract whose reference is on
# rows and on no contract is rebuilt from those rows: contractor, project,
# scope and company from the items (the payment stages where there are no
# items), the earliest row's date as the date of agreement. It gets no
# studio_ref_id, because there is no Studio row to point at; the reference is
# its name and is what the rows are matched on.
PAYMENT_TYPES = 'x_sc_payment_type'
ATTACHMENTS = 'x_sc_attachments'

# Three references survive on nothing but their signed PDF, which names no
# contractor. What does name one: the purchase order raised under the same
# reference (purchase.order.x_studio_mr_reference) and the contractor
# agreements of the same day carrying the reference as their name. Read on
# 2026-09-06 on a copy of production of the day before; the project is the
# one the reference prefix stands for.
#   SSC/ARJ-672/2025/SC014    purchase order 416, partner 3011, 2025-07-20;
#                             agreement 30 (Valuestar, aluminium) of that day
#   SSC/KHAN-211/2025/SC006   purchase order 508, partner 3917 (Middle East
#                             Dewatering), 2025-09-09; agreements 39-42
#   SSC/MANARA-868/2025/SC002 agreement 17 (Al Marjan) of 2025-07-01; the
#                             contractor's other contract, AJM SC001, is 3855
RECOVERED = {
    'SSC/ARJ-672/2025/SC014': (3011, 19, 'purchase order 416 and agreement 30'),
    'SSC/KHAN-211/2025/SC006': (3917, 14, 'purchase order 508 and agreements 39 to 42'),
    'SSC/MANARA-868/2025/SC002': (3855, 20, 'agreement 17'),
}
ours_by_name = {c.name: c for c in Contract.search([('name', '!=', False)])}
rebuild = {}
for model_name, ref_field in ((ITEMS, 'x_studio_ref_no'), (SECTORS, 'x_studio_ref_no'),
                              (WORKS, 'x_studio_ref_no'), (PAYMENT_TYPES, 'x_studio_ref_no'),
                              (ATTACHMENTS, 'x_name')):
    model = source(model_name)
    if model is None:
        continue
    for row in model.search([]):
        ref = (g(row, ref_field) or '').strip()
        if not ref or ref in contracts_by_ref or ref in ours_by_name:
            continue
        found = rebuild.setdefault(ref, {'rows': 0, 'partner': None, 'project': None,
                                         'scope': None, 'company': None, 'first': None,
                                         'stages': []})
        found['rows'] += 1
        for key, name in (('partner', 'x_studio_contractor'), ('project', 'x_studio_project'),
                          ('scope', 'x_studio_scope_description'), ('company', 'x_studio_company_id')):
            if found[key] is None and g(row, name):
                found[key] = g(row, name)
        if model_name == PAYMENT_TYPES and g(row, 'x_name'):
            found['stages'].append(g(row, 'x_name'))
        created = row.create_date and row.create_date.date()
        if created and (found['first'] is None or created < found['first']):
            found['first'] = created

for ref, (partner_id, project_id, evidence) in RECOVERED.items():
    found = rebuild.get(ref)
    if found and not found['partner']:
        partner = env['res.partner'].sudo().browse(partner_id).exists()   # noqa: F821
        project = env['project.project'].sudo().browse(project_id).exists()  # noqa: F821
        if partner and project:
            found['partner'], found['project'] = partner, project
            found['evidence'] = evidence

print("  %s reference(s) are on rows and on no contract, Studio's or ours:" % len(rebuild))
for ref, found in sorted(rebuild.items()):
    print("      %-28s %4s row(s)  %-32s %-28s %s%s"
          % (ref, found['rows'],
             (found['partner'].display_name if found['partner'] else '(no contractor)')[:32],
             (found['project'].display_name if found['project'] else '(no project)')[:28],
             found['first'] or '',
             ('   from ' + found['evidence']) if found.get('evidence') else
             '' if found['partner'] and found['project'] else '   CANNOT REBUILD'))

print("  %s item(s) name a contractor and project with no contract" % len(orphan))
print("  %s item(s) were placed by the certificates raised on them" % by_certificate)
print("  %s item(s) are still ambiguous and are left where they are" % len(ambiguous))
if ambiguous:
    for record, found in ambiguous[:8]:
        print("      %-40s -> %s contracts"
              % ((g(record, 'x_name') or '')[:40], len(found)))
print("""
  An item on no contract has nothing to be certified against, and one that is
  still ambiguous after the certificates have been read is a question for the
  person who signed the two contracts - not something to decide here.""")

# Studio's x_contracts_sequence: one row per company and project with the
# prefix typed in - SSC/ARJ-672/%(year)s/SC - and a "next" that was never
# the truth (it says 10 where SC027 exists). The prefix is carried; the next
# number is read off the references that exist under that prefix - Studio's
# contracts, ours, and the ones rebuilt from a reference - so the next one
# issued follows the last one signed rather than reusing a number. Section 2c
# shows the plan; the counters are written in 3e, after the contracts are.
import re
Numbering = source('x_contracts_sequence')
Sequence = env['ir.sequence'].sudo()                             # noqa: F821


def all_references():
    refs = set(contracts_by_ref)
    refs.update(rebuild)
    refs.update(c.name for c in Contract.search([('name', '!=', False)]))
    return refs


def numbering(write):
    carried_seq = 0
    if Numbering is None:
        print("  x_contracts_sequence is not on this database; nothing to carry")
        return 0
    refs = all_references()
    for row in Numbering.search([], order='id'):
        company = g(row, 'x_studio_company_id')
        project = g(row, 'x_studio_project')
        prefix = (g(row, 'x_studio_prefix') or '').strip()
        if not company or not project or not prefix:
            print("  ! row %s has no company, project or prefix; left" % row.id)
            continue
        # the highest number issued under this prefix, any year
        pattern = re.compile('^' + re.escape(prefix).replace(re.escape('%(year)s'), r'\d{4}') + r'(\d+)$')
        highest = 0
        for ref in refs:
            m = pattern.match(ref or '')
            if m:
                highest = max(highest, int(m.group(1)))
        code = 'ssc.subcontract.%s.%s' % (company.id, project.id)
        found = Sequence.search([('code', '=', code)], limit=1)
        values = {'prefix': prefix, 'padding': 3, 'number_next_actual': highest + 1}
        print("  %-42s %-28s next SC%03d%s" % (prefix, project.display_name[:28], highest + 1,
                                               '' if not found else '   (updates the existing counter)'))
        if write:
            if found:
                found.write(values)
            else:
                Sequence.create(dict(values, name="Subcontract - %s - %s" % (company.name, project.display_name),
                                     code=code, implementation='standard', company_id=company.id))
        carried_seq += 1
    if write:
        cr.commit()
    return carried_seq


title("2c. the numbering, per company and project")
print("  %s counter(s)" % numbering(write=False))


if DRY_RUN:
    print("\n" + "=" * 92)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


title("3. the contracts")

carried = 0
existing = set(Contract.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
for record in Source[CONTRACTS].search([], order='id'):
    if record.id in existing:
        continue
    partner = g(record, 'x_studio_contractor')
    project = g(record, 'x_studio_project')
    if not partner or not project:
        continue
    company = g(record, 'x_studio_company_id')
    approved = bool(g(record, 'x_studio_approved'))
    done = g(record, 'x_studio_done', 0.0) or g(record, 'x_studio_done_perc', 0.0)
    try:
        with cr.savepoint():
            Contract.create({
                'studio_ref_id': record.id,
                'name': g(record, 'x_studio_ref_no') or False,
                'description': (g(record, 'x_name') or 'Subcontract')[:255],
                'scope_description': g(record, 'x_studio_scope_description') or False,
                'partner_id': partner.id,
                'project_id': project.id,
                'company_id': company.id if company else env.company.id,  # noqa: F821
                'date_agreement': g(record, 'x_studio_date_of_agreement') or False,
                'quotation_ref': g(record, 'x_studio_quotation_ref') or False,
                'scope': SCOPE.get(g(record, 'x_studio_scope_of_contract'), 'service'),
                'contract_type': CONTRACT_TYPE.get(
                    g(record, 'x_studio_type_of_contract'), 'unit_price'),
                'state': ('running' if approved and done else
                          'approved' if approved else 'draft'),
                'vat_applicable': bool(g(record, 'x_studio_vat_applicable')),
                'has_retention': bool(g(record, 'x_studio_ret')),
                'retention_percent': g(record, 'x_studio_retention', 0.0),
                'has_warranty_retention': bool(g(record, 'x_studio_warranty_retention')),
                'has_advance': bool(g(record, 'x_studio_advance')),
                'advance_amount': g(record, 'x_studio_value_of_advance', 0.0),
                'on_progressive': bool(
                    g(record, 'x_studio_payment_will_be_on_progressive_')),
                'progressive_percent': g(record, 'x_studio_progressive_1', 0.0),
                'penalty_amount': g(record, 'x_studio_penalty', 0.0),
                'active': bool(g(record, 'x_active', True)),
            })
        carried += 1
    except Exception as exc:
        print("  ! %-8s %s" % (record.id, str(exc).strip().splitlines()[0][:70]))
cr.commit()
print("  %s contract(s)" % carried)

by_studio = {c.studio_ref_id: c for c in Contract.search([('studio_ref_id', '!=', False)])}


title("3b. the contracts rebuilt from their reference")

made = 0
for ref, found in sorted(rebuild.items()):
    if not found['partner'] or not found['project']:
        continue
    try:
        with cr.savepoint():
            Contract.create({
                'name': ref,
                'description': "%s - %s" % (found['partner'].display_name[:120],
                                             (found['scope'] or 'Subcontract')[:120]),
                'scope_description': found['scope'] or False,
                'partner_id': found['partner'].id,
                'project_id': found['project'].id,
                'company_id': found['company'].id if found['company'] else env.company.id,  # noqa: F821
                'date_agreement': found['first'] or False,
                'contract_type': 'unit_price',
                'scope': 'service',
                'state': 'running',
                'vat_applicable': True,
                'on_progressive': 'Progress' in found['stages'],
                'has_advance': 'Advance' in found['stages'] or 'Down Payment' in found['stages'],
            })
        made += 1
    except Exception as exc:
        print("  ! %-28s %s" % (ref, str(exc).strip().splitlines()[0][:70]))
cr.commit()
print("  %s contract(s) rebuilt" % made)
ours_by_name = {c.name: c for c in Contract.search([('name', '!=', False)])}
REBUILT_NOTE = ("Rebuilt from its reference: the Studio contract record had been "
                "deleted, and its items, sectors, certificates and signed copy "
                "survived. Check the retention, the advance and the VAT against "
                "the signed copy in the chatter.")
for ref in rebuild:
    contract = ours_by_name.get(ref)
    if contract and not contract.message_ids.filtered(
            lambda m: 'Rebuilt from its reference' in (m.body or '')):
        body = REBUILT_NOTE
        if rebuild[ref].get('evidence'):
            body += (" The contractor and the project were read from %s, because "
                     "only the signed copy survived." % rebuild[ref]['evidence'])
        contract.message_post(body=body, message_type='comment',
                              subtype_xmlid='mail.mt_note')
cr.commit()


title("3c. the payment stages, noted on the contract")

# x_sc_payment_type is a list per contract - Advance, Materials Delivery,
# Progress; or Milestone - that the contract's own flags already say
# (on_progressive, has_advance). The list is kept as a note in the chatter,
# once, so the wording the office used is not lost with the model.
Stages = source(PAYMENT_TYPES)
noted = 0
if Stages is not None:
    stages_by_ref = {}
    for row in Stages.search([], order='id'):
        ref = (g(row, 'x_studio_ref_no') or '').strip()
        if ref and g(row, 'x_name'):
            stages_by_ref.setdefault(ref, []).append(g(row, 'x_name'))
    for ref, names in stages_by_ref.items():
        contract = ours_by_name.get(ref)
        if not contract:
            continue
        marker = "Payment stages in Studio:"
        if contract.message_ids.filtered(lambda m: marker in (m.body or '')):
            continue
        contract.message_post(body="%s %s" % (marker, ", ".join(names)),
                              message_type='comment', subtype_xmlid='mail.mt_note')
        noted += 1
    cr.commit()
print("  %s contract(s) carry their payment stages as a note" % noted)


title("3e. the numbering, written now that every contract has its name")
print("  %s counter(s)" % numbering(write=True))


title("4. the work categories")

carried = 0
existing = set(Work.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
names = {w.name: w for w in Work.search([])}
work_by_studio = {w.studio_ref_id: w for w in Work.search([('studio_ref_id', '!=', False)])}
for record in Source[WORKS].search([], order='id'):
    if record.id in existing:
        continue
    name = (g(record, 'x_name') or '').strip()
    if not name:
        continue
    if name in names:
        # the same category under two Studio ids: one record, both ids answered
        work_by_studio[record.id] = names[name]
        continue
    try:
        with cr.savepoint():
            made = Work.create({'name': name, 'studio_ref_id': record.id})
        names[name] = made
        work_by_studio[record.id] = made
        carried += 1
    except Exception as exc:
        print("  ! %-8s %s" % (record.id, str(exc).strip().splitlines()[0][:70]))
cr.commit()
print("  %s work categor(ies)" % carried)


title("5. the bill of quantities")

carried = 0
existing = set(Item.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
for record in Source[ITEMS].search([], order='id'):
    if record.id in existing:
        continue
    placed = contract_for(record)
    contract = placed and by_studio.get(placed.id)
    if not contract:
        contract = ours_by_name.get((g(record, 'x_studio_ref_no') or '').strip())
    if not contract:
        continue                          # reported in section 2
    try:
        with cr.savepoint():
            Item.create({
                'studio_ref_id': record.id,
                'contract_id': contract.id,
                'sequence': g(record, 'x_studio_sequence', 10) or 10,
                'reference': g(record, 'x_studio_ref_no') or False,
                'name': (g(record, 'x_name') or 'Item')[:255],
                'scope_description': g(record, 'x_studio_scope_description') or False,
                'product_id': (g(record, 'x_studio_item') or
                               env['product.template'].browse([])).id or False,  # noqa: F821
                'unit': UNIT.get(g(record, 'x_studio_unit'), 'nos'),
                'quantity': g(record, 'x_studio_full_qty', 0.0),
                'unit_price': g(record, 'x_studio_unit_price', 0.0),
                'account_id': (g(record, 'x_studio_account_1') or
                               env['account.account'].browse([])).id or False,  # noqa: F821
                'active': bool(g(record, 'x_active', True)),
            })
        carried += 1
    except Exception as exc:
        print("  ! %-8s %s" % (record.id, str(exc).strip().splitlines()[0][:70]))
cr.commit()
print("  %s item(s)" % carried)

item_by_studio = {i.studio_ref_id: i for i in Item.search([('studio_ref_id', '!=', False)])}


title("6. the sectors")

carried = 0
existing = set(Sector.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
for record in Source[SECTORS].search([], order='id'):
    if record.id in existing:
        continue
    scope_item = g(record, 'x_studio_scope_item')
    item = scope_item and item_by_studio.get(scope_item.id)
    if not item:
        continue
    work = g(record, 'x_studio_work')
    try:
        with cr.savepoint():
            Sector.create({
                'studio_ref_id': record.id,
                'item_id': item.id,
                'sequence': g(record, 'x_studio_sequence', 10) or 10,
                'reference': g(record, 'x_studio_ref_no') or False,
                'name': (g(record, 'x_name') or 'Sector')[:255],
                'work_id': (work and work_by_studio.get(work.id)
                            and work_by_studio[work.id].id) or False,
                'quantity': g(record, 'x_studio_total_qty', 0.0),
                'unit_price': g(record, 'x_studio_unit_price_aedunit', 0.0),
                'factor': g(record, 'x_studio_factor', 1.0) or 1.0,
                'active': bool(g(record, 'x_active', True)),
            })
        carried += 1
    except Exception as exc:
        print("  ! %-8s %s" % (record.id, str(exc).strip().splitlines()[0][:70]))
cr.commit()
print("  %s sector(s)" % carried)

sector_by_studio = {s.studio_ref_id: s
                    for s in Sector.search([('studio_ref_id', '!=', False)])}


if Line is None:
    title("done - without the certificates")
    print("  ssc_requests_subcontract is not installed. Install it and run this")
    print("  again to carry the certificate lines and the sector claims.")
    raise SystemExit()

Line = Line.sudo().with_context(active_test=False)
Claim = Claim.sudo().with_context(active_test=False)


title("7. the certificates on the requests")

request_by_studio = {r.studio_ref_id: r
                     for r in Request.search([('studio_ref_id', '!=', False)])}

# Which contract each certificate was raised against is on the Studio request,
# so it is read from there rather than guessed from the project.
attached = 0
source_requests = env.get('x_all_requests')              # noqa: F821
if source_requests is not None:
    source_requests = source_requests.sudo().with_context(active_test=False)
    for record in source_requests.search([('x_studio_type_of_request_1', '=', 'SPC')]):
        request = request_by_studio.get(record.id)
        if not request or request.contract_id:
            continue
        contract = g(record, 'x_studio_contract')
        ours = contract and by_studio.get(contract.id)
        if ours:
            request.contract_id = ours.id
            attached += 1
    cr.commit()
print("  %s certificate(s) linked to a contract" % attached)

carried = 0
existing = set(Line.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
for record in Source[CERT_LINES].search([], order='id'):
    if record.id in existing:
        continue
    parent = g(record, 'x_all_requests_id')
    request = parent and request_by_studio.get(parent.id)
    if not request:
        continue
    studio_item = g(record, 'x_studio_item_description')
    item = studio_item and item_by_studio.get(studio_item.id)
    if not item:
        continue
    try:
        with cr.savepoint():
            Line.create({
                'studio_ref_id': record.id,
                'request_id': request.id,
                'sequence': g(record, 'x_studio_sequence', 10) or 10,
                'line_no': g(record, 'x_studio_sl_no', 0),
                'item_id': item.id,
                'name': (g(record, 'x_name') or item.name)[:255],
                'unit_price': item.unit_price,
            })
        carried += 1
    except Exception as exc:
        print("  ! %-8s %s" % (record.id, str(exc).strip().splitlines()[0][:70]))
cr.commit()
print("  %s certificate line(s)" % carried)

# The Studio link from certificate to contract went with the deleted
# contracts. The lines still name their items, and the items now name their
# contract, so a certificate with no contract and lines on exactly one is on
# that one.
relinked, torn = 0, []
for request in Request.search([('studio_ref_id', '!=', False), ('contract_id', '=', False),
                               ('type_code', '=', 'SPC')]):
    contracts = request.certificate_line_ids.mapped('item_id.contract_id')
    if len(contracts) == 1:
        request.contract_id = contracts.id
        relinked += 1
    elif len(contracts) > 1:
        torn.append((request, contracts))
cr.commit()
print("  %s certificate(s) linked through their lines" % relinked)
for request, contracts in torn:
    print("      %-30s lines on %s contracts: %s" % (
        (request.name or '')[:30], len(contracts), ", ".join(contracts.mapped('name'))))

line_by_studio = {l.studio_ref_id: l for l in Line.search([('studio_ref_id', '!=', False)])}


title("8. the sector claims")

carried = 0
existing = set(Claim.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
for record in Source[CERT_CLAIMS].search([], order='id'):
    if record.id in existing:
        continue
    parent = g(record, 'x_all_requests_line_05c8c_id')
    line = parent and line_by_studio.get(parent.id)
    if not line:
        continue
    studio_sector = g(record, 'x_studio_sector')
    sector = studio_sector and sector_by_studio.get(studio_sector.id)
    if not sector:
        continue
    try:
        with cr.savepoint():
            Claim.create({
                'studio_ref_id': record.id,
                'line_id': line.id,
                'sequence': g(record, 'x_studio_sequence', 10) or 10,
                'sector_id': sector.id,
                'name': (g(record, 'x_name') or sector.name)[:255],
                'quantity': g(record, 'x_studio_quantity', 0.0),
            })
        carried += 1
    except Exception as exc:
        print("  ! %-8s %s" % (record.id, str(exc).strip().splitlines()[0][:70]))
cr.commit()
print("  %s claim(s)" % carried)


title("after")

print("  contracts        %6s" % Contract.search_count([('studio_ref_id', '!=', False)]))
print("  items            %6s" % Item.search_count([('studio_ref_id', '!=', False)]))
print("  work categories  %6s" % Work.search_count([('studio_ref_id', '!=', False)]))
print("  sectors          %6s" % Sector.search_count([('studio_ref_id', '!=', False)]))
print("  certificate lines%6s" % Line.search_count([('studio_ref_id', '!=', False)]))
print("  sector claims    %6s" % Claim.search_count([('studio_ref_id', '!=', False)]))
print("""
  The percentages done are not carried and were not meant to be: they are
  computed from the claims now. Open a contract that is half built and check
  that its sectors say what the site says.""")
