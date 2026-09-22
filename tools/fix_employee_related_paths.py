"""Point the readers at the native attribute the old one became.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/fix_employee_related_paths.py

A related field is a path, and the repoint changed what the middle of the path
is. x_to_pay.x_studio_designation still reads x_studio_for_employee.
x_studio_profession, but x_studio_for_employee is an hr.employee now, and
hr.employee has never heard of x_studio_profession. It calls it job_title.

So the last step of the path is rewritten, and only where the native field means
the same thing and is the same type. The type is checked rather than assumed:
this is the mistake the items migration made, where a many2one was carried
across as a char and seventy-two paths and one field type had to be taken apart
afterwards. A name and a type are both part of the contract.

The nationality is the one that cannot be a straight swap - text on the old
side, a country on the new - so it is read through the country's name and stays
the text the reader was declared as.

What this does not touch: the readers of attributes that never moved. The
allowances, the gratuity, the document dates live on ssc.employee, and there is
no step from hr.employee to it - deliberately, because nothing was added to
hr.employee. Those are listed at the end and settled by a decision, not here.
"""
import os

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
Employee = env[TARGET_MODEL]                                     # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def resolves(model_name, parts):
    current = env.get(model_name)                                # noqa: F821
    if current is None:
        return False
    for index, part in enumerate(parts):
        if part not in current._fields:
            return False
        field = current._fields[part]
        if index == len(parts) - 1:
            return True
        if not field.relational:
            return False
        current = env.get(field.comodel_name)                    # noqa: F821
        if current is None:
            return False
    return True


def lands_on_employee(model_name, parts):
    """True when the path walks onto an hr.employee and then reads one field of
    it. Anything shorter or longer is somebody else's path."""
    current = env.get(model_name)                                # noqa: F821
    if current is None or len(parts) < 2:
        return False
    for part in parts[:-1]:
        if part not in current._fields:
            return False
        field = current._fields[part]
        if not field.relational:
            return False
        current = env.get(field.comodel_name)                    # noqa: F821
        if current is None:
            return False
    return current._name == TARGET_MODEL


def type_of(path):
    """The ttype at the end of a path from hr.employee, and its comodel."""
    current = Employee
    for index, part in enumerate(path.split('.')):
        field = current._fields[part]
        if index == len(path.split('.')) - 1:
            return field.type, getattr(field, 'comodel_name', None)
        current = env[field.comodel_name]                        # noqa: F821
    return None, None


# --- 1. what is broken and why ------------------------------------------------

title("1. readers whose last step hr.employee does not have")

fixable, undecided, mismatched = [], [], []
for field in IrField.search([('related', '!=', False)]):
    parts = (field.related or '').split('.')
    if len(parts) < 2 or resolves(field.model, parts):
        continue
    if not lands_on_employee(field.model, parts[:-1] + [parts[-1]]):
        # the path breaks before it reaches an employee, or never goes near one
        continue
    attribute = parts[-1]
    replacement = MOVED.get(attribute)
    if not replacement:
        undecided.append((field, attribute))
        continue
    want_type, want_comodel = type_of(replacement)
    if field.ttype != want_type or (want_comodel and field.relation != want_comodel):
        mismatched.append((field, attribute, replacement, want_type, want_comodel))
        continue
    fixable.append((field, parts[:-1] + replacement.split('.')))

print("  %s can be pointed at the native attribute" % len(fixable))
print("  %s read something that only ssc.employee has" % len(undecided))
print("  %s have a native attribute of the wrong type" % len(mismatched))

if fixable:
    title("2. what will be rewritten")
    by_model = {}
    for field, new_parts in fixable:
        by_model.setdefault(field.model, []).append((field, '.'.join(new_parts)))
    for model in sorted(by_model):
        print("\n  %s" % model)
        for field, new_related in sorted(by_model[model], key=lambda p: p[0].name):
            print("      %-34s %-42s -> %s"
                  % (field.name, field.related, new_related))

if mismatched:
    title("3. right meaning, wrong type - left alone")
    for field, attribute, replacement, want_type, want_comodel in mismatched:
        print("  %-30s %-28s declared %-10s native %s %s"
              % (field.model, field.name, field.ttype, want_type,
                 want_comodel or ''))
    print("\n  Changing a reader's type changes what every view and every piece")
    print("  of code expecting it will get. Each of these is a decision.")

if undecided:
    title("4. the attributes that did not move")
    wanted = {}
    for field, attribute in undecided:
        wanted.setdefault(attribute, []).append(field)
    for attribute, fields_ in sorted(wanted.items(), key=lambda kv: -len(kv[1])):
        print("  %-46s %3s reader(s)" % (attribute, len(fields_)))
    print("\n  Neither hr.employee nor ssc.employee has these. The step from one")
    print("  to the other exists now and reaches everything ssc.employee holds -")
    print("  the salary, the allowances, the joining date - so what is left is")
    print("  what nothing holds at all: the gratuity total, the residence")
    print("  expiry, the leave allowance, the year-of-service flag. Each is a")
    print("  decision - put it on ssc.employee, or stop reading it - and not an")
    print("  obstacle to anything.")

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 5. rewrite ---------------------------------------------------------------

title("5. rewriting")

done, refused = 0, []
for field, new_parts in fixable:
    new_related = '.'.join(new_parts)
    try:
        with cr.savepoint():
            field.write({'related': new_related})
        done += 1
        print("  > %-28s %-30s %s" % (field.model, field.name, new_related))
    except Exception as exc:
        refused.append((field.model, field.name,
                        str(exc).strip().splitlines()[0][:70]))
cr.commit()

print("\n  %s rewritten" % done)
if refused:
    print("  %s refused:" % len(refused))
    for model, name, why in refused:
        print("      %-30s %-28s %s" % (model, name, why))

title("summary")
print("  %s reader(s) now point at the native attribute" % done)
print("""
  Restart before checking: a related path is resolved when the registry is
  built, and the one in memory still holds the old one.""")
