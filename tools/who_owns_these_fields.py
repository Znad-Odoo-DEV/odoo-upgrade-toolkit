"""Which model declares each of these field names, and which views show them.

    SSC_FIELDS=x_studio_fine_link,x_studio_salary_adjustment odoo-bin shell --no-http < tools/who_owns_these_fields.py

Reads only. The delete tool says it would strip these nodes out of views
belonging to models that are staying, on the grounds that the field itself is
leaving. That is either exactly right - a departing model's field shown inside
another model's form, through an embedded list - or it is the same mistake as
before wearing a better disguise.

The difference is visible in one query: who declares the name. If only the
departing model and its lines declare it, a node carrying that name is that
field wherever it appears, and the view showing it is showing something that
will not exist. If anybody else declares it too, the tool should have left it
alone and did not.
"""
import os

NAMES = [n.strip() for n in (os.environ.get('SSC_FIELDS') or '').split(',') if n.strip()]
MODEL = os.environ.get('SSC_MODEL') or 'x_to_pay'

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821

if not NAMES:
    raise SystemExit("Set SSC_FIELDS=name1,name2")


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


title("who declares them")

for name in NAMES:
    fields = IrField.search([('name', '=', name)])
    print("\n  %s" % name)
    if not fields:
        print("      nothing declares it")
        continue
    for field in fields.sorted('model'):
        mark = '  <-- the model that is leaving' if field.model.startswith(MODEL) else ''
        print("      %-40s %-10s %s%s"
              % (field.model, field.ttype, field.state, mark))


title("the views that show them, and what those views are of")

for name in NAMES:
    cr.execute("SELECT id FROM ir_ui_view WHERE arch_db::text LIKE %s", ('%' + name + '%',))
    ids = [row[0] for row in cr.fetchall()]
    print("\n  %s   %s view(s)" % (name, len(ids)))
    for view in View.browse(ids).exists():
        print("      %-6s %-28s %s" % (view.id, view.model or '-',
                                       (view.name or '')[:44]))


title("what to read")
print("""  A name declared only by the departing model and its line models is that
  model's field wherever a view names it - shown inside somebody else's form
  through an embedded list, which is ordinary. Stripping it is right, because
  the field is going.

  A name any surviving model also declares should never have reached the strip
  list. If one appears above, the guard is wrong again and nothing should be
  deleted until it is fixed.""")
