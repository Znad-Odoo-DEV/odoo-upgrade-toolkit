"""Tidy the carried project attributes: drop the studio_ prefix, put the
documents back on their fields.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/tidy_project_attributes.py

Three things, in one run because they depend on each other:

 1. x_studio_project_idno becomes x_project_idno, and so on for every attribute
    carried onto project.project. The x_ has to stay - Odoo will not have a
    custom field without it - but studio_ says nothing and can go.

    Every related path out in the legacy estate that reads one of these through
    the project is rewritten in the same breath. Rename the field without them
    and nineteen screens stop showing the project number.

 2. The documents are bound back to a field. They were moved onto the project
    when the projects were created, but as loose files with a technical name -
    "Site Layout - x_studio_site_layout". A binary field is created for each
    kind, the file is tied back to it, and it is renamed to the real filename
    that was carried alongside it. The form then shows a file to download
    instead of a string nobody can open.

 3. The Site Details view is rewritten to match, or it would name fields that no
    longer exist.

AFTER THIS RUNS: odoosh-restart http, so the registry picks the new names up.
"""
import os
import re

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

MODEL = 'project.project'
TABLE = 'project_project'
VIEW_NAME = 'project.project.form.site.details'

# The documents: the legacy binary field, and the name its file goes under.
DOCUMENTS = [
    ('x_studio_affection_plan', 'x_affection_plan', "Affection Plan"),
    ('x_studio_site_layout', 'x_site_layout', "Site Layout"),
    ('x_studio_landlevel_survey', 'x_landlevel_survey', "Land / Level Survey"),
    ('x_studio_soil_report', 'x_soil_report', "Soil Report"),
    ('x_studio_perspectives', 'x_perspectives', "Perspectives"),
    ('x_studio_proposaldesign', 'x_proposaldesign', "Proposal Design"),
    ('x_studio_preliminary_arch_documents', 'x_preliminary_arch_documents',
     "Preliminary Arch. Documents"),
]

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
Attachment = env['ir.attachment'].sudo()                         # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


model_id = IrModel.search([('model', '=', MODEL)], limit=1).id
Project = env[MODEL].sudo().with_context(active_test=False)      # noqa: F821


# --- 1. what gets renamed ---------------------------------------------------

title("1. names")

renames = []                       # (old, new)
taken = {f.name for f in IrField.search([('model', '=', MODEL)])}
for field in IrField.search([('model', '=', MODEL),
                             ('state', '=', 'manual')]).sorted('name'):
    if not field.name.startswith('x_studio_'):
        continue
    new = 'x_' + field.name[len('x_studio_'):]
    if new in taken:
        print("  ! %s -> %s is taken, left alone" % (field.name, new))
        continue
    renames.append((field.name, new))
    taken.add(new)
    print("  %-46s -> %s" % (field.name, new))
print("\n  %s field(s)" % len(renames))

rename_map = dict(renames)


# --- 2. the paths that read them --------------------------------------------

title("2. related paths that read them")


def path_ends_on_project(model_name, parts):
    """True when following ``parts`` from ``model_name`` lands the last step on
    a project - which is the only case where our rename matters."""
    current = env.get(model_name)                                # noqa: F821
    for part in parts[:-1]:
        if current is None or part not in current._fields:
            return False
        field = current._fields[part]
        if not field.relational:
            return False
        current = env.get(field.comodel_name)                     # noqa: F821
    return current is not None and current._name == MODEL


path_fixes = []
for field in IrField.search([('related', '!=', False)]):
    parts = (field.related or '').split('.')
    last = parts[-1]
    if last not in rename_map or len(parts) < 2:
        continue
    if not path_ends_on_project(field.model, parts):
        continue
    new_related = '.'.join(parts[:-1] + [rename_map[last]])
    path_fixes.append((field.id, field.model, field.name, field.related, new_related))
    print("  %-40s %-34s %s" % (field.model, field.name, new_related))
print("\n  %s path(s)" % len(path_fixes))


# --- 3. the documents -------------------------------------------------------

title("3. documents")

doc_plan = []
for legacy_name, new_name, label in DOCUMENTS:
    atts = Attachment.search(['|', ('res_field', '=', new_name),
                              '&', ('name', 'like', legacy_name),
                                   ('res_model', '=', MODEL)])
    atts = atts.filtered(lambda a: a.res_model == MODEL)
    if not atts:
        print("  - %-34s no file" % label)
        continue
    doc_plan.append((legacy_name, new_name, label, atts))
    print("  + %-34s %s file(s) -> field %s" % (label, len(atts), new_name))

loose = Attachment.search([('res_model', '=', MODEL), ('name', '=', 'x_avatar_image')])
if loose:
    print("  + %-34s %s file(s) -> field x_avatar_image" % ("Photo", len(loose)))


if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 4. rename ---------------------------------------------------------------

title("4. renaming")

if not renames:
    print("  nothing to rename - the names are already tidy")
for old, new in renames:
    cr.execute("UPDATE ir_model_fields SET name = %s WHERE model = %s AND name = %s",
               (new, MODEL, old))
    if column_exists(TABLE, old):
        cr.execute('ALTER TABLE "%s" RENAME COLUMN "%s" TO "%s"' % (TABLE, old, new))
    print("  %-46s -> %s" % (old, new))
cr.commit()

if not path_fixes:
    print("  no path to rewrite")
for field_id, model, name, _old_related, new_related in path_fixes:
    cr.execute("UPDATE ir_model_fields SET related = %s WHERE id = %s",
               (new_related, field_id))
    print("  path %-36s %-30s %s" % (model, name, new_related))
cr.commit()


# --- 5. bind the documents back ---------------------------------------------

title("5. binding the documents")

for legacy_name, new_name, label, atts in doc_plan:
    if new_name not in Project._fields:
        IrField.create({
            'model_id': model_id,
            'model': MODEL,
            'name': new_name,
            'field_description': label,
            'ttype': 'binary',
            'state': 'manual',
            'copied': True,
        })
        env.flush_all()                                          # noqa: F821
        print("  + field %s" % new_name)

    filename_field = 'x_' + legacy_name[len('x_studio_'):] + '_filename'
    if not column_exists(TABLE, filename_field):
        filename_field = legacy_name + '_filename'
    for att in atts:
        real_name = None
        if column_exists(TABLE, filename_field):
            cr.execute('SELECT "%s" FROM "%s" WHERE id = %%s'
                       % (filename_field, TABLE), (att.res_id,))
            row = cr.fetchone()
            real_name = row[0] if row else None
        cr.execute("UPDATE ir_attachment SET res_field = %s, name = %s WHERE id = %s",
                   (new_name, real_name or label, att.id))
    print("  %-34s %s file(s) bound" % (label, len(atts)))

if loose:
    cr.execute("UPDATE ir_attachment SET res_field = 'x_avatar_image', name = 'Photo' "
               " WHERE id = ANY(%s)", (loose.ids,))
    print("  %-34s %s file(s) bound" % ("Photo", len(loose)))
cr.commit()


# --- 6. the view ------------------------------------------------------------

title("6. the view")

cr.execute("SELECT id, arch_db FROM ir_ui_view WHERE name = %s", (VIEW_NAME,))
row = cr.fetchone()
if not row:
    print("  no Site Details view to rewrite - run show_project_attributes.py")
else:
    view_id, arch = row
    if isinstance(arch, dict):                    # jsonb translated column
        arch = {k: re.sub(r'x_studio_', 'x_', v) for k, v in arch.items()}
        cr.execute("UPDATE ir_ui_view SET arch_db = %s::jsonb WHERE id = %s",
                   (__import__('json').dumps(arch), view_id))
    else:
        cr.execute("UPDATE ir_ui_view SET arch_db = %s WHERE id = %s",
                   (re.sub(r'x_studio_', 'x_', arch), view_id))
    print("  view %s rewritten to the new names" % view_id)
cr.commit()

title("done")
print("  %s field(s) renamed, %s path(s) rewritten, %s document field(s) bound"
      % (len(renames), len(path_fixes), len(doc_plan)))
print("""
  NEXT: odoosh-restart http

  Then re-run tools/show_project_attributes.py to lay the page out again with
  the documents on it, and open a project to check the files download.""")
