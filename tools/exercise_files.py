"""An uploaded file lands in the chatter, where somebody can find it."""
import base64

Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
Attachment = env['ir.attachment']                                 # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-64s %s" % (label, detail))


def a_file(text):
    return base64.b64encode(text.encode())


def visible_on(record):
    """The attachments a person can see - not the field's own storage."""
    return Attachment.search([
        ('res_model', '=', 'ssc.request'),
        ('res_id', '=', record.id),
        ('res_field', '=', False),
    ])


# --- both bridges contribute, neither replaces the other ----------------------
declared = Request._visible_files()
check("the payroll bridge's two documents are declared",
      'ticket_quotation' in declared and 'signed_nor' in declared, declared)
check("and the subcontract bridge's tax invoice with them",
      'tax_invoice' in declared,
      "one bridge overwrote the other" if 'tax_invoice' not in declared
      else declared)
check("three in all, from two modules that each know only their own",
      len(declared) == 3, len(declared))

alr = Type.search([('code', '=', 'ALR')], limit=1)
res = Type.search([('code', '=', 'RES')], limit=1) or alr

# --- uploaded on creation ------------------------------------------------------
leave = Request.create({
    'request_type_id': alr.id, 'description': "Annual leave",
    'ticket_quotation': a_file("a quote for a ticket"),
    'ticket_quotation_filename': "ticket-quote.pdf",
})
files = visible_on(leave)
check("a file given at creation is in the chatter",
      len(files) == 1, "%s attachment(s)" % len(files))
check("under the name it was uploaded with",
      files.name == 'ticket-quote.pdf', files.name)
check("and a message says it arrived",
      any('Ticket Quotation' in (m.body or '') for m in leave.message_ids),
      "no message" if not leave.message_ids else "said so")

# --- uploaded later ------------------------------------------------------------
leave.write({'signed_nor': a_file("a signed notice"),
             'signed_nor_filename': "notice.pdf"})
files = visible_on(leave)
check("a file uploaded later joins it", len(files) == 2,
      ", ".join(sorted(files.mapped('name'))))

# --- the same file twice is not two attachments --------------------------------
leave.write({'signed_nor': a_file("a signed notice"),
             'signed_nor_filename': "notice.pdf"})
check("writing the same file again does not make a second copy",
      len(visible_on(leave)) == 2, len(visible_on(leave)))

# --- a replacement under a new name is a new document --------------------------
leave.write({'signed_nor': a_file("a corrected notice"),
             'signed_nor_filename': "notice-v2.pdf"})
check("a replacement under a new name is kept beside the first",
      len(visible_on(leave)) == 3,
      ", ".join(sorted(visible_on(leave).mapped('name'))))

# --- a field with no filename still gets a sensible one -------------------------
plain = Request.create({
    'request_type_id': alr.id, 'description': "No filename given",
    'ticket_quotation': a_file("something"),
})
names = visible_on(plain).mapped('name')
check("a file with no filename is named after its field",
      names and 'Ticket Quotation' in names[0], names)

# --- nothing uploaded, nothing said ---------------------------------------------
quiet = Request.create({'request_type_id': alr.id,
                        'description': "Nothing attached"})
check("a request with no file has no attachment", not visible_on(quiet),
      len(visible_on(quiet)))

# --- writing something else does not republish -----------------------------------
before = len(visible_on(leave))
leave.description = "Annual leave, corrected"
check("editing another field does not attach anything again",
      len(visible_on(leave)) == before, len(visible_on(leave)))

# --- the file is still readable from its field ------------------------------------
check("and the field itself still holds the file",
      bool(leave.signed_nor), "held" if leave.signed_nor else "lost")

print()
print("PASS  %s" % len(ok))
for line in ok:
    print("   ok   %s" % line)
if bad:
    print()
    print("FAIL  %s" % len(bad))
    for line in bad:
        print("   XX   %s" % line)
else:
    print()
    print("nothing failed")

env.cr.rollback()                                                  # noqa: F821
print("rolled back")
