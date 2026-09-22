"""Rewrite the automations that reach an employee attribute the old way.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/fix_employee_code_references.py

Every field that named x_employeeslist names hr.employee now, and the two do not
answer to the same questions. A server action holding

    record.x_studio_employee.x_studio_profession

was reading a Studio attribute off a Studio record. It is reading it off a
native employee today, which has never heard of it and calls it job_title - so
the line raises the next time the action runs, in the middle of whatever it was
doing, in front of whoever pressed the button.

The rewrite is textual and deliberately narrow: only ".<link>.<attribute>",
where <link> is a field that really points at hr.employee and <attribute> is one
of the names below. A bare .x_name is never touched - it belongs to a hundred
models and only the ones reached through an employee are ours to change.

Nothing is guessed. An attribute with no native counterpart is reported and left
alone, because a wrong rewrite in an automation is worse than one that still
fails loudly.
"""
import os
import re

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

TARGET_MODEL = 'hr.employee'

# the attribute as the Studio list called it -> the path from hr.employee
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
Server = env['ir.actions.server'].sudo()                         # noqa: F821
Employee = env[TARGET_MODEL]                                     # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# --- 1. the field names that reach an employee ------------------------------

links = {field.name for field in IrField.search([('relation', '=', TARGET_MODEL)])}
print("  %s field name(s) anywhere point at %s" % (len(links), TARGET_MODEL))

# The same name reaches different models from different places:
# x_studio_paid_by is an hr.employee on one model and an x_responsible_for_pett
# on another, and .x_name -> .name is right for one and breaks the other. So a
# link is resolved on the model the action runs on when the field is there;
# when it is not (the code walked somewhere else first), the rewrite is made
# only if every model carrying that name agrees on where it points.
targets_by_name = {}
for field in IrField.search([('name', 'in', sorted(links))]):
    targets_by_name.setdefault(field.name, set()).add(field.relation or '-')


def link_target(action, link):
    """The model `link` reaches from this action, or None when it cannot be
    told: '-' for a field that is not relational."""
    model = env.get(action.model_id.model) if action.model_id else None   # noqa: F821
    if model is not None and link in model._fields:
        return model._fields[link].comodel_name or '-'
    targets = targets_by_name.get(link, set())
    return next(iter(targets)) if len(targets) == 1 else None

pattern = re.compile(
    r'\.(' + '|'.join(sorted(map(re.escape, links))) + r')\.([A-Za-z_]\w*)')


title("1. what the automations read")

plans, unmapped, elsewhere, unsure = [], {}, {}, {}
for action in Server.search([]):
    code = action.code or ''
    if not code:
        continue
    changes = []
    for link, attribute in set(pattern.findall(code)):
        if attribute in Employee._fields:
            continue                      # already reads something native
        target = link_target(action, link)
        if target is None:
            unsure.setdefault(link, set()).add(action.id)
            continue
        if target != TARGET_MODEL:
            elsewhere.setdefault((link, target), set()).add(action.id)
            continue
        replacement = MOVED.get(attribute)
        if not replacement:
            unmapped.setdefault(attribute, set()).add(action.id)
            continue
        changes.append((link, attribute, replacement))
    if changes:
        plans.append((action, changes))

print("  %s action(s) to rewrite" % len(plans))
for action, changes in sorted(plans, key=lambda p: p[0].id):
    print("\n  %-6s %s" % (action.id, (action.name or '')[:56]))
    for link, attribute, replacement in sorted(changes):
        print("      .%s.%-40s -> .%s.%s" % (link, attribute, link, replacement))

if elsewhere:
    title("1b. links that reach another model from these actions - left alone")
    for (link, target), ids in sorted(elsewhere.items()):
        print("  .%-34s -> %-28s %3s action(s)  %s"
              % (link, target, len(ids), sorted(ids)[:6]))
    print()
    print("  The same name is an employee elsewhere; here it is not, and its")
    print("  x_name is its own.")

if unsure:
    title("1c. links the action's model does not carry, and models disagree on - left alone")
    for link, ids in sorted(unsure.items()):
        print("  .%-34s %3s action(s)  %s" % (link, len(ids), sorted(ids)[:6]))
    print()
    print("  Read the code before deciding which model the record on the left is.")

if unmapped:
    title("2. attributes with no native counterpart - left alone")
    for attribute, ids in sorted(unmapped.items(), key=lambda kv: -len(kv[1])):
        print("  %-46s %3s action(s)  %s"
              % (attribute, len(ids), sorted(ids)[:6]))
    print("\n  These read something neither hr.employee nor ssc.employee has.")
    print("  They fail today and will fail after; each is its own decision.")

if not plans:
    print("\n  nothing to rewrite")
    raise SystemExit()

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 3. rewrite --------------------------------------------------------------

title("3. rewriting")

done, refused = 0, []
for action, changes in plans:
    code = action.code or ''
    before = code
    for link, attribute, replacement in changes:
        # The link is part of the pattern on purpose: .x_name on its own belongs
        # to a hundred models, and only the ones reached through an employee are
        # ours to touch.
        code = re.sub(r'\.%s\.%s\b' % (re.escape(link), re.escape(attribute)),
                      '.%s.%s' % (link, replacement), code)
    if code == before:
        continue
    try:
        with cr.savepoint():
            action.write({'code': code})
        done += 1
        print("  > %-6s %-46s %s change(s)"
              % (action.id, (action.name or '')[:46], len(changes)))
    except Exception as exc:
        refused.append((action.id, str(exc).strip().splitlines()[0][:70]))
cr.commit()

print("\n  %s rewritten" % done)
if refused:
    print("  %s refused:" % len(refused))
    for action_id, why in refused:
        print("      %-6s %s" % (action_id, why))

title("summary")
print("""  Read one of these before trusting the run. A textual rewrite is exactly as
  good as the pattern behind it, and the pattern here is one dot, a field that
  really points at an employee, another dot, and a name off the list above.""")
