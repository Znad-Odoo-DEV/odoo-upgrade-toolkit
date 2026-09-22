"""Put the carried project attributes on the project form.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/show_project_attributes.py

tools/carry_project_attributes.py moved the site details onto project.project -
the project number, the plot, the parties, the areas, the documents - and every
legacy screen reads them again through its own related fields. Nobody can see
them, though: a field created from the shell belongs to no view.

This adds one page to the project form, "Site Details", with the attributes
laid out in the four groups they fall into naturally. Only the fields that
actually exist are put on it, so a database where some were never carried still
gets a working view.

The view is a normal inherited view record and can be deleted from Settings >
Technical > Views at any time; nothing else depends on it. Running this twice
rewrites the same record rather than making a second one.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

VIEW_NAME = 'project.project.form.site.details'

# The order they read in, not the order they were created in. Names are given
# without a prefix: the tool takes whichever of x_studio_<name> / x_<name> the
# database actually has, so it works before and after the tidy-up rename.
GROUPS = [
    ("Identification", [
        'project_idno', 'plot_number', 'project_typeuse', 'type',
        'created', 'main_store', 'under_saud_shehatha_construction_llc',
    ]),
    ("Location", ['city', 'master_project_area', 'country']),
    ("Parties", ['owner', 'master_developer', 'consultant',
                 'mep_contractor', 'tenant_if_any']),
    ("Figures", [
        'height_floor', 'no_of_buildings_1', 'building_height_m',
        'plot_area_sqft', 'plot_coverage', 'ground_floor_area_sqft',
        'total_bua_sqft', 'total_bua_sqm', 'gfa_sqft_1', 'far',
    ]),
]

# A document is a file and the name it was uploaded under. Shown as one widget,
# which is the only way a file is any use on a form.
DOCUMENTS = [
    ('affection_plan', "Affection Plan"),
    ('site_layout', "Site Layout"),
    ('landlevel_survey', "Land / Level Survey"),
    ('soil_report', "Soil Report"),
    ('perspectives', "Perspectives"),
    ('proposaldesign', "Proposal Design"),
    ('preliminary_arch_documents', "Preliminary Arch. Documents"),
]


Project = env['project.project']                                 # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# --- 1. what is there to show ----------------------------------------------

title("1. fields to put on the form")

def resolve(name):
    """The field behind a bare name, whichever prefix this database uses."""
    for candidate in ('x_' + name, 'x_studio_' + name):
        if candidate in Project._fields:
            return candidate
    return None


blocks, shown, absent = [], 0, []
for label, names in GROUPS:
    present = [f for f in (resolve(n) for n in names) if f]
    absent += [n for n in names if not resolve(n)]
    if not present:
        continue
    rows = '\n'.join('                    <field name="%s"/>' % n for n in present)
    blocks.append('                <group string="%s">\n%s\n                </group>'
                  % (label, rows))
    shown += len(present)
    print("  %-16s %s field(s)" % (label, len(present)))

doc_rows = []
for name, label in DOCUMENTS:
    binary = resolve(name)
    if not binary:
        continue
    filename = resolve(name + '_filename')
    attrs = ' filename="%s"' % filename if filename else ''
    doc_rows.append('                    <field name="%s" string="%s"%s/>'
                    % (binary, label, attrs))
    shown += 1
if doc_rows:
    blocks.append('                <group string="Documents">\n%s\n                </group>'
                  % '\n'.join(doc_rows))
    print("  %-16s %s field(s)" % ('Documents', len(doc_rows)))
else:
    print("  %-16s none bound yet - run tools/tidy_project_attributes.py" % 'Documents')

arch = """<data>
    <xpath expr="//sheet/notebook" position="inside">
        <page string="Site Details" name="ssc_site_details">
            <group>
%s
            </group>
        </page>
    </xpath>
</data>""" % '\n'.join(blocks)


# --- 2. the view ------------------------------------------------------------

title("2. the view")

parent = env.ref('project.edit_project', raise_if_not_found=False)  # noqa: F821
if not parent:
    parent = View.search([('model', '=', 'project.project'),
                          ('type', '=', 'form'),
                          ('inherit_id', '=', False)], limit=1)
if not parent:
    raise SystemExit("the project form view was not found - nothing to inherit.")
print("  inheriting %s (id %s)" % (parent.name, parent.id))

existing = View.search([('name', '=', VIEW_NAME)], limit=1)
print("  %s" % ("updating the view added by an earlier run" if existing
                else "creating a new view"))
print("  %s field(s) on the page" % shown)

if DRY_RUN:
    print("\n%s" % arch)
    print("\n  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    env.cr.rollback()                                            # noqa: F821
    raise SystemExit()

vals = {
    'name': VIEW_NAME,
    'model': 'project.project',
    'inherit_id': parent.id,
    'mode': 'extension',
    'priority': 99,
    'arch_db': arch,
    'active': True,
}
if existing:
    existing.write(vals)
    view = existing
else:
    view = View.create(vals)
env.cr.commit()                                                  # noqa: F821

title("done")
print("  view %s is live: Project > any project > Site Details" % view.id)
print("  to take it away again: Settings > Technical > Views, delete '%s'"
      % VIEW_NAME)
