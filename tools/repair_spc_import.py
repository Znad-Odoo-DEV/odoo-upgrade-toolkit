"""What the import owed the certificates, put right.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/repair_spc_import.py

    SSC_WRITE=1      actually write
    SSC_STEPS=retention,advance,progressive,penalty,invoice,factor,advance_line,claims,consultant,leaving,needed,date,price,quantity
    SSC_PENALTIES=all    carry the five that are not penalties (see below)
    SSC_OUT=~/spc_repair.md

Dry by default.

Only what was demonstrated. Every step below rests on something counted or on
Studio's own code, and the things still being argued about - the progressive
sub total, the frozen totals - are not touched here.

  retention     Studio's x_studio_ret_perc is a FRACTION related from the
                contract: 0.1 meaning a tenth. Our retention_percent means per
                cent, where a tenth is 10. The import copied the number and
                dropped its meaning, so ten per cent became one tenth of one
                per cent - verified on three certificates by hand and then on
                24 by count, every one of which held exactly a thousandth of
                its gross and not one a tenth.

  advance       Six contracts, each using ONE percentage throughout - 35, 30
                and 50 - and none using two, so the contract is where it
                belongs. Studio held it on the certificate and the import never
                told the contract, which is why advance recovery is zero on all
                25 that should have one.

  progressive   34 certificates are on a progressive-payment contract and 26
                carry a payable-invoice figure. The contract already has
                on_progressive and progressive_percent; the import never filled
                them either. This step only carries the facts. Whether the
                certificate should COMPUTE from them is a change to the model
                and is deliberately not made here.

  penalty       Nine certificates carry one and none came across.

                Five of the nine are not penalties. Their reasons read
                "Retention on Advance", "RETENTION ON ADVANCE PAYMENT",
                "Previously paid + Retention on advance" - the office recorded
                advance retention in the penalty box because there was no box
                for it. Once the advance recovery above computes properly those
                five would be deducted twice, so they are LISTED AND SKIPPED,
                and SSC_PENALTIES=all carries them anyway if somebody decides
                otherwise. That decision is an accounting one, not a technical
                one.

  factor        Studio's sector rows carry x_studio_factor and the import
                left it behind, so a line whose sectors count pieces reads as
                pieces rather than as the unit it is priced in. It is 4 on
                twenty lines and 1 on 696, it never varies within a line, and
                dividing by it reproduces Studio's own line quantity on every
                line that has one. Our line now has pieces_per_unit; this
                fills it.

  advance_line  39 lines say their work done is 'Advance Payment', across 8
                certificates. Studio charges no retention and recovers no
                advance on those; we were charging both on all eight. Our line
                has is_advance_payment now; this ticks it.

  claims        Twenty of our certificate lines have no sector claim at all,
                so their quantity is nothing where Studio has a real one -
                Ajman to Sharjah tolls, concrete compressive strength tests,
                monthly site work. Those rows were never made rather than made
                wrongly, and they are most of what still differs from Studio's
                live lines. Every sector is matched by studio_ref_id and never
                by name; a row whose sector is not on our side is listed
                rather than invented.

  consultant    x_studio_consultant_email and consultant_re_email are on the
                certificate in Studio and on nothing else, because a
                certificate is what goes to the consultant. Each holds one
                distinct value across the whole database, and by project they
                read Site@antcpl.com and projects@antcpl.com for Arjan,
                Site@antcpl.com for Al Manara. They move to the project. A
                project whose certificates disagree about the address is
                listed rather than given one of them.

  leaving       x_studio_type on a resignation says "Resigning" or "No
                Renew" - 36 and 15 of them - and the notice period is measured
                to a different date for each. Without it the fifty-one
                resignations already carried have nothing to measure to.
                Nothing else on this list is about resignations; it is here
                because this is the tool that already pairs the two sides.

  needed        x_studio_requirement_date_2 is a char filled on 984 requests
                and most of it reads "ASAP". Our date_required is a Date where
                empty means as soon as possible, so ASAP becomes empty and a
                real date becomes a date. Anything that is neither is LISTED
                rather than dropped: 984 rows of free text will contain
                something nobody predicted, and finding out what it is beats
                assuming it was another way of writing ASAP.

  invoice       The tax invoice itself on 186 certificates, its date on 117,
                its reference on 181 and the notes on 19. The fields all exist
                on our side; nothing was ever put in them. The file is copied
                out of ir.attachment rather than read and rewritten, and a row
                whose file is missing from the filestore is skipped and named -
                the same care as the attachments migration, and for the same
                reason.

Run twice safely. Every step checks what is already there before writing.
"""
import datetime
import os

WRITE = os.environ.get('SSC_WRITE') == '1'
STEPS = [s.strip() for s in (os.environ.get('SSC_STEPS')
                             or 'retention,advance,progressive,penalty,'
                                'invoice,factor,advance_line,claims,consultant,leaving,needed,date,price,quantity'
                             ).split(',') if s.strip()]
ALL_PENALTIES = os.environ.get('SSC_PENALTIES') == 'all'
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/spc_repair.md')

STUDIO = 'x_all_requests'

# Words that say a row in the penalty box is not a penalty.
#
# Matched as keywords rather than as whole sentences, because the first version
# matched whole sentences and let the largest of the nine straight through:
# SPC0013, 78,000, "Previously Paid on last invoice". That is money already
# paid on an earlier certificate, deducted from this one - the same kind of
# thing as the advance retentions and just as wrong to carry as a penalty. A
# subcontractor reading that report would see a 78,000 fine for work they were
# already paid for.
NOT_A_PENALTY_WORDS = ('retention', 'previously paid', 'advance')

report = []
counts = {}


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say()
    say(rule * 96)
    say(text)
    say(rule * 96)


def note(step, what):
    counts[(step, what)] = counts.get((step, what), 0) + 1


def finish():
    with open(OUT, 'w', encoding='utf-8') as handle:
        handle.write("\n".join(report))
    print("\nwritten to %s" % OUT)
    raise SystemExit


def g(record, name, default=None):
    try:
        return record[name]
    except Exception:
        return default


title("repairing what the import owed the certificates")
say("  %s" % ("WRITING" if WRITE else "dry run - nothing will be changed"))
say("  steps: %s" % ", ".join(STEPS))

if STUDIO not in env or 'ssc.request' not in env:                # noqa: F821
    say("  Both sides have to be here.")
    finish()

Studio = env[STUDIO].sudo()                                      # noqa: F821
Request = env['ssc.request'].sudo()                              # noqa: F821
Attachment = env['ir.attachment'].sudo()                         # noqa: F821
Contract = env.get('ssc.subcontract')                            # noqa: F821

ours = Request.with_context(active_test=False).search(
    [('type_code', '=', 'SPC')])
studio_by_id = {row.id: row for row in
                Studio.with_context(active_test=False).search(
                    [('x_studio_type_of_request_1', '=', 'SPC')])}
paired = [(rec, studio_by_id[rec.studio_ref_id]) for rec in ours
          if rec.studio_ref_id in studio_by_id]
say("  %s certificate(s) paired" % len(paired))


# ========================================================== retention ========
if 'retention' in STEPS and Contract is not None:
    title("retention: a fraction put in a field that means per cent", '-')
    for contract in Contract.sudo().search([('retention_percent', '>', 0),
                                            ('retention_percent', '<', 1)]):
        was = contract.retention_percent
        say("      %-46s %s  ->  %s" % (contract.display_name[:46], was,
                                        was * 100))
        if WRITE:
            contract.retention_percent = was * 100
        note('retention', 'corrected')
    already = Contract.sudo().search_count([('retention_percent', '>=', 1)])
    say()
    say("      %s contract(s) already hold a figure of 1 or more and are left"
        % already)
    say("      alone - which is also what makes this safe to run twice.")


# ============================================================ advance ========
if 'advance' in STEPS and Contract is not None:
    title("advance: held on the certificate, belongs on the contract", '-')
    # Keyed on OUR contract, reached through our own certificate, so no
    # name matching is involved anywhere. Studio's certificate supplies the
    # figures; ours supplies which contract they belong to.
    by_contract = {}
    for rec, row in paired:
        perc = g(row, 'x_studio_advance_perc', 0)
        if not perc or not rec.contract_id:
            continue
        found = by_contract.setdefault(rec.contract_id, {'perc': set(),
                                                         'value': 0.0})
        found['perc'].add(perc)
        found['value'] = g(row, 'x_studio_advance_value', 0) or found['value']

    for contract, found in sorted(by_contract.items(),
                                  key=lambda kv: kv[0].display_name):
        if len(found['perc']) > 1:
            say("      %-40s MORE THAN ONE PERCENTAGE (%s) - skipped"
                % (contract.display_name[:40], sorted(found['perc'])))
            note('advance', 'ambiguous')
            continue
        perc = list(found['perc'])[0]
        if contract.has_advance and contract.advance_recovery_percent:
            note('advance', 'already set')
            continue
        say("      %-40s advance %s%%, value %s"
            % (contract.display_name[:40], perc, found['value']))
        if WRITE:
            contract.write({
                'has_advance': True,
                'advance_recovery_percent': perc,
                'advance_amount': found['value'] or contract.advance_amount,
            })
        note('advance', 'set')


# ======================================================== progressive ========
if 'progressive' in STEPS and Contract is not None:
    title("progressive payment: the facts only", '-')
    say("      This carries what the contract says. It does NOT change how a")
    say("      certificate computes its sub total - that is a model decision")
    say("      and 34 certificates depend on it.")
    say()
    seen = {}
    for rec, row in paired:
        if not rec.contract_id:
            continue
        seen.setdefault(rec.contract_id, {
            'on': bool(g(row, 'x_studio_prog_pay', False)),
            'percent': g(row, 'x_studio_progressive_', 0.0) or 0.0,
        })
    for contract, found in sorted(seen.items(),
                                  key=lambda kv: kv[0].display_name):
        if not found['on']:
            continue
        if contract.on_progressive:
            note('progressive', 'already set')
            continue
        say("      %-46s progressive %s"
            % (contract.display_name[:46], found['percent']))
        if WRITE:
            contract.write({'on_progressive': True,
                            'progressive_percent': found['percent']})
        note('progressive', 'set')


# ============================================================ penalty ========
if 'penalty' in STEPS:
    title("penalties, and the five that are not penalties", '-')
    skipped, unexplained = [], []
    for rec, row in paired:
        amount = g(row, 'x_studio_penalty_amount', 0)
        if not amount:
            continue
        reason = (g(row, 'x_studio_penalty_reason', '') or '').strip()
        matched = [word for word in NOT_A_PENALTY_WORDS
                   if word in reason.lower()]
        if not reason:
            # No reason at all. Small amounts, and nobody alive can say what
            # they were for - carried, because refusing to move a figure
            # somebody entered is a bigger decision than moving it.
            unexplained.append((rec, amount))
        if matched and not ALL_PENALTIES:
            skipped.append((rec, amount, reason, matched))
            note('penalty', 'skipped: not a penalty')
            continue
        if rec.certificate_penalty:
            note('penalty', 'already carried')
            continue
        say("      %-30s %12.2f   %s"
            % ((rec.name or '')[:30], amount, reason[:36]))
        if WRITE:
            rec.write({'has_penalty': True, 'certificate_penalty': amount,
                       'penalty_reason': reason or False})
        note('penalty', 'carried')

    if skipped:
        say()
        say("      NOT carried, because the reason says these are advance")
        say("      retention recorded in the penalty box. Once the advance")
        say("      recovery above computes, carrying them would deduct the")
        say("      same money twice. SSC_PENALTIES=all overrides this.")
        say()
        for rec, amount, reason, matched in skipped:
            say("          %-30s %12.2f   %-36s [%s]"
                % ((rec.name or '')[:30], amount, reason[:36],
                   ", ".join(matched)))

    if unexplained:
        say()
        say("      carried, but with no reason recorded against them. Small,")
        say("      and nobody can now say what they were for:")
        for rec, amount in unexplained:
            say("          %-30s %12.2f" % ((rec.name or '')[:30], amount))


# ============================================================ invoice ========
if 'invoice' in STEPS:
    title("the tax invoice, its date, its reference and the notes", '-')

    def file_is_there(attachment):
        if not attachment.store_fname:
            return bool(attachment.db_datas)
        try:
            return os.path.exists(attachment._full_path(attachment.store_fname))
        except Exception:
            return False

    lost = []
    for rec, row in paired:
        values = {}
        if not rec.invoice_ref and g(row, 'x_studio_invoice_ref_no'):
            values['invoice_ref'] = g(row, 'x_studio_invoice_ref_no')
        if not rec.tax_invoice_date and g(row, 'x_studio_tax_invoice_date'):
            values['tax_invoice_date'] = g(row, 'x_studio_tax_invoice_date')
        if not rec.certificate_notes and g(row, 'x_studio_additio'):
            values['certificate_notes'] = g(row, 'x_studio_additio')
        if values:
            if WRITE:
                rec.write(values)
            for name in values:
                note('invoice', name)

        # the file itself, copied rather than read and rewritten
        if rec.tax_invoice:
            note('invoice', 'file already here')
            continue
        source = Attachment.search(
            [('res_model', '=', STUDIO), ('res_id', '=', row.id),
             ('res_field', '=', 'x_studio_tax_invoice')], limit=1)
        if not source:
            continue
        if not file_is_there(source):
            lost.append((rec, source.name, source.store_fname))
            note('invoice', 'file missing from the filestore')
            continue
        if WRITE:
            source.copy({
                'res_model': 'ssc.request',
                'res_id': rec.id,
                'res_field': 'tax_invoice',
                'name': g(row, 'x_studio_tax_invoice_filename')
                or source.name or "Tax Invoice",
            })
        note('invoice', 'file carried')

    if lost:
        say()
        say("      files the database lists and the filestore does not have.")
        say("      Nothing was copied for these - a broken paperclip looks")
        say("      like a document until somebody needs it. They may be fine")
        say("      on production; a staging build does not always bring every")
        say("      file with it.")
        say()
        for rec, name, store in lost:
            say("          %-30s %-24s %s"
                % ((rec.name or '')[:30], (name or '')[:24], store))


# ============================================================= factor ========
if 'factor' in STEPS:
    title("pieces per unit: the factor Studio kept on the sector row", '-')
    item_field = env['ir.model.fields'].sudo().search(               # noqa: F821
        [('model', '=', STUDIO), ('name', '=', 'x_studio_spc_item')], limit=1)
    LineModel = item_field.relation if item_field else None
    if not LineModel or LineModel not in env:                        # noqa: F821
        say("      x_studio_spc_item does not resolve; skipped")
    else:
        TheirLines = env[LineModel].sudo()                           # noqa: F821
        for rec, _row in paired:
            for line in rec.certificate_line_ids:
                if not line.studio_ref_id:
                    continue
                theirs = TheirLines.browse(line.studio_ref_id).exists()
                if not theirs:
                    note('factor', 'no Studio line')
                    continue
                values = {g(sector, 'x_studio_factor', 0.0) or 0.0
                          for sector in (g(theirs, 'x_studio_sectors_1') or [])}
                values.discard(0.0)
                if not values:
                    note('factor', 'no factor on their sectors')
                    continue
                if len(values) > 1:
                    say("      %-30s more than one factor (%s) - skipped"
                        % ((rec.name or '')[:30], sorted(values)))
                    note('factor', 'ambiguous')
                    continue
                factor = list(values)[0]
                if abs((line.pieces_per_unit or 0.0) - factor) < 0.0001:
                    note('factor', 'already right')
                    continue
                if factor != 1.0:
                    say("      %-30s %-34s %s -> %s"
                        % ((rec.name or '')[:30], (line.name or '')[:34],
                           line.pieces_per_unit, factor))
                if WRITE:
                    line.pieces_per_unit = factor
                note('factor', 'set to %s' % factor)


# ======================================================= advance_line ========
if 'advance_line' in STEPS:
    title("the lines that are the advance being drawn, not work done", '-')
    item_field = env['ir.model.fields'].sudo().search(               # noqa: F821
        [('model', '=', STUDIO), ('name', '=', 'x_studio_spc_item')], limit=1)
    LineModel = item_field.relation if item_field else None
    if not LineModel or LineModel not in env:                        # noqa: F821
        say("      x_studio_spc_item does not resolve; skipped")
    else:
        TheirLines = env[LineModel].sudo()                           # noqa: F821
        touched = set()
        for rec, _row in paired:
            for line in rec.certificate_line_ids:
                if not line.studio_ref_id:
                    continue
                theirs = TheirLines.browse(line.studio_ref_id).exists()
                if not theirs:
                    continue
                work = g(theirs, 'x_studio_work_done')
                is_advance = bool(work) and (g(work, 'x_name') or '') ==                     'Advance Payment'
                if line.is_advance_payment == is_advance:
                    note('advance_line', 'already right')
                    continue
                if WRITE:
                    line.is_advance_payment = is_advance
                note('advance_line', 'ticked' if is_advance else 'unticked')
                if is_advance:
                    touched.add(rec)
        for rec in sorted(touched, key=lambda r: r.name or ''):
            say("      %-30s retention %12.2f  recovery %12.2f"
                % ((rec.name or '')[:30], rec.certificate_retention,
                   rec.certificate_advance_recovery))
        if touched:
            say()
            say("      %s certificate(s) now draw the advance. The figures"
                % len(touched))
            say("      above are what they read AFTER the change - both should")
            say("      be zero, and if one is not, the rule did not fire.")


# ============================================================= claims ========
if 'claims' in STEPS:
    title("the sector claims that were never made", '-')
    IrF = env['ir.model.fields'].sudo()                               # noqa: F821
    item_field = IrF.search([('model', '=', STUDIO),
                             ('name', '=', 'x_studio_spc_item')], limit=1)
    LineModel = item_field.relation if item_field else None
    Sector = env.get('ssc.subcontract.sector')                        # noqa: F821
    Claim = env.get('ssc.request.certificate.claim')                  # noqa: F821

    if not LineModel or LineModel not in env or Sector is None:       # noqa: F821
        say("      the models needed are not all here; skipped")
    else:
        TheirLines = env[LineModel].sudo()                            # noqa: F821
        # our sectors, by the Studio row they came from
        ours_by_ref = {sector.studio_ref_id: sector
                       for sector in Sector.sudo().search(
                           [('studio_ref_id', '!=', False)])}
        say("      %s of our sectors carry a Studio id" % len(ours_by_ref))

        unplaced = []
        for rec, _row in paired:
            for line in rec.certificate_line_ids:
                if line.claim_ids or not line.studio_ref_id:
                    continue
                theirs = TheirLines.browse(line.studio_ref_id).exists()
                if not theirs:
                    continue
                rows = g(theirs, 'x_studio_sectors_1') or []
                if not rows:
                    note('claims', 'their line has no sector rows either')
                    continue
                # which column on their sector row points at a sector, and
                # which at a quantity - asked rather than assumed
                links = IrF.search([('model', '=', rows._name),
                                    ('ttype', '=', 'many2one')])
                made_here = 0
                for sector_row in rows:
                    target = None
                    for link in links:
                        candidate = g(sector_row, link.name)
                        if candidate and candidate.id in ours_by_ref:
                            target = ours_by_ref[candidate.id]
                            break
                    quantity = g(sector_row, 'x_studio_quantity', 0.0) or 0.0
                    if not target:
                        unplaced.append((rec, line, sector_row, quantity))
                        continue
                    if not quantity:
                        note('claims', 'nothing claimed on that sector')
                        continue
                    if WRITE:
                        Claim.sudo().create({
                            'line_id': line.id,
                            'sector_id': target.id,
                            'quantity': quantity,
                            'studio_ref_id': sector_row.id,
                            'name': (g(sector_row, 'x_name') or '')[:255],
                        })
                    made_here += 1
                    note('claims', 'made')
                if made_here:
                    say("      %-28s %-30s %s claim(s)"
                        % ((rec.name or '')[:28], (line.name or '')[:30],
                           made_here))

        if unplaced:
            say()
            say("      sector rows whose sector is not on our side. Not")
            say("      invented - a claim against the wrong sector is a")
            say("      quantity charged to the wrong part of the job:")
            say()
            for rec, line, sector_row, quantity in unplaced[:30]:
                say("          %-26s %-26s %-20s qty %s"
                    % ((rec.name or '')[:26], (line.name or '')[:26],
                       (sector_row.display_name or '')[:20], quantity))
            if len(unplaced) > 30:
                say("          ... and %s more" % (len(unplaced) - 30))
            note('claims', 'unplaced')


# ========================================================= consultant ========
if 'consultant' in STEPS:
    title("the consultant's addresses, onto the projects", '-')
    wanted = {}
    for rec, row in paired:
        if not rec.project_id:
            continue
        for studio_name, ours in (
                ('x_studio_consultant_email', 'ssc_consultant_email'),
                ('x_studio_consultant_re_email', 'ssc_consultant_re_email')):
            value = (g(row, studio_name, '') or '').strip()
            if not value:
                continue
            wanted.setdefault((rec.project_id, ours), {})
            found = wanted[(rec.project_id, ours)]
            found[value] = found.get(value, 0) + 1

    for (project, ours), values in sorted(
            wanted.items(), key=lambda kv: (kv[0][0].display_name, kv[0][1])):
        if len(values) > 1:
            say("      %-40s %-26s DISAGREES: %s"
                % (project.display_name[:40], ours,
                   ", ".join("%s on %s" % (v, c) for v, c in values.items())))
            note('consultant', 'certificates disagree')
            continue
        address = list(values)[0]
        if project[ours] == address:
            note('consultant', 'already right')
            continue
        say("      %-40s %-26s %s   (from %s certificate(s))"
            % (project.display_name[:40], ours, address,
               values[address]))
        if WRITE:
            project.sudo().write({ours: address})
        note('consultant', 'set')


# ============================================================ leaving ========
if 'leaving' in STEPS:
    title("how each resignation ends: resigning, or not renewing", '-')
    Studio_all = env[STUDIO].sudo()                                  # noqa: F821
    resignations = Request.with_context(active_test=False).search(
        [('type_code', '=', 'RES')])
    by_studio = {row.id: row for row in
                 Studio_all.with_context(active_test=False).search(
                     [('x_studio_type_of_request_1', '=', 'RES')])}
    WORDS = {'Resigning': 'resign', 'No Renew': 'no_renew'}
    for rec in resignations:
        row = by_studio.get(rec.studio_ref_id)
        if not row:
            note('leaving', 'no Studio row')
            continue
        word = (g(row, 'x_studio_type', '') or '').strip()
        value = WORDS.get(word)
        if not value:
            if word:
                say("      %-30s Studio says %r, which is neither"
                    % ((rec.name or '')[:30], word))
                note('leaving', 'unrecognised word')
            else:
                note('leaving', 'Studio did not say either')
            continue
        if rec.leaving_reason == value:
            note('leaving', 'already right')
            continue
        if WRITE:
            rec.leaving_reason = value
        note('leaving', 'set to %s' % value)


# ============================================================== needed =======
if 'needed' in STEPS:
    title("when the material is needed", '-')
    Studio_all = env[STUDIO].sudo()                                  # noqa: F821
    # every request, not only the certificates - this field is a material
    # request's, and the pairing above is SPC only
    ours_all = {rec.studio_ref_id: rec for rec in
                Request.with_context(active_test=False).search(
                    [('studio_ref_id', '!=', False)])}
    ASAP_WORDS = {'asap', 'a.s.a.p', 'a.s.a.p.', 'urgent', 'immediately',
                  'immediate', 'as soon as possible', 'today', 'now'}
    unreadable = {}
    for row in Studio_all.with_context(active_test=False).search(
            [('x_studio_requirement_date_2', '!=', False)]):
        rec = ours_all.get(row.id)
        if not rec:
            note('needed', 'request not on our side')
            continue
        text = (g(row, 'x_studio_requirement_date_2', '') or '').strip()
        if not text:
            continue
        if text.lower() in ASAP_WORDS:
            note('needed', 'as soon as possible')
            continue
        parsed = None
        for pattern in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y',
                        '%m/%d/%Y', '%d/%m/%y'):
            try:
                parsed = datetime.datetime.strptime(text, pattern).date()
                break
            except ValueError:
                continue
        if not parsed:
            unreadable[text] = unreadable.get(text, 0) + 1
            note('needed', 'not a date and not ASAP')
            continue
        if rec.date_required == parsed:
            note('needed', 'already right')
            continue
        if WRITE:
            rec.date_required = parsed
        note('needed', 'dated')

    if unreadable:
        say("      text that is neither a date nor a way of saying ASAP.")
        say("      Not dropped and not guessed at - somebody who knows the")
        say("      site should say what these meant:")
        say()
        for text in sorted(unreadable, key=lambda k: -unreadable[k])[:40]:
            say("          %-60s on %s request(s)"
                % (text[:60], unreadable[text]))
        if len(unreadable) > 40:
            say("          ... and %s more distinct values"
                % (len(unreadable) - 40))


# ============================================================== the tally ====
# =============================================================== date =======
if 'date' in STEPS:
    title("the date on the certificate", '-')
    if 'certificate_date' not in Request._fields:
        say("      we have no certificate_date field here; upgrade ssc_requests_subcontract first")
        note('date', 'no field')
    else:
        for rec, row in paired:
            theirs = g(row, 'x_studio_date_1')
            if not theirs:
                note('date', 'Studio has none')
                continue
            if hasattr(theirs, 'date'):
                theirs = theirs.date()
            if rec.certificate_date == theirs:
                note('date', 'already right')
                continue
            if rec.certificate_date:
                note('date', 'ours already set, left')
                continue
            if WRITE:
                rec.with_context(tracking_disable=True).write({'certificate_date': theirs})
            note('date', 'set')
        say("      %s carried" % sum(n for (step, what), n in counts.items()
                                     if step == 'date' and what == 'set'))


# ============================================================== price =======
if 'price' in STEPS:
    title("the unit price the certificate agreed, where it is not the contract's", '-')
    say("""      The import priced every certificate line at the contract rate.
      Thirty certificates disagree with Studio's own lines by 0.80 to 77
      dirhams, all on lines where the certificate carried a rate of its
      own - KHAN-211's monthly rates come out at a thirteenth (76.92,
      769.23), which no contract item holds. The certificate's rate is
      what was signed, so it is carried onto the line; a line whose
      quantity also differs is listed and left, because our quantity is
      what the sectors add up to and is not a thing to type over.
""")
    Line = env['ssc.request.certificate.line'].sudo()              # noqa: F821
    Studio_line = env.get('x_all_requests_line_05c8c')             # noqa: F821
    if Studio_line is None:
        say("      x_all_requests_line_05c8c is not on this database")
        note('price', 'no source')
    else:
        studio_line_by_id = {r.id: r for r in
                             Studio_line.sudo().with_context(active_test=False).search([])}
        qty_rows = []
        for line in Line.search([('studio_ref_id', '!=', False)]):
            row = studio_line_by_id.get(line.studio_ref_id)
            if row is None:
                note('price', 'no Studio line')
                continue
            theirs = g(row, 'x_studio_unit_price', 0.0) or 0.0
            their_qty = g(row, 'x_studio_quantity', 0.0) or 0.0
            if abs((line.quantity or 0.0) - their_qty) > 0.001:
                qty_rows.append((line, line.quantity, their_qty))
            if not theirs:
                note('price', 'Studio has no rate')
                continue
            if abs((line.unit_price or 0.0) - theirs) <= 0.005:
                note('price', 'already the same')
                continue
            say("      %-28s %-30s %12.2f -> %12.2f"
                % ((line.request_id.name or '')[:28], (line.name or '')[:30],
                   line.unit_price or 0.0, theirs))
            if WRITE:
                line.write({'unit_price': theirs})
            note('price', 'set to the certificate rate')
        if qty_rows:
            say()
            say("      quantity differs, and is left (ours is what the sectors add up to):")
            for line, mine, theirs in qty_rows[:40]:
                say("      %-28s %-30s ours %10.3f   Studio %10.3f"
                    % ((line.request_id.name or '')[:28], (line.name or '')[:30], mine, theirs))
            if len(qty_rows) > 40:
                say("      ... and %s more" % (len(qty_rows) - 40))
            note('price', 'quantity differs, left')


# =========================================================== quantity =======
if 'quantity' in STEPS:
    title("the claimed quantities, at Studio's precision", '-')
    say("""      The first import wrote every claim through a field rounded to the
      hundredth, so 1.196 months became 1.20 and 19 pieces over four became
      4.75 exactly where Studio held 4.75 - but 1.583 became 1.58. The
      field now keeps six decimals; this writes Studio's figure back over
      every claim that lost something, and the line and the certificate
      recompute from it. Then it lists any line still not matching.
""")
    Claim = env['ssc.request.certificate.claim'].sudo()            # noqa: F821
    Line = env['ssc.request.certificate.line'].sudo()              # noqa: F821
    Studio_claim = env.get('x_all_requests_line_05c8c_line_d44ac')  # noqa: F821
    Studio_line = env.get('x_all_requests_line_05c8c')             # noqa: F821
    if Studio_claim is None or Studio_line is None:
        say("      the Studio line models are not on this database")
        note('quantity', 'no source')
    else:
        their_claim = {r.id: r for r in
                       Studio_claim.sudo().with_context(active_test=False).search([])}
        for claim in Claim.search([('studio_ref_id', '!=', False)]):
            row = their_claim.get(claim.studio_ref_id)
            if row is None:
                note('quantity', 'no Studio claim')
                continue
            theirs = g(row, 'x_studio_quantity', 0.0) or 0.0
            if abs((claim.quantity or 0.0) - theirs) <= 0.0000005:
                note('quantity', 'already exact')
                continue
            if WRITE:
                claim.write({'quantity': theirs})
            note('quantity', 'rewritten at full precision')
        if WRITE:
            env.cr.flush()                                          # noqa: F821
        their_line = {r.id: r for r in
                      Studio_line.sudo().with_context(active_test=False).search([])}
        still = []
        for line in Line.search([('studio_ref_id', '!=', False)]):
            row = their_line.get(line.studio_ref_id)
            if row is None:
                continue
            theirs = g(row, 'x_studio_quantity', 0.0) or 0.0
            if abs((line.quantity or 0.0) - theirs) > 0.0005:
                still.append((line, line.quantity, theirs))
        say("      %s line(s) still differ from Studio's line quantity by more than a thousandth%s"
            % (len(still), '' if WRITE else ' (before the write; run with SSC_WRITE=1)'))
        for line, mine, theirs in still[:40]:
            say("      %-28s %-30s ours %12.6f   Studio %12.6f"
                % ((line.request_id.name or '')[:28], (line.name or '')[:30], mine, theirs))
        if still:
            note('quantity', 'line still differs')


title("what this comes to")
if not counts:
    say("  Nothing to do.")
for step in STEPS:
    rows = [(what, number) for (this_step, what), number in counts.items()
            if this_step == step]
    if not rows:
        continue
    say()
    say("  %s" % step)
    for what, number in sorted(rows, key=lambda r: -r[1]):
        say("      %-46s %s" % (what, number))

title("what to do next")
if not WRITE:
    say("  Nothing was changed. Run it again with SSC_WRITE=1 when the numbers")
    say("  above are the ones you expect, then run tools/reconcile_spc.py and")
    say("  see which of the 74 differences are gone.")
else:
    env.cr.commit()                                              # noqa: F821
    say("  Written. Run tools/reconcile_spc.py now: the retention and advance")
    say("  differences should be gone, and what remains is the argument about")
    say("  progressive payment and the frozen Studio totals - neither of which")
    say("  this tool touched.")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

if not WRITE:
    env.cr.rollback()                                            # noqa: F821
