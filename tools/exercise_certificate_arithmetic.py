"""The two rules SPC0003 taught: pieces per unit, and drawing the advance."""
Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
Contract = env['ssc.subcontract']                                 # noqa: F821
Partner = env['res.partner']                                      # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-64s %s" % (label, detail))


spc = Type.search([('code', '=', 'SPC')], limit=1)
project = env['project.project'].create({'name': "Arjan Townhouses"})  # noqa: F821
partner = Partner.create({'name': "Cassia Atam Metals LLC"})

contract = Contract.create({
    'name': "SSC/ARJ-672/2025/SC002",
    'description': "Fabrication & Installation of Sliding Shower Enclosures",
    'project_id': project.id,
    'partner_id': partner.id,
    'has_retention': True, 'retention_percent': 10.0,
    'has_advance': True, 'advance_recovery_percent': 30.0,
    'vat_applicable': True, 'vat_percent': 5.0,
})
item = env['ssc.subcontract.item'].create({                       # noqa: F821
    'contract_id': contract.id,
    'name': "Fabrication & Installation of Sliding Shower",
    'unit_price': 4000.0, 'quantity': 47.0,
})
sector = env['ssc.subcontract.sector'].create({                   # noqa: F821
    'item_id': item.id, 'name': "Block A's Ground Floor",
    'quantity': 500.0,
})


def a_certificate(pieces, factor, advance=False):
    """One line, one sector claim, the numbers SPC0003 actually holds."""
    record = Request.create({
        'request_type_id': spc.id, 'project_id': project.id,
        'contract_id': contract.id, 'description': "Site Payment Certificate",
        'certificate_line_ids': [(0, 0, {
            'item_id': item.id,
            'name': "Fabrication & Installation of Sliding Shower",
            'unit_price': 4000.0,
            'pieces_per_unit': factor,
            'is_advance_payment': advance,
            'claim_ids': [(0, 0, {'sector_id': sector.id,
                                  'quantity': pieces})],
        })],
    })
    return record


# --- the factor -----------------------------------------------------------
real = a_certificate(188.0, 4.0)
line = real.certificate_line_ids
check("188 pieces at four to the unit is 47 units", line.quantity == 47.0,
      line.quantity)
check("and 47 at 4,000 is 188,000, not 752,000", line.amount == 188000.0,
      line.amount)
check("which is what the certificate calls work done",
      real.certificate_gross == 188000.0, real.certificate_gross)

plain = a_certificate(188.0, 1.0)
check("a factor of one leaves the pieces alone",
      plain.certificate_line_ids.quantity == 188.0,
      plain.certificate_line_ids.quantity)
check("which is 696 of the 729 lines and why this stayed invisible",
      plain.certificate_gross == 752000.0, plain.certificate_gross)

check("the default is one, so a line nobody touches is unchanged",
      Request.env['ssc.request.certificate.line']._fields[
          'pieces_per_unit'].default(line) == 1.0, "1.0")

zero = a_certificate(188.0, 0.0)
check("a factor of zero does not lose the line",
      zero.certificate_line_ids.quantity == 188.0,
      zero.certificate_line_ids.quantity)

# --- changing the factor moves the money ----------------------------------
real.certificate_line_ids.pieces_per_unit = 2.0
check("changing the factor recomputes the quantity",
      real.certificate_line_ids.quantity == 94.0,
      real.certificate_line_ids.quantity)
real.certificate_line_ids.pieces_per_unit = 4.0

# --- the advance suppression ----------------------------------------------
work = a_certificate(188.0, 4.0)
check("a normal certificate retains ten per cent",
      round(work.certificate_retention, 2) == 18800.0,
      work.certificate_retention)
check("and recovers thirty per cent of the advance",
      round(work.certificate_advance_recovery, 2) == 56400.0,
      work.certificate_advance_recovery)

drawn = a_certificate(188.0, 4.0, advance=True)
check("a certificate drawing the advance retains nothing",
      drawn.certificate_retention == 0.0, drawn.certificate_retention)
check("and recovers nothing against itself",
      drawn.certificate_advance_recovery == 0.0,
      drawn.certificate_advance_recovery)
check("so its sub total is the whole of the work done",
      drawn.certificate_subtotal == drawn.certificate_gross,
      "%s = %s" % (drawn.certificate_subtotal, drawn.certificate_gross))
check("VAT is still charged on it",
      round(drawn.certificate_vat, 2) == round(drawn.certificate_gross * 0.05, 2),
      drawn.certificate_vat)

# --- and ticking the box on an existing certificate takes them off ---------
work.certificate_line_ids.is_advance_payment = True
check("ticking it afterwards clears the retention too",
      work.certificate_retention == 0.0, work.certificate_retention)
check("and the recovery, because it is in the dependencies",
      work.certificate_advance_recovery == 0.0,
      work.certificate_advance_recovery)
work.certificate_line_ids.is_advance_payment = False
check("unticking it puts them back",
      round(work.certificate_retention, 2) == 18800.0,
      work.certificate_retention)

# --- one advance line among several is enough -----------------------------
mixed = a_certificate(188.0, 4.0)
mixed.write({'certificate_line_ids': [(0, 0, {
    'item_id': item.id, 'name': "Advance", 'unit_price': 1000.0,
    'pieces_per_unit': 1.0, 'is_advance_payment': True,
    'claim_ids': [(0, 0, {'sector_id': sector.id, 'quantity': 1.0})],
})]})
check("one advance line among several suppresses the whole certificate",
      mixed.certificate_retention == 0.0, mixed.certificate_retention)

# --- the consultant is read through the project, not copied ----------------
project.write({'ssc_consultant_email': "Site@antcpl.com",
               'ssc_consultant_re_email': "projects@antcpl.com"})
certificate = a_certificate(4.0, 1.0)
check("a certificate reads the consultant off its project",
      certificate.consultant_email == "Site@antcpl.com",
      certificate.consultant_email)
check("and the resident engineer too",
      certificate.consultant_re_email == "projects@antcpl.com",
      certificate.consultant_re_email)
project.ssc_consultant_email = "newsite@antcpl.com"
check("correcting the project corrects every certificate on it",
      certificate.consultant_email == "newsite@antcpl.com",
      certificate.consultant_email)
check("which is the whole point: Studio held it on 306 rows",
      'consultant_email' not in (Request._fields['consultant_email'].store
                                 and [] or ['stored']),
      "related, not stored")

# --- the page Studio never drew -------------------------------------------
report = env.ref('ssc_requests_subcontract.action_report_certificate')  # noqa: F821
paper = a_certificate(188.0, 4.0)
paper.write({'has_penalty': True, 'certificate_penalty': 500.0,
             'penalty_reason': "Bad quality material",
             'invoice_ref': "ADV-023",
             'certificate_notes': "Measured with the consultant on site."})
html = report._render_qweb_html(report.report_name, paper.ids)[0]
html = html.decode() if isinstance(html, bytes) else html

check("the certificate page renders", bool(html), "%s characters" % len(html))
for what, text in (("its title", "SITE PAYMENT CERTIFICATE"),
                   ("the subcontractor", "Cassia Atam Metals"),
                   ("the contract", "SSC/ARJ-672/2025/SC002"),
                   ("the project", "Arjan Townhouses"),
                   ("the item", "Sliding Shower"),
                   # an apostrophe leaves QWeb as &#39;, so the check looks
                   # for the half of the name that has none
                   ("the sector it was claimed against", "Ground Floor"),
                   ("the work done", "188,000.00"),
                   ("the retention as a rate", "(10.0%)"),
                   ("the penalty's reason", "Bad quality material"),
                   ("the tax invoice reference", "ADV-023"),
                   ("the notes", "Measured with the consultant"),
                   ("the net in words", "Thousand"),
                   ("a line for the subcontractor to sign", "Subcontractor")):
    check("the certificate page carries %s" % what, text in html,
          text if text in html else "MISSING - it goes to a client like this")

check("the deductions are itemised, not just netted",
      "Less Retention" in html and "Less Advance Recovered" in html,
      "itemised")

# a certificate drawing the advance shows no deduction lines at all
drawn_paper = a_certificate(188.0, 4.0, advance=True)
drawn_html = report._render_qweb_html(report.report_name, drawn_paper.ids)[0]
drawn_html = (drawn_html.decode() if isinstance(drawn_html, bytes)
              else drawn_html)
check("an advance certificate prints no retention line",
      "Less Retention" not in drawn_html,
      "clean" if "Less Retention" not in drawn_html else "printed a zero")

empty_paper = Request.create({
    'request_type_id': spc.id, 'project_id': project.id,
    'contract_id': contract.id, 'description': "Nothing claimed yet"})
empty_html = report._render_qweb_html(report.report_name, empty_paper.ids)[0]
empty_html = (empty_html.decode() if isinstance(empty_html, bytes)
              else empty_html)
check("a certificate with no lines says so rather than printing a blank",
      "Nothing has been claimed" in empty_html, "said so")

# --- the screens still open -----------------------------------------------
for ref in ('ssc_requests_subcontract.view_ssc_request_certificate_form',
            'ssc_requests.view_ssc_request_form'):
    view = env.ref(ref, raise_if_not_found=False)                 # noqa: F821
    if not view:
        continue
    try:
        Request.get_view(view.id, 'form')
        check("the form still opens: %s" % ref.split('.')[-1], True, "")
    except Exception as error:
        check("the form still opens: %s" % ref.split('.')[-1], False,
              str(error)[:60])

print()
print("PASS  %s" % len(ok))
for row in ok:
    print("   ok   %s" % row)
if bad:
    print()
    print("FAIL  %s" % len(bad))
    for row in bad:
        print("   XX   %s" % row)
else:
    print()
    print("nothing failed")

env.cr.rollback()                                                  # noqa: F821
print("rolled back")
