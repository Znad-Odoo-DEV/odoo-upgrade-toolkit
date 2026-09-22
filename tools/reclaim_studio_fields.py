"""Give Studio back the fields that are recorded as belonging to a module.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/reclaim_studio_fields.py

A field's state says who made it. 'manual' means Studio or somebody at a
keyboard; 'base' means a module declares it in code, and Odoo protects those
from being edited or removed by hand - rightly, because a module would put them
back on the next upgrade and disagree with its own database.

Some fields here say 'base' and no module declares them. They are Studio's own -
the name says so, ir.model.data says studio_customization or says nothing at all
- and the state is simply wrong, which is what happens when a Studio field is
made against a model a module also touches. The consequence is small and
persistent: every tool that respects the state refuses to touch them, and every
model they point at cannot be deleted.

So they are handed back, one at a time and printed. A field any module really
does declare is never touched: this looks for the module first and only reclaims
what nothing claims.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

# Narrow it to the fields pointing at one model. Fifty-five orphans across
# res.users and product.product are a real finding and somebody's afternoon;
# two of them are what blocks a deletion today, and those two are the ones to
# touch. Left unset, it reports everything and reclaims everything.
RELATION = os.environ.get('SSC_RELATION') or ''

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrData = env['ir.model.data'].sudo()                             # noqa: F821

# Modules whose ownership is nominal: Studio writes its fields under this name,
# and a field with no ir.model.data at all belongs to nobody.
STUDIO_MODULES = {'studio_customization', False, None, ''}


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


title("1. fields that say 'base' and start with x_")

domain = [('state', '=', 'base'), ('name', '=like', 'x\\_%')]
if RELATION:
    domain.append(('relation', '=', RELATION))
suspects = IrField.search(domain)
print("  %s field(s)%s"
      % (len(suspects), ' pointing at %s' % RELATION if RELATION else ''))
if not RELATION:
    print("  (set SSC_RELATION=<model> to narrow this to one model's blockers)")

owners = {}
for data in IrData.search([('model', '=', 'ir.model.fields'),
                           ('res_id', 'in', suspects.ids)]):
    owners[data.res_id] = data.module

reclaim, owned = [], []
for field in suspects:
    module = owners.get(field.id)
    # A name beginning x_studio_ settles it whatever ir.model.data says. That
    # prefix is Studio's alone - no Odoo module declares one in Python, and
    # Studio makes them manual - so 'base' on such a field is wrong however it
    # got there. account.bank.statement.line.x_studio_employee is recorded as
    # belonging to the account module, which never declared it and never could.
    if field.name.startswith('x_studio_') or module in STUDIO_MODULES:
        reclaim.append((field, module))
    else:
        owned.append((field, module))

title("2. claimed by a real module, and not named by Studio - left alone")

for field, module in sorted(owned, key=lambda p: (p[0].model, p[0].name)):
    print("  %-34s %-38s %s" % (field.model, field.name, module))
if not owned:
    print("  none")

title("3. claimed by nobody - handed back to Studio")

for field, module in sorted(reclaim, key=lambda p: (p[0].model, p[0].name)):
    table = field.model.replace('.', '_')
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""",
               (table, field.name))
    held = '-'
    if cr.fetchone():
        cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL'
                   % (table, field.name))
        held = cr.fetchone()[0]
    print("  %-34s %-38s %-10s %s row(s)  %s"
          % (field.model, field.name, field.ttype, held,
             module if module else 'no ir.model.data'))
print("\n  %s field(s)" % len(reclaim))

if not reclaim:
    raise SystemExit()

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing changed. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


title("4. handing them back")

done = 0
for field, _module in reclaim:
    try:
        with cr.savepoint():
            cr.execute("UPDATE ir_model_fields SET state = 'manual' WHERE id = %s",
                       (field.id,))
        done += 1
        print("  > %s.%s" % (field.model, field.name))
    except Exception as exc:
        print("  ! %s.%s %s"
              % (field.model, field.name, str(exc).strip().splitlines()[0][:70]))
cr.commit()

title("summary")
print("""  %s field(s) now say 'manual', which is what they always were. Nothing about
  the data changed - the column, its values and its foreign key are exactly as
  they were - only the record of who made it.

  Restart before running anything that acts on the state.""" % done)
