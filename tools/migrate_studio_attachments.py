"""The files hanging off x_attachments, moved onto the requests they belong to.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/migrate_studio_attachments.py

    SSC_WRITE=1     actually write; without it nothing is created
    SSC_OUT=~/attachments.md

Dry by default.

x_attachments is a separate model holding a file and a link back to a request.
There is no reason for it to exist: Odoo already gives every record a chatter
that holds files, and a second model holding files means a person looking for
the signed copy of a request has two places to look and is told about one.

So the files move into the chatter of the request they belong to, and after
that x_attachments holds nothing that is not somewhere better.

Three things this is careful about:

The bytes are not re-read from the field. A Studio binary field with
attachment=True already keeps its file in ir.attachment, carrying res_field to
mark it as a field's private storage rather than something a person attached.
Copying that row and clearing res_field is what turns it into a visible
attachment - same bytes, same checksum, no base64 round trip. Only a binary
field stored inline in its own column is read directly, and the tool says
which of the two it did.

It can be run twice. Every attachment it makes carries its origin in the
description - studio:x_attachments:<id>:<field> - and that is what it searches
before creating anything. This is the same lesson as the bill lines: an import
with no key writes the same rows again on the second run and nothing says so.

A file whose request was never imported is not written anywhere. It is listed,
with the reason, because a file silently attached to the wrong record is worse
than a file still sitting in Studio.
"""
import os

WRITE = os.environ.get('SSC_WRITE') == '1'
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/attachments.md')

# The same move serves three Studio models, so the three names are settings:
#   x_attachments     -> ssc.request      linked through x_all_requests   (default)
#   x_sc_attachments  -> ssc.subcontract  linked through x_subcontractors
#   x_subcontractors  -> ssc.subcontract  the row IS the contract: SSC_LINK_TO=self
SOURCE = os.environ.get('SSC_SOURCE') or 'x_attachments'
TARGET = os.environ.get('SSC_TARGET') or 'ssc.request'
LINK_TO = os.environ.get('SSC_LINK_TO') or 'x_all_requests'

IrField = env['ir.model.fields'].sudo()                          # noqa: F821
Attachment = env['ir.attachment'].sudo()                         # noqa: F821

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
    """Every way out of this script leaves the report on disk.

    Including the ways out that found nothing. A tool that stops early and
    writes nothing costs somebody a second trip to a staging shell to be told
    the same sentence it had already worked out.
    """
    with open(OUT, 'w', encoding='utf-8') as handle:
        handle.write("\n".join(report))
    print("\nwritten to %s" % OUT)
    raise SystemExit


title("moving the files off %s" % SOURCE)
say("  %s" % ("WRITING" if WRITE else "dry run - nothing will be created"))

if SOURCE not in env:                                            # noqa: F821
    say()
    say("  %s is not on this database. Either it is already gone, or this is"
        % SOURCE)
    say("  not the database that has it.")
    finish()

if TARGET not in env:                                            # noqa: F821
    say()
    say("  %s is not on this database - ssc_requests is not installed here,"
        % TARGET)
    say("  so there is nothing to move the files onto.")
    finish()

Source = env[SOURCE].sudo()                                      # noqa: F821
Target = env[TARGET].sudo()                                      # noqa: F821

# ------------------------------------------------------- what the model holds
fields_here = IrField.search([('model', '=', SOURCE)])

links = [f for f in fields_here
         if f.ttype in ('many2one', 'many2many') and f.relation == LINK_TO]
if LINK_TO == 'self':
    # the row itself is what the target was imported from
    links = [type('Self', (), {'name': 'id', 'ttype': 'self', 'field_description': 'the row itself'})()]
binaries = [f for f in fields_here if f.ttype == 'binary']
chars = {f.name for f in fields_here if f.ttype == 'char'}

title("what is on it", '-')
say("  %s row(s)" % Source.search_count([]))
say()
say("  links back to a request:")
for f in links:
    say("      %-40s %-12s %s" % (f.name, f.ttype, f.field_description))
if not links:
    say("      NONE - there is no link to follow, and nothing can be placed.")
say()
say("  the files:")
for f in binaries:
    stored = Attachment.search_count([('res_model', '=', SOURCE),
                                      ('res_field', '=', f.name)])
    say("      %-40s %s row(s) hold a file%s"
        % (f.name, stored,
           "" if stored else " in ir.attachment - read from the column instead"))
if not binaries:
    say("      NONE - this model has no binary field.")

if not links or not binaries:
    finish()

link = links[0]
if len(links) > 1:
    say()
    say("  more than one link back; following %s, which is the first" % link.name)


def filename_field_for(binary_name):
    """The char field Studio pairs with a binary, if it made one."""
    for candidate in ("%s_filename" % binary_name, "%s_name" % binary_name):
        if candidate in chars:
            return candidate
    return None


# ------------------------------------------------------- request by studio id
requests_by_studio = {}
for record in Target.search([('studio_ref_id', '!=', False)]):
    requests_by_studio[record.studio_ref_id] = record

title("matching each file to its request", '-')
say("  %s request(s) on our side carry a Studio id" % len(requests_by_studio))

made, already, orphans, empty = 0, 0, [], []
lost = []
touched = {}


def file_is_really_there(attachment):
    """Is the file this row names actually on disk?

    Two of them are not. The ir.attachment rows exist, they carry a size and a
    checksum, and the file they point at is missing from the filestore -
    Odoo logs a FileNotFoundError and hands back nothing rather than raising,
    so a migration that did not look would copy the row, report success, and
    leave a broken paperclip on a request.

    A staging build takes the database and does not always take every file
    with it, so a row listed here may still be fine on production. Which is
    exactly why it is listed rather than counted as empty.
    """
    if not attachment.store_fname:
        return bool(attachment.db_datas)
    try:
        return os.path.exists(attachment._full_path(attachment.store_fname))
    except Exception:
        return False


def origin_of(row_id, field_name):
    return "studio:%s:%s:%s" % (SOURCE, row_id, field_name)


targets_by_name = {t.name: t for t in Target.search([]) if 'name' in Target._fields and t.name}
for row in Source.search([]):
    linked = row if link.ttype == 'self' else row[link.name]
    if not linked and 'x_name' in row._fields and (row.x_name or '').strip() in targets_by_name:
        # the link went with a deleted parent, but the row is named after the
        # contract reference, and a contract of that name is here (rebuilt)
        named = targets_by_name[(row.x_name or '').strip()]
        for field in binaries:
            origin = origin_of(row.id, field.name)
            if Attachment.search_count([('description', '=', origin),
                                        ('res_model', '=', TARGET), ('res_id', '=', named.id)]):
                already += 1
                continue
            source_attachment = Attachment.search(
                [('res_model', '=', SOURCE), ('res_id', '=', row.id),
                 ('res_field', '=', field.name)], limit=1)
            if not source_attachment:
                empty.append((row.id, field.name))
                continue
            if not file_is_really_there(source_attachment):
                lost.append((row.id, field.name, source_attachment.name,
                             source_attachment.store_fname))
                continue
            filename_field = filename_field_for(field.name)
            name = (filename_field and row[filename_field]) or source_attachment.name                 or field.field_description
            if WRITE:
                source_attachment.copy({'name': name, 'res_model': TARGET, 'res_id': named.id,
                                        'res_field': False, 'description': origin})
            made += 1
        continue
    if not linked:
        orphans.append((row.id, row.display_name, "no request on the row"))
        continue
    # a many2many gives several; a file that belongs to three requests belongs
    # on all three, and each gets its own copy with its own origin marker
    for studio_request in linked:
        target = requests_by_studio.get(studio_request.id)
        if not target:
            orphans.append((row.id, row.display_name,
                            "request %s was never imported" % studio_request.id))
            continue
        for field in binaries:
            origin = origin_of(row.id, field.name)
            if Attachment.search_count([('description', '=', origin),
                                        ('res_model', '=', TARGET),
                                        ('res_id', '=', target.id)]):
                already += 1
                continue

            source_attachment = Attachment.search(
                [('res_model', '=', SOURCE), ('res_id', '=', row.id),
                 ('res_field', '=', field.name)], limit=1)

            name = None
            filename_field = filename_field_for(field.name)
            if filename_field and row[filename_field]:
                name = row[filename_field]

            if source_attachment and not file_is_really_there(source_attachment):
                lost.append((row.id, field.name, source_attachment.name,
                             source_attachment.store_fname))
                continue

            if source_attachment:
                name = name or source_attachment.name or field.field_description
                values = {
                    'name': name,
                    'res_model': TARGET,
                    'res_id': target.id,
                    'res_field': False,
                    'description': origin,
                }
                if WRITE:
                    source_attachment.copy(values)
            else:
                data = row[field.name]
                if not data:
                    empty.append((row.id, field.name))
                    continue
                name = name or field.field_description
                if WRITE:
                    Attachment.create({
                        'name': name,
                        'datas': data,
                        'res_model': TARGET,
                        'res_id': target.id,
                        'description': origin,
                    })
            made += 1
            touched.setdefault(target, []).append(name)

say()
say("  %-8s file(s) to carry across" % made)
say("  %-8s already carried on an earlier run" % already)
say("  %-8s binary field(s) with nothing in them" % len(empty))
say("  %-8s row(s) whose file is missing from the filestore" % len(lost))
say("  %-8s row(s) that cannot be placed" % len(orphans))
say("  %-8s request(s) will gain a file" % len(touched))

# ------------------------------------------------- say so in the chatter, once
if WRITE and touched:
    for target, names in touched.items():
        target.message_post(body=env._(                          # noqa: F821
            "Carried across from the old attachments list: %s",
            ", ".join(sorted(set(names)))))
    say()
    say("  and each of those %s requests has a note saying where the file"
        % len(touched))
    say("  came from, so a person reading the chatter in a year is not left")
    say("  wondering how a document appeared with no message around it.")

# ------------------------------------------------------------ what did not go
if orphans:
    title("the ones that stay where they are", '-')
    say("  Not written anywhere. A file attached to the wrong request is worse")
    say("  than a file still sitting in Studio.")
    say()
    for row_id, label, reason in orphans[:60]:
        say("      %-8s %-46s %s" % (row_id, (label or '')[:46], reason))
    if len(orphans) > 60:
        say("      ... and %s more" % (len(orphans) - 60))

if lost:
    title("rows whose file is not on this filestore", '-')
    say("  The database row is there - a name, a size, a checksum - and the")
    say("  file it points at is not. Nothing is copied for these: a broken")
    say("  paperclip on a request looks like a document until somebody needs")
    say("  it, which is the worst moment to find out.")
    say()
    say("  A staging build takes the database and does not always bring every")
    say("  file with it, so these may well be fine on production. Run this")
    say("  there before concluding anything was lost.")
    say()
    for row_id, field_name, name, store in lost:
        say("      row %-6s %-26s %s" % (row_id, field_name, (name or '')[:26]))
        say("      %-10s %s" % ('', store or "(kept in the database)"))

if empty:
    title("binary fields that never held a file", '-')
    for row_id, field_name in empty[:30]:
        say("      row %-8s %s" % (row_id, field_name))
    if len(empty) > 30:
        say("      ... and %s more" % (len(empty) - 30))

title("what to do next")
if not WRITE:
    say("  Nothing was written. Run it again with SSC_WRITE=1 when the numbers")
    say("  above are the ones you expect.")
else:
    say("  Written. Open one of the requests listed above and check the file")
    say("  opens from the chatter before %s is deleted." % SOURCE)
    env.cr.commit()                                              # noqa: F821
    say("  Committed.")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

if not WRITE:
    env.cr.rollback()                                            # noqa: F821
