"""The fourteen money readers: give them a currency and point them home.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/fix_employee_money_readers.py

They were declared float and the salary they read is monetary, so the earlier
pass would not touch them: Odoo refuses to build a registry where a related
field and its source disagree on type, and that refusal takes the whole database
down rather than one screen.

The plan before this one was to leave them frozen - stop the path, keep the
figure, let the document remember the salary it was written with. That plan died
on one line of output: none of them is stored. They hold nothing, Odoo dropped
them from their models the moment the path broke, and asking for one raises
KeyError today. There is no figure to keep.

So they are made monetary and pointed at ssc.employee, which is where the money
is. A monetary field needs a currency, and Odoo will take x_currency_id without
being told, so each of the four models gets one - related, through the same
employee link the salary comes through, so the amount and the currency can never
disagree about whose money it is.

Order matters: the currency first and flushed, then the type, then the path. A
monetary field created before its currency exists fails validation, and the
failure is a constraint rather than a warning.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

TARGET_MODEL = 'hr.employee'
CURRENCY_NAME = 'x_currency_id'

# the last step of the broken path -> the monetary field on hr.employee (hr.version behind it)
MONEY = {
    'x_studio_basic_salary': 'wage',
    'x_studio_house_allowance': 'l10n_ae_housing_allowance',
    'x_studio_other_allowance': 'l10n_ae_other_allowances',
    'x_studio_transportation_allowance': 'l10n_ae_transportation_allowance',
    'x_studio_totalgross_salary': 'l10n_ae_total_salary',
    'x_studio_monetary_field_uk_1iboqhtm2': None,   # nothing on ssc.employee answers to it
}

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def lands_on_employee(model_name, parts):
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


# --- 1. find them -------------------------------------------------------------

title("1. the money readers")

work, unreachable = [], []
for field in IrField.search([('related', '!=', False)]):
    parts = (field.related or '').split('.')
    if len(parts) < 2 or parts[-1] not in MONEY:
        continue
    if not lands_on_employee(field.model, parts):
        continue
    source = MONEY[parts[-1]]
    if not source:
        unreachable.append((field, parts[-1]))
        continue
    work.append((field, parts[0], parts[:-1] + [source]))

by_model = {}
for field, link, new_parts in work:
    by_model.setdefault(field.model, set()).add(link)

for field, link, new_parts in sorted(work, key=lambda w: (w[0].model, w[0].name)):
    print("  %-24s %-30s %-8s -> %s"
          % (field.model, field.name, field.ttype, '.'.join(new_parts)))
print("\n  %s reader(s) on %s model(s)" % (len(work), len(by_model)))

if unreachable:
    print("\n  %s read something ssc.employee does not have either:" % len(unreachable))
    for field, attribute in unreachable:
        print("      %-24s %-30s %s" % (field.model, field.name, attribute))


# --- 2. the currency each model needs ----------------------------------------

title("2. currency")

needed = {}
for model, links in sorted(by_model.items()):
    Model = env.get(model)                                       # noqa: F821
    have = [name for name in ('currency_id', CURRENCY_NAME)
            if Model is not None and name in Model._fields]
    if have:
        print("  %-24s already has %s" % (model, have[0]))
        continue
    if len(links) > 1:
        print("  %-24s reaches the employee by %s different links - skipped"
              % (model, len(links)))
        continue
    link = sorted(links)[0]
    needed[model] = '%s.currency_id' % link
    print("  %-24s + %s  related %s" % (model, CURRENCY_NAME, needed[model]))

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 3. create the currency fields, and flush before using them --------------

title("3. creating the currency fields")

for model, related in sorted(needed.items()):
    model_record = IrModel.search([('model', '=', model)], limit=1)
    if not model_record:
        print("  ! %s has no ir.model record" % model)
        continue
    IrField.create({
        'model_id': model_record.id,
        'model': model,
        'name': CURRENCY_NAME,
        'field_description': "Currency",
        'ttype': 'many2one',
        'relation': 'res.currency',
        'related': related,
        'readonly': True,
        'state': 'manual',
    })
    print("  + %-24s %s" % (model, CURRENCY_NAME))
env.flush_all()                                                  # noqa: F821
cr.commit()


# --- 4. type, then path -------------------------------------------------------

title("4. making them monetary")

done, refused = 0, []
for field, _link, new_parts in work:
    new_related = '.'.join(new_parts)
    try:
        with cr.savepoint():
            # The type first: a related path is validated against the field's
            # own type, so a float pointed at a monetary would be refused on
            # the way in.
            field.write({'ttype': 'monetary'})
            field.write({'related': new_related})
        done += 1
        print("  > %-24s %-30s %s" % (field.model, field.name, new_related))
    except Exception as exc:
        refused.append((field.model, field.name,
                        str(exc).strip().splitlines()[0][:70]))
cr.commit()

print("\n  %s converted" % done)
if refused:
    print("  %s refused:" % len(refused))
    for model, name, why in refused:
        print("      %-24s %-30s %s" % (model, name, why))

title("summary")
print("  %s money reader(s) now read ssc.employee" % done)
print("""
  Restart, then open a To Pay and an End of Service. These fields have shown
  nothing since the repoint - they were dropped from their models - so what
  appears now is the first figure they have carried in either direction.""")
