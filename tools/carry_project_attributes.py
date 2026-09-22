"""Carry the project attributes off the legacy list onto project.project.

    odoo-bin shell -d <database> --no-http < tools/carry_project_attributes.py

Phase B, step 1. The legacy list x_projects_list holds 25 projects and a set of
attributes native project.project has no home for - the project number, the plot
and area figures, the consultant, the documents' filenames. About twenty Studio
fields elsewhere read those attributes THROUGH the project, with related paths
like ``x_studio_project.x_studio_project_idno``.

So the fields are created on project.project under exactly the same names. Every
one of those related paths then keeps resolving with no edit at all, and nothing
is lost the day the legacy list is deleted.

What it does:

 1. reads the old -> new id map left by tools/migrate_projects_to_native.py
 2. creates one manual field on project.project per legacy attribute that is
    still worth carrying - same name, same type, same label, same target model
    for a many2one, same values for a selection
 3. copies the 25 rows' values across

What it deliberately skips: the attributes that already have a native home and
were carried when the projects were created - name, active, description,
sequence and the pipeline status, which is a stage now.

Nothing is deleted and nothing on the legacy side is touched. Safe to run twice:
a field that is already there is left alone, and values are only written where
the project has none.
"""

# Prints the plan and rolls back, unless SSC_WRITE=1 is in the environment:
#
#     SSC_WRITE=1 odoo-bin shell --no-http < tools/carry_project_attributes.py
#
# Safer than a constant in the file - the default in git can never be "write".
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

LEGACY_MODEL = 'x_projects_list'
ID_MAP_KEY = 'ssc.project_migration.id_map'

# Already carried onto native fields when the projects were created.
NATIVE_HOME = {
    'x_name': 'name',
    'x_active': 'active',
    'x_studio_description': 'description',
    'x_studio_sequence': 'sequence',
    'x_studio_selection_field_841_1ifp8eo32': 'stage_id',
}

# Types this script knows how to create. Anything else is reported, not guessed.
SUPPORTED = {'char', 'text', 'integer', 'float', 'boolean', 'date', 'datetime',
             'monetary', 'many2one', 'selection', 'binary', 'html'}

import json

# 19.0 dropped Environment.with_context, so the context goes on the recordsets
# rather than on the environment itself.
CTX = {'lang': 'en_US', 'active_test': False}

param = env['ir.config_parameter'].sudo()                        # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821

Legacy = env.get(LEGACY_MODEL)                                   # noqa: F821
if Legacy is None:
    raise SystemExit("%s is not in this database - nothing to carry." % LEGACY_MODEL)
Legacy = Legacy.sudo().with_context(**CTX)
Project = env['project.project'].sudo().with_context(**CTX)      # noqa: F821
project_model = IrModel.search([('model', '=', 'project.project')], limit=1)


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# --- the id map -------------------------------------------------------------

id_map = {int(k): int(v) for k, v in json.loads(param.get_param(ID_MAP_KEY) or '{}').items()}
if not id_map:
    raise SystemExit(
        "%s is empty. Run tools/migrate_projects_to_native.py first." % ID_MAP_KEY)

records = Legacy.search([], order='id')
title("0. what is being carried")
print("  %s project(s) on the legacy list, %s in the id map" % (len(records), len(id_map)))


# --- 1. which attributes are worth carrying ---------------------------------

legacy_fields = IrField.search([('model', '=', LEGACY_MODEL)])
info = Legacy.fields_get()

# Every related path in the database that ends on one of our attributes, so a
# field nobody fills is still carried when something out there reads it.
readers = {}
for f in IrField.search([('related', '!=', False)]):
    last = (f.related or '').split('.')[-1]
    if last in info:
        readers.setdefault(last, []).append('%s.%s' % (f.model, f.name))

carry, skipped = [], []
for field in legacy_fields.sorted('name'):
    name = field.name
    if not name.startswith('x_') or name in NATIVE_HOME:
        continue
    if info.get(name, {}).get('type') == 'one2many':
        continue
    filled = sum(1 for r in records if r[name])
    if not filled and name not in readers:
        continue
    if field.ttype not in SUPPORTED:
        skipped.append((name, field.ttype, filled))
        continue
    carry.append((field, filled))

title("1. attributes to carry")
print("  %-46s %-10s %5s %s" % ('FIELD', 'TYPE', 'FILL', 'READERS'))
for field, filled in carry:
    print("  %-46s %-10s %2s/%-2s  %s" % (
        field.name, field.ttype, filled, len(records),
        len(readers.get(field.name, [])) or ''))
if skipped:
    print("\n  ! not carried, unsupported type:")
    for name, ttype, filled in skipped:
        print("    %-44s %-10s %s row(s)" % (name, ttype, filled))


# --- 2. create the fields on project.project --------------------------------

title("2. fields on project.project")

existing = {f.name for f in IrField.search([('model', '=', 'project.project')])}
created = 0
for field, _filled in carry:
    if field.name in existing:
        print("  = %s already there" % field.name)
        continue

    vals = {
        'model_id': project_model.id,
        'name': field.name,
        'field_description': field.field_description or field.name,
        'ttype': field.ttype,
        'state': 'manual',
        'help': field.help or False,
        'copied': True,
    }
    if field.ttype == 'many2one':
        vals['relation'] = field.relation
        # Never let a project vanish because the thing it points at was removed.
        vals['on_delete'] = 'set null'
    if field.ttype == 'selection':
        vals['selection_ids'] = [
            (0, 0, {'value': s.value, 'name': s.name, 'sequence': s.sequence})
            for s in field.selection_ids
        ]
    IrField.create(vals)
    created += 1
    print("  + %s (%s)%s" % (
        field.name, field.ttype,
        '  -> %s' % field.relation if field.ttype == 'many2one' else ''))

if created:
    # Creating a manual field is Odoo's own business: it reflects the field and
    # brings the column into being itself. Rather than reach into the registry -
    # whose API is a moving target across versions - we simply ask the model
    # afterwards whether the fields are there to be written.
    env.flush_all()                                              # noqa: F821
    Project = env['project.project'].sudo().with_context(**CTX)  # noqa: F821

not_ready = [f.name for f, _ in carry if f.name not in Project._fields]
if not_ready:
    title("the fields are declared but not live yet")
    print("  %s field(s) are not in the model yet, so their values cannot be "
          "written in this run:" % len(not_ready))
    for name in not_ready[:5]:
        print("    %s" % name)
    if len(not_ready) > 5:
        print("    ... and %s more" % (len(not_ready) - 5))
    print("""
  This is normal: a manual field becomes usable once the registry has been
  rebuilt. Nothing is lost - do this:

    1. run it once with SSC_WRITE=1, which creates the field definitions
       and commits them
    2. odoosh-restart
    3. run it again - it will find the fields in place and copy the values

  The script is safe to run as many times as that takes: a field that exists is
  left alone, and a value that is already there is never overwritten.""")
    if DRY_RUN:
        env.cr.rollback()                                        # noqa: F821
        print("\n  DRY RUN - rolled back.")
    else:
        env.cr.commit()                                          # noqa: F821
        print("\n  the %s field definition(s) are committed." % created)
    raise SystemExit()


# --- 3. copy the values -----------------------------------------------------

title("3. values")

written, untouched, missing = 0, 0, 0
for src in records:
    project = Project.browse(id_map.get(src.id)).exists()
    if not project:
        missing += 1
        print("  ! legacy %s (%s) has no project - skipped" % (src.id, src.x_name))
        continue

    vals = {}
    for field, _filled in carry:
        name = field.name
        if name not in Project._fields:
            continue
        value = src[name]
        if not value:
            continue
        if project[name]:
            # Already carried, or set by hand since. Never overwrite.
            continue
        vals[name] = value.id if field.ttype == 'many2one' else value

    if vals:
        project.write(vals)
        written += 1
        print("  > %-46s %s field(s)" % (src.x_name or src.id, len(vals)))
    else:
        untouched += 1

title("summary")
print("  fields carried   : %s created, %s already present"
      % (created, len(carry) - created))
print("  projects written : %s" % written)
print("  projects skipped : %s already complete, %s without a counterpart"
      % (untouched, missing))
if skipped:
    print("  attributes left  : %s of an unsupported type (listed above)" % len(skipped))

if DRY_RUN:
    env.cr.rollback()
    print("\n  DRY RUN - everything above was rolled back.")
    print("  Run it again with SSC_WRITE=1 in front of the command to write.")
else:
    env.cr.commit()
    print("\n  committed.")
