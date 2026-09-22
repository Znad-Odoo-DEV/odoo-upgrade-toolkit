"""The signatures stamped onto every request, gathered onto the people.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/migrate_studio_signatures.py

    SSC_WRITE=1     actually write; without it nothing is saved
    SSC_OUT=~/signatures.md

Dry by default.

x_all_requests carries three signature images - the requester's, the site
engineer's, the project manager's - filled on 873, 801 and 853 of 1,149 rows.
Behind those two and a half thousand filled boxes there are seven, seven and
four distinct pictures, and the same picture appears under different fields on
different requests: ef57bc358ae3 signs as the requester on one page and as the
site engineer on another.

So a signature is not a property of a box on a page. It is a property of a
person, and Studio was copying it onto every request they touched. This reads
the pairs - who signed, and with what - and gives each person their signature
once, on res.users.

Each of the three boxes has a user field beside it, so the pairing is read
rather than guessed:

    x_studio_requested_by_1   with  x_studio_submitted_signature
    x_studio_approved_by      with  x_studio_site_eng_signature
    x_studio_approved_by_1    with  x_studio_project_manger_signature

A person who signed with two different pictures gets the one they used most,
and both are reported with their counts - somebody redrawing their signature
last year is the ordinary reason, and it is not something to decide silently.

Nobody's existing signature is overwritten. A person who has already uploaded
one has said what they want printed.
"""
import os

WRITE = os.environ.get('SSC_WRITE') == '1'
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/signatures.md')

SOURCE = 'x_all_requests'

# the three boxes, each as (the user who signed, the image they signed with)
PAIRS = [
    ('x_studio_requested_by_1', 'x_studio_submitted_signature', "requester"),
    ('x_studio_approved_by', 'x_studio_site_eng_signature', "site engineer"),
    ('x_studio_approved_by_1', 'x_studio_project_manger_signature',
     "project manager"),
]

IrField = env['ir.model.fields'].sudo()                          # noqa: F821
Attachment = env['ir.attachment'].sudo()                         # noqa: F821
Users = env['res.users'].sudo()                                  # noqa: F821

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


title("gathering the signatures onto the people who signed")
say("  %s" % ("WRITING" if WRITE else "dry run - nothing will be saved"))

if SOURCE not in env:                                            # noqa: F821
    say()
    say("  %s is not on this database." % SOURCE)
    finish()
if 'ssc_signature' not in Users._fields:
    say()
    say("  res.users has no ssc_signature - ssc_requests is not installed")
    say("  here, or it is an older version than the one that added it.")
    finish()

Source = env[SOURCE].sudo()                                      # noqa: F821

# ------------------------------------------------ who signed with what, and how often
# user id -> {image bytes: how many requests they signed with it}
marks = {}
names = {}
missing = []

for user_field, image_field, role in PAIRS:
    if not IrField.search([('model', '=', SOURCE), ('name', '=', user_field)]):
        missing.append(user_field)
        continue
    if not IrField.search([('model', '=', SOURCE), ('name', '=', image_field)]):
        missing.append(image_field)
        continue

    # The image lives in ir.attachment, keyed by the row it hangs off, so the
    # rows are read once and the pictures fetched in one search rather than
    # eleven hundred times.
    rows = Source.with_context(active_test=False).search(
        [(user_field, '!=', False)])
    signer_of = {row.id: row[user_field] for row in rows}
    for attachment in Attachment.search([('res_model', '=', SOURCE),
                                         ('res_field', '=', image_field),
                                         ('res_id', 'in', list(signer_of))]):
        signer = signer_of.get(attachment.res_id)
        if not signer:
            continue
        data = attachment.datas
        if not data:
            continue
        by_image = marks.setdefault(signer.id, {})
        by_image[data] = by_image.get(data, 0) + 1
        names[signer.id] = signer.name

title("what was found", '-')
if missing:
    say("  fields that are not on this database, and were skipped:")
    for name in missing:
        say("      %s" % name)
    say()
say("  %s person(s) signed something" % len(marks))

# ------------------------------------------------------------- give it to them
made, skipped, disagreed = 0, 0, []

title("person by person", '-')
for user_id in sorted(marks, key=lambda uid: names.get(uid, '')):
    user = Users.browse(user_id).exists()
    if not user:
        continue
    by_image = marks[user_id]
    best = max(by_image, key=lambda data: by_image[data])
    total = sum(by_image.values())

    if user.ssc_signature:
        skipped += 1
        say("      %-34s already has one, left alone" % user.name[:34])
        continue

    if len(by_image) > 1:
        disagreed.append((user.name, sorted(by_image.values(), reverse=True)))

    say("      %-34s %s request(s), %s picture(s), taking the one used %s time(s)"
        % (user.name[:34], total, len(by_image), by_image[best]))
    if WRITE:
        user.ssc_signature = best
    made += 1

title("what this comes to")
say("  %-6s person(s) given a signature" % made)
say("  %-6s left alone, having uploaded their own already" % skipped)
say("  %-6s signed with more than one picture" % len(disagreed))

if disagreed:
    say()
    say("  More than one picture is usually somebody redrawing their")
    say("  signature. The most used one is taken; these are the ones to look")
    say("  at if a printed page ever carries the wrong mark:")
    say()
    for name, counts in disagreed:
        say("      %-34s used %s"
            % (name[:34], " and ".join("%s time(s)" % c for c in counts)))

title("what to do next")
if not WRITE:
    say("  Nothing was saved. Run it again with SSC_WRITE=1 when the names")
    say("  and counts above are the ones you expect.")
else:
    env.cr.commit()                                              # noqa: F821
    say("  Saved. Open a person's preferences and check the picture is theirs,")
    say("  then print one old material request and compare it with the same")
    say("  page printed out of Studio before x_all_requests is deleted.")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

if not WRITE:
    env.cr.rollback()                                            # noqa: F821
