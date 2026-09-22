"""Every model whose name starts with a prefix, with what it holds and who wants it.

    SSC_PREFIX=x_1_1 odoo-bin shell --no-http --shell-interface=python < tools/list_models_by_prefix.py

Reads only. Studio names its models after whatever was typed in the box, so a
family shows up as a prefix and nothing else: x_1_1_1_general_assets through
x_1_1_7_tools_equipmen are an asset register, and x_1_1_hr_document sitting in
the middle of them is not.

Before deleting a family, the family has to be a list rather than a guess at a
pattern. This prints one, with the rows each holds, the links pointing in from
outside the family, and whether its own views validate - so what is going and
what it is entangled with are both visible before anything is typed twice.
"""
import os

PREFIX = os.environ.get('SSC_PREFIX') or ''
# A regular expression instead, for when the family is a shape rather than a
# prefix: SSC_MATCH='^x_[0-9]' finds every numbered model at once, which is how
# you discover the families you did not know were there.
MATCH = os.environ.get('SSC_MATCH') or ''

cr = env.cr                                                      # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821

if not PREFIX and not MATCH:
    raise SystemExit("Set SSC_PREFIX=x_1_1 or SSC_MATCH='^x_[0-9]'")


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def table_exists(table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


if MATCH:
    import re as _re
    wanted = _re.compile(MATCH)
    records = IrModel.search([]).filtered(
        lambda r: bool(wanted.search(r.model))).sorted('model')
else:
    records = IrModel.search([('model', '=like', PREFIX + '%')]).sorted('model')
family = {r.model for r in records}

title("1. the models matching %s" % (MATCH or PREFIX))

print("  %-40s %-34s %8s" % ('model', 'name', 'rows'))
total = 0
for record in records:
    model = env.get(record.model)                                # noqa: F821
    rows = 0
    if model is not None and table_exists(model._table):
        cr.execute('SELECT COUNT(*) FROM "%s"' % model._table)
        rows = cr.fetchone()[0]
    total += rows
    print("  %-40s %-34s %8s" % (record.model, (record.name or '')[:34], rows))
print("\n  %s model(s), %s row(s) between them" % (len(records), total))


title("2. links into the family from outside it")

outside = []
for field in IrField.search([('relation', 'in', list(family))]):
    if field.model in family:
        continue
    table = (env[field.model]._table if env.get(field.model) is not None    # noqa: F821
             else field.model.replace('.', '_'))
    held = 0
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""",
               (table, field.name))
    if cr.fetchone():
        cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL'
                   % (table, field.name))
        held = cr.fetchone()[0]
    outside.append((field, held))

for field, held in sorted(outside, key=lambda p: -p[1]):
    print("  %-9s %-34s %-34s -> %-26s %s row(s)"
          % (field.state, field.model, field.name, field.relation, held))
print("\n  %s link(s) from outside, %s row(s) holding one"
      % (len(outside), sum(h for _f, h in outside)))
coded = [f for f, _h in outside if f.state != 'manual']
if coded:
    print("  %s of them say they belong to a module:" % len(coded))
    for field in coded:
        print("      %s.%s" % (field.model, field.name))


title("3. what the family points at, outside itself")

out = {}
for record in records:
    model = env.get(record.model)                                # noqa: F821
    if model is None:
        continue
    for name, field in model._fields.items():
        if field.type not in ('many2one', 'many2many', 'one2many'):
            continue
        target = field.comodel_name
        if not target or target in family or not target.startswith('x_'):
            continue
        out.setdefault(target, set()).add('%s.%s' % (record.model, name))
for target, names in sorted(out.items(), key=lambda kv: -len(kv[1])):
    print("  %-40s %2s field(s)" % (target, len(names)))
if not out:
    print("  nothing outside the family")


title("4. their own views")

healthy, broken = 0, []
for record in records:
    for view in View.search([('model', '=', record.model)]):
        try:
            with cr.savepoint():
                view._check_xml()
            healthy += 1
        except Exception as exc:
            first = [l.rstrip() for l in str(exc).strip().splitlines() if l.strip()]
            broken.append((view, record.model, first[-1][:90] if first else ''))
print("  %s view(s) validate, %s do not" % (healthy, len(broken)))
for view, model_name, reason in broken[:12]:
    print("      %-6s %-30s %s" % (view.id, model_name, reason))


title("before deleting the family")
print("""  %s row(s) go, and they do not come back. %s link(s) from outside have to be
  dropped or repointed first, and any that say they belong to a module are
  settled by tools/reclaim_studio_fields.py before the deletion will start.

  Section 3 is what the family reads: those models stay unless they are on the
  list too, and a member that is only reachable through the family is worth
  adding to it rather than leaving stranded.""" % (total, len(outside)))
