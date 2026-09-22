"""Remove the related fields that read what is not coming across.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/drop_orphan_employee_readers.py

Only the attributes hr.employee already had a home for are moving. Everything
else on x_employeeslist - the allowances, the gratuity, the document expiry
dates, the joining date - stays where it is and goes when the model goes.

Which leaves the fields that read those through an employee link with nothing
to read. Odoo drops such a field from the model on its own, silently, and the
screens showing it then fail with "field is undefined" when somebody opens
them. Removing them here means that happens now, on purpose, with the list in
front of us, rather than to whoever opens the wrong form next week.

Run this LAST, after tools/fix_employee_related_paths.py. Most of what lands
here has a home on ssc.employee - the salary, the allowances, the joining date -
and hr.employee names ssc.employee now, so a path can take one more step and
reach it. Repointing those first leaves a dozen genuinely homeless readers here
instead of sixty-five, and the difference is a dozen columns on live screens.

What goes with each one: a column on a Studio table and whatever it held. The
list is printed in full first, and nothing is touched until it is run with
SSC_WRITE=1.
"""
import os

from lxml import etree

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

LEGACY_MODEL = 'x_employeeslist'
TARGET_MODEL = 'hr.employee'

# The attributes that do have a home on the native employee. A field reading
# one of these keeps working and is left alone.
SURVIVES = {
    'x_name', 'x_active',
    'x_studio_attendance_id', 'x_studio_employee_id', 'x_studio_passport',
    'x_studio_profession', 'x_studio_residence_visa_no', 'x_studio_user',
    'x_studio_nationality', 'x_studio_company',
    # homed by the unified table: wage, the l10n_ae allowances, the contract
    # start date, the office-staff flag
    'x_studio_basic_salary', 'x_studio_house_allowance', 'x_studio_other_allowance',
    'x_studio_transportation_allowance', 'x_studio_totalgross_salary',
    'x_studio_joining_date', 'x_studio_engineeroffice_staff',
    'x_studio_eidres_visa_expiry_date', 'x_studio_date_field_6lg_1ib47o7c3',
    'x_avatar_image',
    # already on hr.employee under their own names
    'x_studio_overtime_contract',
    'x_studio_overtime_hrs_rate_on_offholidays',
    'x_studio_overtime_hrs_rate_on_regular_days',
}

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
Legacy = env[LEGACY_MODEL]                                       # noqa: F821
Employee = env[TARGET_MODEL]                                     # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# --- 1. who reads what will not be there -----------------------------------

title("1. related fields left with nothing to read")

def lands_on(model_name, parts):
    """The model the path stands on when it reads its last step, or None
    when a step on the way is missing or not relational. A native
    activity_type_id, a path through some other model that happens to share
    a field name - none of our business."""
    current = env.get(model_name)                                # noqa: F821
    for part in parts[:-1]:
        if current is None or part not in current._fields:
            return None
        field = current._fields[part]
        if not field.relational:
            return None
        current = env.get(field.comodel_name)                     # noqa: F821
    return current._name if current is not None else None


# Every link was repointed, so a reader of an attribute that did not move now
# lands on hr.employee and asks for a name it does not have. Before the repoint
# the same reader landed on x_employeeslist and the test was whether the name
# was on the survivors' list; both shapes are kept, the first is what is there.
doomed = []
for field in IrField.search([('related', '!=', False)]):
    parts = (field.related or '').split('.')
    if len(parts) < 2:
        # a related field on the legacy model itself, reading one of its own
        own = (field.model == LEGACY_MODEL and parts[0] in Legacy._fields)
        if own and parts[0] not in SURVIVES:
            doomed.append(field)
        continue
    landing = lands_on(field.model, parts)
    if landing == TARGET_MODEL:
        if parts[-1] in Employee._fields:
            continue                    # reads something native: fine
        doomed.append(field)
    elif landing == LEGACY_MODEL:
        if parts[-1] in SURVIVES or parts[-1] not in Legacy._fields:
            continue
        doomed.append(field)

by_model = {}
for field in doomed:
    by_model.setdefault(field.model, []).append(field)

for model in sorted(by_model):
    print("\n  %s" % model)
    for field in sorted(by_model[model], key=lambda f: f.name):
        print("      %-40s %s" % (field.name, field.related))
print("\n  %s field(s) on %s model(s)" % (len(doomed), len(by_model)))

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing removed. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 2. remove --------------------------------------------------------------

title("2. taking them off the views first")

# Odoo will not delete a field a view still shows, and it is right not to: the
# view would break the moment the field went. So the views are cleaned first,
# node by node, and only then is the field removed.
View = env['ir.ui.view'].sudo()                                  # noqa: F821

# A line model's field is often shown inside the parent's form, not in a view of
# its own model, so the search cannot be limited to the field's model. But a
# name like x_studio_company belongs to a dozen models, and stripping it
# everywhere would take out somebody else's column. So: a name that only one
# model has is cleaned wherever it appears; a shared one only in views of its
# own model.
owners = {}
for f in IrField.search([('name', 'in', list({d.name for d in doomed}))]):
    owners.setdefault(f.name, set()).add(f.model)

cleaned = 0
for field in doomed:
    unique = len(owners.get(field.name, set())) <= 1
    views = View.search([]) if unique else View.search([('model', '=', field.model)])
    for view in views:
        arch = view.arch or ''
        if ('name="%s"' % field.name) not in arch and ("name='%s'" % field.name) not in arch:
            continue
        try:
            tree = etree.fromstring(arch.encode())
        except Exception as exc:
            print("  ! view %s will not parse (%s)" % (view.id, str(exc)[:50]))
            continue
        nodes = tree.xpath("//field[@name='%s']" % field.name)
        if not nodes:
            continue
        for node in nodes:
            node.getparent().remove(node)
        try:
            with cr.savepoint():
                view.arch = etree.tostring(tree, encoding='unicode')
            cleaned += len(nodes)
            print("  - %-30s %-28s view %-6s %s"
                  % (field.model, field.name, view.id,
                     '' if unique else '(same model only)'))
        except Exception as exc:
            print("  ! view %s refused: %s" % (view.id, str(exc).strip().splitlines()[0][:56]))
cr.commit()
print("\n  %s field node(s) taken off views" % cleaned)


title("3. removing the fields")

gone, refused = 0, []
for field in doomed:
    try:
        with cr.savepoint():
            field.unlink()
        gone += 1
    except Exception as exc:
        refused.append((field.model, field.name,
                        str(exc).strip().splitlines()[0][:70]))
cr.commit()

print("  %s removed" % gone)
if refused:
    print("\n  %s still refused:" % len(refused))
    for model, name, why in refused:
        print("      %-32s %-30s %s" % (model, name, why))

title("summary")
print("  %s reader(s) removed, %s left in place" % (gone, len(refused)))
print("""
  The screens that showed them have lost those columns. That is the shape of the
  decision: the attributes behind them are not moving to hr.employee.""")
