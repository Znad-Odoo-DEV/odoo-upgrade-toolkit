"""What a site payment certificate actually holds, on both sides.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/profile_spc_requests.py

    SSC_TYPE=SPC        which kind of request to profile (default SPC)
    SSC_OUT=~/spc.md

Reads only.

Two hundred and six requests are payment certificates and the button that
prints one produces a blank sheet - the Studio report's whole body is
<div class="page"><div class="oe_structure"/></div>. So unlike the material
requisition, the advance and the resignation letter, there is nothing to carry
across. The page has to be designed.

A payment certificate goes to a client. It says what work was done this month,
what is held back, what is recovered against the advance, and what is
therefore payable - and somebody signs it. Designing that from an idea of what
such a document usually says would produce a document this office does not
use.

So this asks the records instead. For the certificates only - not for all
eleven hundred requests - it prints which Studio fields are filled and how
often, which of our own fields are filled, and what is on the lines. A field
filled on two hundred of two hundred and six belongs on the page. A field
filled on three does not, whatever it is called.

Counting is by reading the value, not COUNT(column): false is not NULL, and a
binary field with attachment=True has nothing in its column at all.
"""
import os

TYPE = os.environ.get('SSC_TYPE') or 'SPC'
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/spc.md')

STUDIO = 'x_all_requests'
STUDIO_TYPE_FIELD = 'x_studio_type_of_request_1'

PLUMBING = {
    'id', 'create_uid', 'create_date', 'write_uid', 'write_date',
    'display_name', '__last_update', 'message_ids', 'message_follower_ids',
    'message_partner_ids', 'activity_ids', 'website_message_ids',
    'message_main_attachment_id', 'rating_ids',
}

IrField = env['ir.model.fields'].sudo()                          # noqa: F821

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say()
    say(rule * 96)
    say(text)
    say(rule * 96)


def finish():
    with open(OUT, 'w', encoding='utf-8') as handle:
        handle.write("\n".join(report))
    print("\nwritten to %s" % OUT)
    raise SystemExit


def fill_counts(records, model_name):
    """field name -> (ttype, how many of these records hold something, samples)"""
    answer = {}
    fields = IrField.search([('model', '=', model_name)])
    for field in fields:
        if field.name in PLUMBING:
            continue
        count, samples = 0, []
        for record in records:
            try:
                value = record[field.name]
            except Exception:
                break
            if not value:
                continue
            count += 1
            if len(samples) < 2:
                if field.ttype == 'binary':
                    samples.append("<%s bytes>" % len(value))
                elif field.ttype in ('many2one', 'many2many', 'one2many'):
                    samples.append((value.display_name or '')[:40]
                                   if field.ttype == 'many2one'
                                   else "%s row(s)" % len(value))
                else:
                    samples.append(str(value)[:40])
        if count:
            answer[field.name] = (field.ttype, count, samples,
                                  field.field_description)
    return answer


def print_fills(fills, total, floor=0):
    for name in sorted(fills, key=lambda k: -fills[k][1]):
        ttype, count, samples, label = fills[name]
        if count <= floor:
            continue
        say("      %-42s %-10s %4s  %3.0f%%  %s"
            % (name[:42], ttype, count, 100.0 * count / total if total else 0,
               label[:26]))
        if samples:
            say("      %-42s        e.g. %s" % ('', " | ".join(samples)))


title("what a %s holds" % TYPE)

# ------------------------------------------------------------ the Studio side
if STUDIO in env:                                                # noqa: F821
    Studio = env[STUDIO].sudo()                                  # noqa: F821
    rows = Studio.with_context(active_test=False).search(
        [(STUDIO_TYPE_FIELD, '=', TYPE)])
    say()
    say("  Studio: %s row(s) of type %s" % (len(rows), TYPE))
    say()
    say("  Every field with something in it, most filled first. A field filled")
    say("  on nearly all of them is a field the page needs; one filled on a")
    say("  handful is somebody's afternoon, whatever it is called.")
    say()
    print_fills(fill_counts(rows, STUDIO), len(rows))
else:
    say()
    say("  %s is not on this database." % STUDIO)

# --------------------------------------------------------------- our own side
if 'ssc.request' in env:                                         # noqa: F821
    Request = env['ssc.request'].sudo()                          # noqa: F821
    ours = Request.with_context(active_test=False).search(
        [('type_code', '=', TYPE)])
    title("and what came across onto ssc.request", '-')
    say("  %s request(s) of type %s on our side" % (len(ours), TYPE))
    say()
    print_fills(fill_counts(ours, 'ssc.request'), len(ours))

    # the lines, which is where a certificate says what the money is for
    if ours and 'certificate_line_ids' in Request._fields:
        lines = ours.mapped('certificate_line_ids')
        title("the certificate lines", '-')
        say("  %s line(s) across %s certificate(s), %s of which have any"
            % (len(lines), len(ours),
               len(ours.filtered('certificate_line_ids'))))
        say()
        if lines:
            print_fills(fill_counts(lines, lines._name), len(lines))

title("what this decides")
say("""  The page is designed from the left hand column above and nothing else.

  A payment certificate is a document a client is asked to pay against, so
  the parts of it that carry money have to be the computed ones - gross,
  retention, advance recovery, penalty, VAT, net - and not a set of columns
  somebody types beside each other. If the profile shows those filled on our
  side, the page can be built today. If it shows them empty on records that
  Studio filled by hand, the import has a hole in it and that is the thing to
  fix first: a certificate that prints a net of zero is worse than one that
  does not print.
""")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
