"""Which attachments came across as an addition when they are a deduction?

    SSC_WRITE=1 odoo-bin shell --no-http < tools/check_attachment_signs.py

Until this afternoon _sync_payslip_attachments fell back to "salary addition"
whenever a Studio type name did not match one of ours. An unrecognised deduction
therefore arrived as an addition: the same figure with the sign the wrong way
round, on a payslip nobody is going to re-read.

4,199 payslips came across under that rule. Re-importing corrects the ones it
touches, because the mirror finds an attachment by name and rewrites its type -
but it only corrects what it walks past, and an attachment whose Studio line is
gone, or whose payslip did not come across, is not walked past at all.

So this looks at the result rather than the process: every ssc.attachment
recorded as an addition, asked whether the record it came from says otherwise.
The evidence is the value being negative, the factor being negative, or an
advance or a fine standing behind it - the three things the import itself uses.

Read the list before writing. A wrong sign here is money on a payslip, and the
only thing worse than finding these is correcting one that was right.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

SOURCE = 'x_attachments_list'

cr = env.cr                                                      # noqa: F821
Attachment = env['ssc.attachment'].sudo()                        # noqa: F821
Source = env.get(SOURCE)                                         # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def _get(record, name):
    if not record or name not in record._fields:
        return False
    return record[name]


title("1. what the types say")

types = env['ssc.attachment.type'].sudo().search([])              # noqa: F821
for att_type in types.sorted('name'):
    count = Attachment.search_count([('type_id', '=', att_type.id)])
    print("  %-40s %-10s %s attachment(s)" % (att_type.name[:40], att_type.kind, count))

additions = Attachment.search([('type_id.kind', '=', 'addition')])
deductions = Attachment.search([('type_id.kind', '=', 'deduction')])
print("\n  %s addition(s), %s deduction(s)" % (len(additions), len(deductions)))


title("2. additions that look like deductions")

# An attachment made by the payslip mirror carries no studio_ref_id of its own -
# it was built from a line inside the payslip, not from x_attachments_list - so
# the value is the only evidence there, and it is enough: nobody records an
# addition of minus three hundred.
negative = additions.filtered(lambda a: (a.value or 0) < 0)
print("  %s addition(s) hold a negative value" % len(negative))

# The ones that do come from x_attachments_list can be asked directly.
from_studio = additions.filtered('studio_ref_id')
mismatched = Attachment
if Source is not None:
    Source = Source.sudo().with_context(active_test=False)
    rows = {r.id: r for r in Source.search([])}
    for attachment in from_studio:
        src = rows.get(attachment.studio_ref_id)
        if not src:
            continue
        if ((_get(src, 'x_studio_factor') or 0) < 0
                or _get(src, 'x_studio_advance_link')
                or _get(src, 'x_studio_fine_link')):
            mismatched |= attachment
    print("  %s addition(s) whose Studio row is a deduction" % len(mismatched))

suspect = negative | mismatched
print("\n  %s to look at" % len(suspect))

if suspect:
    by_type = {}
    for attachment in suspect:
        by_type.setdefault(attachment.type_id.name, []).append(attachment)
    for name, items in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        print("\n  type '%s'   %s attachment(s)" % (name, len(items)))
        total = sum(abs(a.value or 0) for a in items)
        print("      %s in total" % round(total, 2))
        for attachment in items[:8]:
            print("        %-8s %-28s %-5s %-6s %-10s payslip %s"
                  % (attachment.id, (attachment.employee_id.name or '')[:28],
                     attachment.month, attachment.year, attachment.value,
                     attachment.payslip_id.id or '-'))
        if len(items) > 8:
            print("        ... and %s more" % (len(items) - 8))

if not suspect:
    title("nothing to correct")
    print("  Every addition reads like an addition.")
    raise SystemExit()

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing changed. Run again with SSC_WRITE=1 to move")
    print("  these onto a deduction type of the same name.")
    cr.rollback()
    raise SystemExit()


title("3. moving them")

Type = env['ssc.attachment.type'].sudo()                         # noqa: F821
moved, made = 0, []
for attachment in suspect:
    name = attachment.type_id.name
    target = Type.search([('name', '=', name), ('kind', '=', 'deduction')], limit=1)
    if not target:
        # Same name, other kind: the type itself was created as an addition by
        # an import that could not tell. Make its counterpart rather than
        # flipping the one every correct attachment also uses.
        target = Type.create({'name': name, 'kind': 'deduction'})
        made.append(name)
    attachment.type_id = target.id
    moved += 1
cr.commit()

print("  %s attachment(s) moved to a deduction type" % moved)
if made:
    print("  %s type(s) created: %s" % (len(made), ', '.join(sorted(set(made)))))

title("summary")
print("""  The payslips these sit on recompute their own totals from the attachment
  lines. Check a payslip from a month with several of these against the Studio
  figure before trusting the run.""")
