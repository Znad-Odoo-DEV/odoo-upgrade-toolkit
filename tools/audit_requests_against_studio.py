"""The Studio requests family, field by field, beside what ssc_requests has.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/audit_requests_against_studio.py

    SSC_FULL=1      also print the compute code, the actions and the view arch
    SSC_OUT=~/requests_audit.md
    SSC_SECTION=2   print only one section

Reads only.

dossier_studio_model.py says what a Studio model holds. This says what of it we
did NOT take, which is a different question and the only one worth asking now
that ssc_requests is written and a thousand one hundred and forty-five requests
are sitting in it.

Every Studio field is put in one of four boxes:

  carried    something on our side has the same name or the same label
  MISSING    rows hold a value here and nothing on our side answers to it
  empty      no row has ever filled it, so there was nothing to carry
  plumbing   Odoo's own - message_ids, activity_ids, create_uid

The middle box is the report. Everything else is there so the middle box can be
trusted: a field with two thousand rows in it and no counterpart is a hole, and
a field with none is a field somebody made in an afternoon.

The matching is by name and by label, both normalised - x_studio_total_amount
against total_amount, "Total Amount" against "Total Amount". It is deliberately
generous, because a false match shows up as a name in the carried list that
does not belong there and is easy to spot, while a false miss sends somebody
looking for a field that is already built.

Section 5 prints the views as they RENDER on this database - Studio's own edits
applied - because what the old screen puts in front of people, in what order,
under which page, is the part that no field list can tell you.
"""
import os
import re

from lxml import etree

FULL = os.environ.get('SSC_FULL') == '1'
ONLY_SECTION = os.environ.get('SSC_SECTION')
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/requests_audit.md')

# the Studio side
STUDIO = [
    'x_all_requests',
    'x_requesttypes',
    'x_approval_requests_tag',
    'x_attachments',
    'x_requests_sequence',
]

# ours, and everything that extends it
MINE = [
    'ssc.request',
    'ssc.request.type',
    'ssc.request.sequence',
    'ssc.request.material.line',
    'ssc.request.installment',
    'ssc.request.certificate.line',
    'ssc.request.certificate.claim',
]

# Odoo's own, on every model, never ours to carry
PLUMBING = re.compile(
    r'^(id|create_date|create_uid|write_date|write_uid|display_name|'
    r'__last_update|message_|website_message_|activity_|rating_|has_message|'
    r'my_activity_)')

cr = env.cr                                                      # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrView = env['ir.ui.view'].sudo()                                # noqa: F821
Server = env['ir.actions.server'].sudo()                         # noqa: F821
Automation = env.get('base.automation')                          # noqa: F821

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say()
    say(rule * 100)
    say(text)
    say(rule * 100)


def wanted(number):
    return not ONLY_SECTION or ONLY_SECTION == str(number)


def source(name):
    model = env.get(name)                                        # noqa: F821
    if model is None:
        return None
    cr.execute("SELECT to_regclass(%s)", (model._table,))
    return model.sudo() if cr.fetchone()[0] else None


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""",
               (table, column))
    return bool(cr.fetchone())


def filled(model, field):
    """(rows holding a value, distinct values) or (None, None) if not a column."""
    if field.ttype == 'many2many':
        if field.relation_table and column_exists(field.relation_table, 'id'):
            cr.execute('SELECT COUNT(*), 0 FROM "%s"' % field.relation_table)
            return cr.fetchone()
        return (0, 0)
    if field.ttype == 'one2many':
        other = env.get(field.relation)                          # noqa: F821
        if other is None:
            return (0, 0)
        cr.execute("SELECT to_regclass(%s)", (other._table,))
        if not cr.fetchone()[0]:
            return (0, 0)
        cr.execute('SELECT COUNT(*) FROM "%s"' % other._table)
        return (cr.fetchone()[0], 0)
    if not column_exists(model._table, field.name):
        return (None, None)
    # For a number or a boolean, COUNT(column) counts rows where it is not
    # NULL - and zero and false are not NULL. That reported a boolean nobody
    # ever ticked as filled on eleven hundred rows. Count what is actually
    # SET instead, and let the distinct count say whether it ever varied.
    if field.ttype in ('float', 'monetary', 'integer', 'boolean'):
        cr.execute('SELECT COUNT(*) FILTER (WHERE "%s" IS NOT NULL'
                   '                          AND "%s"::text NOT IN (%%s, %%s)),'
                   '       COUNT(DISTINCT "%s")'
                   '  FROM "%s"'
                   % (field.name, field.name, field.name, model._table),
                   ('0', 'false'))
        return cr.fetchone()
    cr.execute('SELECT COUNT("%s"), COUNT(DISTINCT "%s") FROM "%s"'
               % (field.name, field.name, model._table))
    return cr.fetchone()


def how(model, field):
    if field.compute:
        return "computed" + (", stored" if field.store else "")
    registry = model._fields.get(field.name)
    if registry is not None and registry.compute and not field.related:
        return "computed in code"
    if field.related:
        return "related"
    return "typed"


def flatten(text):
    """A name or a label, reduced to the words in it.

    x_studio_total_amount_1, total_amount and "Total Amount:" all come out as
    the same three words, which is what makes the two sides comparable at all.
    """
    text = re.sub(r'^x_studio_|^x_', '', (text or '').strip())
    text = re.sub(r'_\d+$', '', text)
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


# ---------------------------------------------------------------- our side ---

ours = {}
for name in MINE:
    model = env.get(name)                                        # noqa: F821
    if model is None:
        continue
    for field in IrField.search([('model', '=', name)]):
        for key in (flatten(field.name), flatten(field.field_description)):
            if key:
                ours.setdefault(key, []).append(
                    "%s.%s" % (name.replace('ssc.request', 'req'), field.name))

present = [name for name in MINE if env.get(name) is not None]   # noqa: F821
absent = [name for name in MINE if env.get(name) is None]        # noqa: F821


# --- 1. the two sides ---------------------------------------------------------

if wanted(1):
    title("1. the two sides")
    say("  ours, on this database")
    for name in present:
        model = env[name]                                        # noqa: F821
        cr.execute('SELECT COUNT(*) FROM "%s"' % model._table)
        say("      %-42s %6s row(s), %s field(s)"
            % (name, cr.fetchone()[0],
               IrField.search_count([('model', '=', name)])))
    for name in absent:
        say("      %-42s NOT INSTALLED on this database" % name)

    say()
    say("  Studio's")
    for name in STUDIO:
        model = source(name)
        if model is None:
            say("      %-42s already gone" % name)
            continue
        cr.execute('SELECT COUNT(*) FROM "%s"' % model._table)
        rows = cr.fetchone()[0]
        record = IrModel.search([('model', '=', name)], limit=1)
        say("      %-42s %6s row(s), %s field(s), %s view(s), %s action(s)"
            % (name, rows, IrField.search_count([('model', '=', name)]),
               IrView.search_count([('model', '=', name)]),
               Server.search_count([('model_id', '=', record.id)])
               if record else 0))


# --- 2. the gap ---------------------------------------------------------------

holes = []

if wanted(2):
    title("2. every Studio field, and whether we have it")

for name in STUDIO:
    model = source(name)
    if model is None:
        continue
    fields_of = IrField.search([('model', '=', name)], order='name')
    if wanted(2):
        say()
        say("-" * 100)
        say("  %s" % name)
        say("-" * 100)
        say("  %-44s %-9s %8s %7s  %s"
            % ('field', 'filled', 'rows', 'values', 'ours'))
    for field in fields_of:
        if PLUMBING.match(field.name):
            continue
        rows, distinct = filled(model, field)
        keys = [flatten(field.name), flatten(field.field_description)]
        match = None
        for key in keys:
            if key and key in ours:
                match = ", ".join(sorted(set(ours[key]))[:2])
                break
        if match:
            verdict = match
        elif not rows:
            verdict = "- (no row ever filled it)"
        else:
            verdict = "*** MISSING ***"
            holes.append((name, field.name, field.field_description or '',
                          field.ttype, rows, distinct, how(model, field)))
        if wanted(2):
            say("  %-44s %-9s %8s %7s  %s"
                % (field.name[:44], how(model, field),
                   '-' if rows is None else rows,
                   '-' if not distinct else distinct, verdict))


# --- 3. the arithmetic --------------------------------------------------------

if FULL and wanted(3):
    title("3. the compute code, in full")
    for name in STUDIO:
        model = source(name)
        if model is None:
            continue
        computed = IrField.search([('model', '=', name),
                                   ('compute', '!=', False)], order='name')
        if not computed:
            continue
        say()
        say("-" * 100)
        say("  %s   -   %s field(s) work themselves out" % (name, len(computed)))
        say("-" * 100)
        for field in computed:
            rows, _ = filled(model, field)
            say()
            say("  %s   (%s%s, %s rows hold a value)"
                % (field.name, field.ttype,
                   ", stored" if field.store else ", not stored",
                   '-' if rows is None else rows))
            say("  %s" % (field.field_description or ''))
            say("  depends on: %s" % (field.depends or "NOTHING - it is worked "
                                      "out once and then goes stale"))
            for line in (field.compute or '').replace('\r\n', '\n').split('\n'):
                say("      %s" % line)
        related = IrField.search([('model', '=', name),
                                  ('related', '!=', False)], order='name')
        if related:
            say()
            say("  and %s field(s) are read from somewhere else:" % len(related))
            for field in related:
                say("      %-44s -> %s" % (field.name[:44], field.related))


# --- 4. the behaviour ---------------------------------------------------------

if FULL and wanted(4):
    title("4. the server actions and the automation rules, in full")
    for name in STUDIO:
        record = IrModel.search([('model', '=', name)], limit=1)
        if not record:
            continue
        rules = (Automation.sudo().search([('model_id', '=', record.id)])
                 if Automation else [])
        actions = Server.search([('model_id', '=', record.id)])
        if not rules and not actions:
            continue
        say()
        say("-" * 100)
        say("  %s   -   %s rule(s), %s action(s)"
            % (name, len(rules), len(actions)))
        say("-" * 100)
        for rule in rules:
            say()
            say("  RULE  %s   [%s]" % (rule.name, 'on' if rule.active else 'OFF'))
            say("        fires on %s" % rule.trigger)
            if rule.trigger_field_ids:
                say("        when %s changes"
                    % ", ".join(rule.trigger_field_ids.mapped('name')))
            if rule.filter_domain:
                say("        only if %s" % rule.filter_domain)
            for action in rule.action_server_ids:
                say("        does: %s (%s)" % (action.name, action.state))
                for line in (action.code or '').replace('\r\n', '\n').split('\n'):
                    say("            %s" % line)
        for action in actions:
            say()
            say("  ACTION  %s   [%s]" % (action.name, action.state))
            if action.binding_model_id:
                say("          on the %s screen" % action.binding_model_id.model)
            if action.state == 'object_write' and action.update_field_id:
                say("          sets %s = %s"
                    % (action.update_field_id.name, action.value))
            for line in (action.code or '').replace('\r\n', '\n').split('\n'):
                say("      %s" % line)


# --- 5. the screens -----------------------------------------------------------

if FULL and wanted(5):
    title("5. the screens, as they render on this database")
    say("  Studio's edits applied, because what the old screen puts in front of")
    say("  people - in what order, under which page - is the part no field list")
    say("  can tell you.")
    for name in STUDIO:
        model = env.get(name)                                    # noqa: F821
        if model is None:
            continue
        for view in IrView.search([('model', '=', name),
                                   ('inherit_id', '=', False)],
                                  order='type, id'):
            say()
            say("-" * 100)
            say("  %s   %s   [%s]" % (name, view.name, view.type))
            say("-" * 100)
            try:
                arch = env[view.model].get_view(view.id, view.type)['arch']  # noqa: F821
            except Exception as error:
                say("  will not render: %s" % error)
                continue
            pretty = etree.tostring(etree.fromstring(arch),
                                    pretty_print=True, encoding='unicode')
            for line in pretty.split('\n'):
                say("  %s" % line.rstrip())


# --- 6. what is missing -------------------------------------------------------

title("6. what Studio holds and we do not")

alive = [name for name in STUDIO if source(name) is not None]
if not alive:
    # nothing missing and nothing compared are not the same answer, and
    # printing the first when the second is true sends somebody away happy
    say("  Nothing was compared. Not one of the Studio models is on this")
    say("  database - they have already been deleted, or this is a database")
    say("  they were never on. Run this where they still are.")
elif not holes:
    say("  Nothing. Every Studio field that any row has ever filled has")
    say("  something on our side answering to it.")
else:
    say("  %s field(s) hold data on the Studio side with no counterpart here."
        % len(holes))
    say()
    say("  %-24s %-40s %-11s %8s %7s"
        % ('model', 'field', 'type', 'rows', 'values'))
    for name, field, label, kind, rows, distinct, filled_how in sorted(
            holes, key=lambda hole: -hole[4]):
        say("  %-24s %-40s %-11s %8s %7s   %s"
            % (name[:24], field[:40], kind, rows, distinct or '-', filled_how))
        if label:
            say("  %-24s   %s" % ('', label[:70]))

say()
say("  Read the two number columns together. For a number or a boolean, rows")
say("  counts what is actually SET - not zero, not false - because COUNT on a")
say("  column counts rows where it is not NULL, and that reports a checkbox")
say("  nobody ever ticked as filled on eleven hundred rows.")
say()
say("  Then values. Two distinct values on a boolean means both were used;")
say("  one means it was set once and never varied, and porting it would carry")
say("  a decision nobody has made since.")
say()
say("  Run it again with SSC_FULL=1 for the compute code, the actions and the")
say("  view arch - that is where the shape of the old screen lives.")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
