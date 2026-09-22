"""A Studio model taken apart: every field, and whether anybody ever filled it.

    SSC_MODELS=x_all_requests,x_requesttypes \
        odoo-bin shell --no-http --shell-interface=python < tools/study_studio_model.py

Reads only. Writes nothing, ever.

Before writing a module to replace a Studio model, the model has to be read -
and the field list alone is not reading it. x_all_requests has two hundred and
sixty fields and eleven hundred rows; some of them are the request, some are one
request type's tab, and a great many were made in an afternoon two years ago and
have never held a value.

So every field is printed with the one number that separates those: how many
rows hold something in it. A field with values is a decision. A field with none,
in eleven hundred rows, is not.

Selections get their values counted as well, because that is where the workflow
actually is: a status field with four values and the count under each is the
state machine, written down for the first time.

What this does not do is judge. It prints; the decision is somebody's.
"""
import os

MODELS = [m.strip() for m in (os.environ.get('SSC_MODELS') or '').split(',') if m.strip()]
# A field held by fewer than this many rows is still printed, but flagged. Set
# SSC_QUIET=1 to leave the empty ones out entirely once they have been read.
QUIET = os.environ.get('SSC_QUIET') == '1'
SAMPLES = int(os.environ.get('SSC_SAMPLES') or 2)

cr = env.cr                                                      # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821

if not MODELS:
    raise SystemExit("Set SSC_MODELS=x_all_requests,x_requesttypes")


def title(text, rule='='):
    print("\n" + rule * 104)
    print(text)
    print(rule * 104)


def table_exists(table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


def plain(value):
    """A jsonb translated value read raw comes back as a dict."""
    if isinstance(value, dict):
        return next(iter(value.values()), '')
    return value


def study(model_name, depth=0):
    pad = '  ' * depth
    record = IrModel.search([('model', '=', model_name)], limit=1)
    if not record:
        print("%s%s is not a model in this database" % (pad, model_name))
        return
    Model = env.get(model_name)                                  # noqa: F821
    if Model is None:
        print("%s%s has no registry entry" % (pad, model_name))
        return

    table = Model._table
    rows = 0
    if table_exists(table):
        cr.execute('SELECT COUNT(*) FROM "%s"' % table)
        rows = cr.fetchone()[0]

    title("%s   %s   -   %s row(s)" % (model_name, record.name or '', rows))

    views = View.search([('model', '=', model_name)])
    kinds = {}
    for view in views:
        kinds[view.type] = kinds.get(view.type, 0) + 1
    print("  views: %s" % (', '.join('%s x%s' % (k, v)
                                     for k, v in sorted(kinds.items())) or 'none'))
    for label, model, domain in (
            ('messages', 'mail.message', [('model', '=', model_name)]),
            ('followers', 'mail.followers', [('res_model', '=', model_name)]),
            ('activities', 'mail.activity', [('res_model', '=', model_name)]),
            ('attachments', 'ir.attachment', [('res_model', '=', model_name)])):
        Target = env.get(model)                                  # noqa: F821
        if Target is not None:
            print("  %-12s %s" % (label, Target.sudo().search_count(domain)))

    # ---- the fields ---------------------------------------------------
    print("\n  %-46s %-12s %-26s %8s  %s"
          % ('field', 'type', 'points at / selection', 'filled', 'label'))

    lines, empty, children = [], 0, []
    for field in IrField.search([('model', '=', model_name)]).sorted('name'):
        name = field.name
        if not name.startswith('x_') and name not in ('id',):
            continue
        target = ''
        if field.relation:
            target = field.relation
        if field.ttype == 'selection':
            target = 'selection'
        if field.related:
            target = '= %s' % field.related

        held = None
        if field.ttype in ('one2many',):
            comodel = env.get(field.relation)                    # noqa: F821
            if comodel is not None and table_exists(comodel._table):
                cr.execute('SELECT COUNT(*) FROM "%s"' % comodel._table)
                held = cr.fetchone()[0]
                if field.relation.startswith(model_name + '_line'):
                    children.append(field.relation)
        elif field.ttype == 'many2many':
            if field.relation_table and table_exists(field.relation_table):
                cr.execute('SELECT COUNT(*) FROM "%s"' % field.relation_table)
                held = cr.fetchone()[0]
        elif column_exists(table, name):
            cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL'
                       % (table, name))
            held = cr.fetchone()[0]

        if held == 0:
            empty += 1
            if QUIET:
                continue
        mark = '  .' if held == 0 else '%3s' % (held if held is not None else '-')
        lines.append("  %-46s %-12s %-26s %8s  %s"
                     % (name, field.ttype, target[:26], mark,
                        (plain(field.field_description) or '')[:34]))
    for line in lines:
        print(line)
    print("\n  %s field(s), %s of them never filled in %s row(s)"
          % (len(IrField.search([('model', '=', model_name)])), empty, rows))

    # ---- the workflow, which is whatever the selections say ------------
    selections = IrField.search([('model', '=', model_name),
                                 ('ttype', '=', 'selection')])
    if selections:
        title("  the selection fields, and what is actually in them", '-')
        for field in selections.sorted('name'):
            if not column_exists(table, field.name):
                continue
            cr.execute('SELECT "%s", COUNT(*) FROM "%s" GROUP BY 1 ORDER BY 2 DESC'
                       % (field.name, table))
            counts = cr.fetchall()
            if len(counts) == 1 and counts[0][0] is None:
                continue
            print("\n  %s   %s" % (field.name,
                                   (plain(field.field_description) or '')))
            labels = {}
            try:
                labels = dict(Model._fields[field.name].selection or [])
            except Exception:
                pass
            for value, count in counts:
                print("      %-30s %-30s %s"
                      % (value if value is not None else '(empty)',
                         labels.get(value, '')[:30], count))

    # ---- a look at what is in the busiest text fields -------------------
    if SAMPLES and rows:
        interesting = [f for f in IrField.search([('model', '=', model_name)])
                       if f.ttype in ('char', 'text') and f.name.startswith('x_')
                       and column_exists(table, f.name)]
        shown = []
        for field in interesting:
            cr.execute('SELECT DISTINCT "%s" FROM "%s" WHERE "%s" IS NOT NULL '
                       'AND "%s" <> \'\' LIMIT %s'
                       % (field.name, table, field.name, field.name, SAMPLES))
            values = [str(plain(row[0]))[:44] for row in cr.fetchall()]
            if values:
                shown.append((field.name, values))
        if shown:
            title("  what the text fields hold", '-')
            for name, values in shown:
                print("  %-46s %s" % (name, ' | '.join(values)))

    return children


for model_name in MODELS:
    kids = study(model_name) or []
    for child in sorted(set(kids)):
        study(child, depth=1)


title("what to decide, per field")
print("""  filled  '.'   nobody has ever put anything in it. It is not a feature,
                whatever its label says.
          a count  somebody uses it. It is a decision: carry it, or say what
                replaces it.

  The selection counts are the workflow. A status with four values and a
  thousand rows on one of them is a state nobody leaves, and a state with two
  rows is a path that was tried once.

  Then say, per model: replace it, keep it as it is, or delete it. The module
  gets written from the first list.""")
