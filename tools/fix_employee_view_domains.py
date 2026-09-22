"""Rewrite the view domains that filter an employee on a Studio attribute.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/fix_employee_view_domains.py

A domain on a many2one is evaluated in the model it points at. x_staff_loan's
employee field carried

    domain="[('x_studio_engineeroffice_staff', '=', True)]"

which was a question for x_employeeslist and is now a question for hr.employee,
which has never heard of it. The view stops validating, and a view that will not
validate poisons everything near it: Odoo then refuses to remove or retype any
field whose name appears in it, and reports that as the field being present in
views rather than as the view being broken.

The related paths were repointed and so was the automation code. The domains
were the third place the same attribute names live, and nothing had looked at
them.

Only the domain attribute of a field that really points at hr.employee is
touched, and only the names on the list below. An attribute with no native
counterpart is reported and left, because a domain rewritten wrongly filters the
wrong people rather than failing loudly.
"""
import os
import re

from lxml import etree

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

TARGET_MODEL = 'hr.employee'

# the attribute as the old list called it -> the path from hr.employee
MOVED = {
    'x_name': 'name',
    'x_active': 'active',
    'x_studio_employee_id': 'registration_number',
    'x_studio_attendance_id': 'barcode',
    'x_studio_passport': 'passport_id',
    'x_studio_profession': 'job_title',
    'x_studio_residence_visa_no': 'visa_no',
    'x_studio_user': 'user_id',
    'x_studio_company': 'company_id',
    # Text on the old side, a country on the new: read through the name.
    'x_studio_nationality': 'country_id.name',
    # The money and the dates live on hr.version, reached through _inherits,
    # and the allowances under l10n_ae_hr_payroll's names. ssc.employee is on
    # its way out and nothing routes through it any more.
    'x_studio_basic_salary': 'wage',
    'x_studio_house_allowance': 'l10n_ae_housing_allowance',
    'x_studio_other_allowance': 'l10n_ae_other_allowances',
    'x_studio_transportation_allowance': 'l10n_ae_transportation_allowance',
    'x_studio_totalgross_salary': 'l10n_ae_total_salary',
    'x_studio_joining_date': 'contract_date_start',
    'x_studio_engineeroffice_staff': 'ssc_is_office_staff',
    # The document dates hr.employee keeps: residence visa and labour card.
    # Passport expiry, entry permit and cancellation paper have no native
    # field and stay homeless. The avatar reads the native image.
    'x_studio_eidres_visa_expiry_date': 'visa_expire',
    'x_studio_date_field_6lg_1ib47o7c3': 'work_permit_expiration_date',
    'x_avatar_image': 'image_1920',
    # No native answer, on purpose: x_studio_staff (workforce is three-valued
    # now), the cancellation flags, the visa company, the agreed allowance.
    # A reader of one of these is reported and left, then removed by
    # drop_orphan_employee_readers with the list in front of us.
}

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821
Employee = env[TARGET_MODEL]                                     # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def points_at_employee(node, view):
    """True when this node's field, on the model the node is shown on, links
    to hr.employee; False when it links elsewhere; None when the arch cannot
    say which model the node is on. A name alone is not evidence:
    x_studio_paid_by points at hr.employee on one model and at
    x_responsible_for_pett on another, and the domain that is right for one
    is wrong for the other - view 4275 was refused for exactly that."""
    model = view.model
    embedding = []
    parent = node.getparent()
    while parent is not None:
        if parent.tag == 'field' and not parent.get('position'):
            embedding.append(parent.get('name'))
        parent = parent.getparent()
    for field_name in reversed(embedding):
        field = env[model]._fields.get(field_name) if model in env else None   # noqa: F821
        if field is None or not getattr(field, 'comodel_name', None):
            return None
        model = field.comodel_name
    field = env[model]._fields.get(node.get('name')) if model in env else None  # noqa: F821
    if field is None:
        return None
    return getattr(field, 'comodel_name', None) == TARGET_MODEL

NAME = re.compile(r"['\"]([A-Za-z_]\w*(?:\.\w+)*)['\"]")

# Names a domain may use that the shared table cannot express by
# substitution alone. x_studio_staff was a boolean; the workforce is
# three-valued now, and "staff" means anyone who is not labour - so the
# operator and the value change with the name, not only the name. Each entry
# is (pattern over the whole triple, replacement triple). x_studio_active is
# a plain rename the shared table does not carry.
TRIPLES = [
    (re.compile(r"""\(\s*['"]x_studio_staff['"]\s*,\s*['"]=['"]\s*,\s*True\s*\)"""),
     "('ssc_workforce', '!=', 'labour')"),
    (re.compile(r"""\(\s*['"]x_studio_staff['"]\s*,\s*['"]!=['"]\s*,\s*False\s*\)"""),
     "('ssc_workforce', '!=', 'labour')"),
    (re.compile(r"""\(\s*['"]x_studio_staff['"]\s*,\s*['"]=['"]\s*,\s*False\s*\)"""),
     "('ssc_workforce', '=', 'labour')"),
    (re.compile(r"""\(\s*['"]x_studio_staff['"]\s*,\s*['"]!=['"]\s*,\s*True\s*\)"""),
     "('ssc_workforce', '=', 'labour')"),
]
RENAMES = {'x_studio_active': 'active'}


title("1. domains on an employee field that name a Studio attribute")

plans, unmapped, unplaced = [], {}, []
# arch_db is jsonb and its text form escapes every quote, so match on a word
# with none in it.
cr.execute("SELECT id FROM ir_ui_view WHERE arch_db::text LIKE %s", ('%domain%',))
for (view_id,) in cr.fetchall():
    view = View.browse(view_id).exists()
    if not view:
        continue
    try:
        tree = etree.fromstring((view.arch or '').encode())
    except Exception:
        continue
    changes = []
    for node in tree.xpath("//field[@domain]"):
        name = node.get('name')
        linked = points_at_employee(node, view)
        domain = node.get('domain') or ''
        if linked is None:
            if any(head in MOVED or head in RENAMES or head == 'x_studio_staff'
                   for head in (r.split('.')[0] for r in NAME.findall(domain))):
                unplaced.append((view.id, name))
            continue
        if not linked:
            continue
        for referenced in set(NAME.findall(domain)):
            head = referenced.split('.')[0]
            if head in Employee._fields:
                continue                    # already asks something native
            if head == 'x_studio_staff':
                if any(pattern.search(domain) for pattern, _ in TRIPLES):
                    changes.append((node, name, referenced, 'TRIPLE'))
                else:
                    unmapped.setdefault(head + ' (shape not recognised)', set()).add(view.id)
                continue
            replacement = MOVED.get(head) or RENAMES.get(head)
            if not replacement:
                if head.startswith('x_'):
                    unmapped.setdefault(head, set()).add(view.id)
                continue
            changes.append((node, name, referenced,
                            replacement + referenced[len(head):]))
    if changes:
        plans.append((view, tree, changes))

for view, _tree, changes in plans:
    print("\n  %-6s %-26s %s" % (view.id, view.model or '-', (view.name or '')[:40]))
    for _node, field_name, referenced, replacement in changes:
        shown = replacement
        if replacement == 'TRIPLE':
            shown = "the whole triple -> ('ssc_workforce', '!='/'=', 'labour')"
        print("      on %-34s %-38s -> %s"
              % (field_name, referenced, shown))
print("\n  %s view(s) to rewrite" % len(plans))

if unmapped:
    title("2. names with no native counterpart - left alone")
    for head, ids in sorted(unmapped.items(), key=lambda kv: -len(kv[1])):
        print("  %-46s %3s view(s)  %s" % (head, len(ids), sorted(ids)[:6]))
    print("\n  A domain rewritten wrongly filters the wrong people rather than")
    print("  failing loudly, so nothing here is guessed at.")

if unplaced:
    title("2b. domains naming a moved attribute on a field the arch cannot place - left alone")
    for view_id, name in unplaced:
        print("  %-6s %s" % (view_id, name))
    print("\n  The node is not on the view's own model and no embedding field says")
    print("  which model it is on. Read the view before deciding.")

if not plans:
    print("\n  nothing to rewrite")
    raise SystemExit()

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


title("3. rewriting")

done, refused = 0, []
for view, tree, changes in plans:
    for node, _field_name, referenced, replacement in changes:
        domain = node.get('domain') or ''
        if replacement == 'TRIPLE':
            for pattern, triple in TRIPLES:
                domain = pattern.sub(triple, domain)
            node.set('domain', domain)
            continue
        # Quoted and whole: a name inside quotes, replaced with the same quotes
        # around it, so nothing else in the expression moves.
        for quote in ('"', "'"):
            domain = domain.replace('%s%s%s' % (quote, referenced, quote),
                                    '%s%s%s' % (quote, replacement, quote))
        node.set('domain', domain)
    try:
        with cr.savepoint():
            view.arch = etree.tostring(tree, encoding='unicode')
        done += 1
        print("  > %-6s %-26s %s change(s)"
              % (view.id, view.model or '-', len(changes)))
    except Exception as exc:
        # The whole message: Odoo's first line is "Error while validating
        # view near:" and says nothing; the reason is further down.
        refused.append((view.id, " ".join(str(exc).split())[:700]))
cr.commit()

print("\n  %s view(s) rewritten" % done)
if refused:
    print("  %s refused:" % len(refused))
    for view_id, reason in refused:
        print("      %-6s %s" % (view_id, reason))

title("summary")
print("""  A domain is the third place these attribute names live - after the related
  paths and the automation code - and the only one where being wrong is silent.
  Open the form of a rewritten view and check the dropdown still offers the
  people it should.""")
