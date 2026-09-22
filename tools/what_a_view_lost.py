"""Fields a model still has that no view of it shows any more.

    SSC_MODEL=x_all_requests odoo-bin shell --no-http < tools/what_a_view_lost.py
    SSC_PREFIX=x_ odoo-bin shell --no-http < tools/what_a_view_lost.py

Reads only. Writes nothing, ever.

A field that exists, resolves, holds values, and appears in none of its model's
views has almost certainly been taken out of one. The deletion tool strips field
nodes out of views and commits them, and then tries to delete the model - so
when the deletion is refused, the stripping stands and a live model is left with
a form that has been emptied out.

This is how you find out which ones, and how far it went. The count that matters
is per model: one or two fields hidden on purpose is ordinary, and twenty is a
form that has been gutted.

A field is only reported when it is real: it exists, its related path still
resolves, and the column holds something. What was already broken before any of
this is not what this is looking for.
"""
import os

MODEL = os.environ.get('SSC_MODEL') or ''
PREFIX = os.environ.get('SSC_PREFIX') or ''

cr = env.cr                                                      # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821

if not MODEL and not PREFIX:
    raise SystemExit("Set SSC_MODEL=x_all_requests or SSC_PREFIX=x_")


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def table_exists(table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


def resolves(model_name, related):
    """Whether a related path still walks all the way to a field."""
    current = env.get(model_name)                                # noqa: F821
    parts = (related or '').split('.')
    for index, part in enumerate(parts):
        if current is None or part not in current._fields:
            return False
        field = current._fields[part]
        if index == len(parts) - 1:
            return True
        if not field.relational:
            return False
        current = env.get(field.comodel_name)                    # noqa: F821
    return False


if MODEL:
    models = [MODEL]
else:
    models = sorted(r.model for r in IrModel.search([('model', '=like', PREFIX + '%')]))

title("fields that exist and no view shows")

report = []
for model_name in models:
    Model = env.get(model_name)                                  # noqa: F821
    if Model is None:
        continue

    # Every field name mentioned anywhere in any view of this model. Text is
    # enough: this is asking whether the name is on a screen at all, not which
    # node it is.
    shown = set()
    views = View.search([('model', '=', model_name)])
    for view in views:
        arch = view.arch_db or ''
        if isinstance(arch, dict):
            arch = ' '.join(str(v) for v in arch.values())
        for name in Model._fields:
            if ('"%s"' % name) in arch or ("'%s'" % name) in arch:
                shown.add(name)

    missing = []
    for name, field in Model._fields.items():
        if not name.startswith('x_') or name in shown:
            continue
        record = IrField.search([('model', '=', model_name),
                                 ('name', '=', name)], limit=1)
        if not record or record.state != 'manual':
            continue
        if record.related and not resolves(model_name, record.related):
            continue                       # broken already, and not by this
        held = None
        if not record.related and field.store and table_exists(Model._table) \
                and column_exists(Model._table, name):
            cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL'
                       % (Model._table, name))
            held = cr.fetchone()[0]
        missing.append((name, record.ttype, record.related or '', held))

    if missing:
        report.append((model_name, len(views), missing))

for model_name, view_count, missing in sorted(report, key=lambda r: -len(r[2])):
    print("\n  %-40s %2s view(s)   %s field(s) on no screen"
          % (model_name, view_count, len(missing)))
    for name, ttype, related, held in sorted(missing):
        print("      %-44s %-10s %-30s %s"
              % (name, ttype, related[:30],
                 '' if held is None else '%s row(s) hold a value' % held))

print("\n  %s model(s), %s field(s)"
      % (len(report), sum(len(m) for _n, _v, m in report)))
print("""
  A field with values behind it and no node anywhere is the shape of a form
  that was edited by something that did not mean to. Compare against another
  branch before concluding: a field can be missing from a form because nobody
  ever put it there.""")
