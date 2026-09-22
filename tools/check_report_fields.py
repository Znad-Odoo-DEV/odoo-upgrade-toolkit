"""The fields the Studio reports print: does anybody actually fill them?

    odoo-bin shell --no-http --shell-interface=python \
        < tools/check_report_fields.py

    SSC_OUT=~/report_fields.md

Reads only.

dump_studio_reports.py said what the three working reports put on the page.
This says, for each of those fields, how many rows have ever held a value -
because a signature box on a printed page means one of two things, and they
lead to opposite decisions.

If the signature images are filled, they are the reason the page is printed at
all and three binary fields have to be built. If they are empty, the office
signs the paper with a pen, and building three image fields nobody uploads to
adds three columns and a wet-signature workflow that never existed.

Counting is done by reading the value, not by COUNT(column). COUNT counts
non-NULL, false is not NULL, and that is how an untouched checkbox once read
as a filled field on 1,140 rows.
"""
import os

OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/report_fields.md')

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say()
    say(rule * 96)
    say(text)
    say(rule * 96)


# what the three working reports print, and why each one is being asked about
QUESTIONS = [
    ('x_studio_submitted_signature',
     "MR: the requester's signature box"),
    ('x_studio_site_eng_signature',
     "MR: the site engineer's signature box"),
    ('x_studio_project_manger_signature',
     "MR: the project manager's signature box"),
    ('x_studio_will_be_repaid_by',
     "Advance: 'Received in full by'"),
    ('x_studio_repayment_summary_in_words',
     "Advance: the repayment summary - we hold installments instead"),
    ('x_studio_amount_in_words',
     "Advance: the amount spelled - a report can spell it"),
    ('x_studio_requested_by_1',
     "MR: the name under 'Submitted by'"),
    ('x_studio_requested_by_2',
     "MR and Advance: the name beside 'Requested By'"),
    ('x_studio_approved_by',
     "MR: the name under 'Site Engineer'"),
    ('x_studio_approved_by_1',
     "MR: the name under 'Project Manager'"),
    ('x_studio_profession',
     "Resignation letter: the line under the name"),
    ('x_studio_todays_date',
     "Resignation letter: the date at the top"),
    ('x_studio_project_id',
     "MR and Advance: the project's own code"),
]

# and the line model, whose one2many the MR table walks
LINE_QUESTIONS = [
    ('x_name', "MR table: the 'SN Of Item' column"),
    ('x_studio_unit', "MR table: the 'Unit' column - we read it off the product"),
    ('x_studio_stock_available',
     "MR table: 'Stock Available' - ours is computed from the warehouse"),
    ('x_studio_previous_requests_quantity',
     "MR table: 'Previous Requests Quantity' - ours is computed"),
]

# The MR table walks o.x_studio_one2many_field_9eg_1ibh9vbtm, and asking
# x_items_needed instead answered about 47 rows on a model the report never
# opens. The field is resolved rather than guessed at.
LINE_FIELD = 'x_studio_one2many_field_9eg_1ibh9vbtm'

# the three signature boxes, asked about together further down
SIGNATURES = ('x_studio_submitted_signature',
              'x_studio_site_eng_signature',
              'x_studio_project_manger_signature')

IrField = env['ir.model.fields'].sudo()                          # noqa: F821


def described(model_name, field_name):
    field = IrField.search([('model', '=', model_name),
                            ('name', '=', field_name)], limit=1)
    return field


def filled(model_name, field_name, limit_samples=3):
    """How many rows hold something, and what a few of them look like.

    Read rather than counted in SQL. A binary field with attachment=True has
    nothing in its column at all - the file is in ir.attachment - so a SQL
    count of that column answers zero on a model where every row has a file.
    """
    field = described(model_name, field_name)
    if not field:
        return None, None, []
    Model = env[model_name].sudo()                               # noqa: F821
    rows = Model.with_context(active_test=False).search([])
    count, samples = 0, []
    for row in rows:
        try:
            value = row[field_name]
        except Exception:
            continue
        if not value:
            continue
        count += 1
        if len(samples) < limit_samples:
            if field.ttype == 'binary':
                samples.append("<%s bytes>" % len(value))
            elif field.ttype in ('many2one',):
                samples.append(value.display_name)
            else:
                samples.append(str(value)[:60])
    return field, count, samples


def ask(model_name, questions):
    if model_name not in env:                                    # noqa: F821
        say()
        say("  %s is not on this database." % model_name)
        return
    total = env[model_name].sudo().with_context(                 # noqa: F821
        active_test=False).search_count([])
    say()
    say("  %s   -   %s row(s)" % (model_name, total))
    say()
    for field_name, why in questions:
        field, count, samples = filled(model_name, field_name)
        if field is None:
            say("      %-42s NOT A FIELD ON THIS MODEL" % field_name)
            say("      %-42s   %s" % ('', why))
            continue
        share = (100.0 * count / total) if total else 0.0
        verdict = ("nobody ever filled it" if not count
                   else "%s row(s), %.0f%%" % (count, share))
        say("      %-42s %-10s %s" % (field_name, field.ttype, verdict))
        say("      %-42s   %s" % ('', why))
        if samples:
            say("      %-42s   e.g. %s" % ('', " | ".join(samples)))
        say()


title("what the printed pages read, and whether anybody fills it")
say("  A field nobody has ever filled is not carried. A signature box that is")
say("  always empty means the office signs with a pen, and building an image")
say("  field for it invents a workflow that never existed.")

ask('x_all_requests', QUESTIONS)

# ------------------------------------------------------- the many2one targets
title("what the many2one fields on the page actually point at", '-')
say("  Two 'requested by' fields, filled 96% and 41% of the time, are not two")
say("  spellings of one thing. What each points at says which is the person")
say("  who typed the request and which is the person it is for.")
say()
for field_name in ('x_studio_requested_by_1', 'x_studio_requested_by_2',
                   'x_studio_approved_by', 'x_studio_approved_by_1',
                   'x_studio_requested_for'):
    field = described('x_all_requests', field_name)
    if field:
        say("      %-40s -> %s" % (field_name, field.relation))
    else:
        say("      %-40s not a field here" % field_name)

# --------------------------------------------------------- the real line model
title("the line model the MR table walks", '-')
line_field = described('x_all_requests', LINE_FIELD)
if not line_field:
    say("      %s is not a field on x_all_requests" % LINE_FIELD)
else:
    say("      %s  ->  %s" % (LINE_FIELD, line_field.relation))
    ask(line_field.relation, LINE_QUESTIONS)

# ---------------------------------------------- how many signatures there are
title("how many DIFFERENT signatures there are", '-')
say("""  This is the question, not how many rows are filled. Eight hundred and
  seventy-three filled rows mean one of two things and they lead to opposite
  designs.

  If there are a handful of distinct images, a signature is a PERSON'S
  signature, stored once and stamped onto every request they touch. Then it
  belongs on the employee or the user - one image, one place - and the report
  reads it through the approver, the way the nationality is read through the
  employee rather than copied onto eleven hundred rows.

  If there are hundreds, people sign each request individually on a screen,
  and the image belongs on the request because each one is a different mark.

  The first sample of each field came back the same size three times running,
  which is what made this worth counting.
""")

if 'x_all_requests' in env:                                      # noqa: F821
    Requests = env['x_all_requests'].sudo()                      # noqa: F821
    Attachment = env['ir.attachment'].sudo()                     # noqa: F821
    for field_name in SIGNATURES:
        if not described('x_all_requests', field_name):
            continue
        # a checksum is already computed for anything in ir.attachment, so ask
        # there first rather than reading a thousand images to hash them
        stored = Attachment.search([('res_model', '=', 'x_all_requests'),
                                    ('res_field', '=', field_name)])
        if stored:
            marks = {}
            for attachment in stored:
                marks[attachment.checksum] = marks.get(attachment.checksum, 0) + 1
        else:
            import hashlib
            marks = {}
            for row in Requests.with_context(active_test=False).search([]):
                value = row[field_name]
                if not value:
                    continue
                key = hashlib.sha1(bytes(value)).hexdigest()
                marks[key] = marks.get(key, 0) + 1
        say("      %-42s %s distinct image(s) across %s row(s)"
            % (field_name, len(marks), sum(marks.values())))
        for key in sorted(marks, key=lambda k: -marks[k])[:6]:
            say("      %-42s     %-12s used %s time(s)"
                % ('', key[:12], marks[key]))
        say()

# ------------------------------------------------- which reports matter at all
title("how many requests of each kind there are", '-')
say("  The first attempt at this took the first many2one pointing at")
say("  x_requesttypes and got '(none)' on all 1,149 rows - so it had picked a")
say("  field nobody fills. Every candidate is counted now, and the one that")
say("  is filled is the one the requests are actually classified by.")
say()
if 'x_all_requests' in env:                                      # noqa: F821
    Requests = env['x_all_requests'].sudo()                      # noqa: F821
    candidates = IrField.search([('model', '=', 'x_all_requests'),
                                 ('ttype', 'in', ('many2one', 'selection')),
                                 '|', ('relation', '=', 'x_requesttypes'),
                                 ('name', 'ilike', 'type')])
    rows = Requests.with_context(active_test=False).search([])
    if not candidates:
        say("      nothing on x_all_requests looks like a request type")
    for candidate in candidates:
        counts = {}
        for row in rows:
            value = row[candidate.name]
            if not value:
                continue
            label = value.display_name if candidate.ttype == 'many2one' \
                else str(value)
            counts[label] = counts.get(label, 0) + 1
        say("      %s   (%s -> %s)"
            % (candidate.name, candidate.ttype, candidate.relation or ''))
        if not counts:
            say("          nobody ever filled it")
        for label in sorted(counts, key=lambda k: -counts[k])[:20]:
            say("          %-42s %s" % (label[:42], counts[label]))
        say()

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
