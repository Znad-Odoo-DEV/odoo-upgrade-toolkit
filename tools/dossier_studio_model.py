"""Everything about a Studio model, so it can be rebuilt without guessing.

    SSC_MODELS=x_contractor_agreement,x_site_payment_certifi \
        odoo-bin shell --no-http --shell-interface=python < tools/dossier_studio_model.py
    SSC_OUT=~/dossier.md      where the long version is written
    SSC_SAMPLES=3             how many real rows to print (0 for none)

Reads only. Writes nothing.

The other tools each answer one question. map_studio_family draws the graph,
dump_all_studio_logic lists the behaviour, study_studio_model counts the fields.
Between them they missed the thing that matters most when you are replacing a
Studio model with real code: the arithmetic.

A Studio model keeps its logic in FOUR places, and three of them are invisible
from the screen:

  1. compute code on the field itself      ir.model.fields.compute + depends
  2. related paths                          ir.model.fields.related
  3. server actions                         ir.actions.server.code
  4. automation rules                       base.automation, and the actions
                                            they fire

Rebuild from one and two only, and the totals come out right and the workflow
does nothing. Rebuild from three and four only, and every computed column comes
out empty and nobody notices until a report is printed. This prints all four,
in full, with the code, plus what the fields actually hold - because a field
that no row has ever filled is a field somebody made in an afternoon, and it
does not need porting.

Sections:

   1. the model            rows, dates, what opens it
   2. every field          type, target, how it is filled, how many rows fill it
   3. the arithmetic       compute code and depends, in full - the section the
                           other tools do not have
   4. related fields       what is read from where
   5. selections           the actual values, with how many rows hold each
   6. links out and in     with row counts, so a real relation is told apart
                           from an abandoned one
   7. behaviour            automations and server actions, code included
   8. screens              views, and the fields each one puts in front of people
   9. access               groups, rules, and what a plain user may do
  10. samples              a few real rows, rendered

Read section 3 first. It is where the tender arithmetic of the old system
lives, and it is the part a rewrite silently loses.
"""
import os
import re

MODELS = [m.strip() for m in (os.environ.get('SSC_MODELS') or '').split(',')
          if m.strip()]
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/dossier.md')
SAMPLES = int(os.environ.get('SSC_SAMPLES') or 3)

cr = env.cr                                                      # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrView = env['ir.ui.view'].sudo()                                # noqa: F821
IrRule = env['ir.rule'].sudo()                                   # noqa: F821
IrAccess = env['ir.model.access'].sudo()                         # noqa: F821
Server = env['ir.actions.server'].sudo()                         # noqa: F821
Automation = env.get('base.automation')                          # noqa: F821

if not MODELS:
    raise SystemExit("Set SSC_MODELS=x_one,x_two")

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say()
    say(rule * 100)
    say(text)
    say(rule * 100)


def block(text, indent='      '):
    """Print somebody's code the way they wrote it."""
    for line in (text or '').replace('\r\n', '\n').split('\n'):
        say(indent + line)


def table_exists(table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""",
               (table, column))
    return bool(cr.fetchone())


def rows_of(model_name):
    model = env.get(model_name)                                  # noqa: F821
    if model is None or not table_exists(model._table):
        return 0
    cr.execute('SELECT COUNT(*) FROM "%s"' % model._table)
    return cr.fetchone()[0]


def filled(model, field):
    """How many rows hold a value, and how many different values there are.

    The pair matters. A thousand rows holding one value is a field somebody
    set a default on and never touched; a thousand rows holding nine hundred
    values is a field people actually use.
    """
    if field.ttype == 'many2many':
        if field.relation_table and table_exists(field.relation_table):
            cr.execute('SELECT COUNT(*), COUNT(DISTINCT "%s") FROM "%s"'
                       % (field.column1 or 'id', field.relation_table))
            return cr.fetchone()
        return (0, 0)
    if field.ttype == 'one2many':
        return (rows_of(field.relation) if field.relation else 0, 0)
    if not table_exists(model._table) or not column_exists(model._table,
                                                           field.name):
        return (None, None)          # not a column: computed and not stored
    cr.execute('SELECT COUNT("%s"), COUNT(DISTINCT "%s") FROM "%s"'
               % (field.name, field.name, model._table))
    return cr.fetchone()


def compute_code(model, field):
    """Studio keeps its compute on ir.model.fields; real code does not.

    A Studio model is all Studio fields, so the first branch is the one that
    matters - but pointing this at a half-ported model should still say which
    columns work themselves out.
    """
    if field.compute:
        return field.compute
    registry_field = model._fields.get(field.name)
    return '<in the module code>' if registry_field is not None         and registry_field.compute else ''


def how_filled(model, field):
    if compute_code(model, field):
        return "computed" + (", stored" if field.store else ", on the fly")
    if field.related:
        return "related"
    return "typed"


for name in MODELS:
    record = IrModel.search([('model', '=', name)], limit=1)
    model = env.get(name)                                        # noqa: F821
    if not record or model is None:
        title("%s - NOT A MODEL ON THIS DATABASE" % name)
        continue

    fields_of = IrField.search([('model', '=', name)], order='name')
    total = rows_of(name)

    # --- 1. the model --------------------------------------------------------
    title("%s   -   %s" % (name, record.name or ''))
    say("  rows                 %s" % total)
    say("  table                %s" % model._table)
    say("  order                %s" % model._order)
    say("  fields               %s (%s of them Studio's own)"
        % (len(fields_of), len(fields_of.filtered(
            lambda f: f.name.startswith('x_')))))
    if total and column_exists(model._table, 'create_date'):
        cr.execute('SELECT MIN(create_date), MAX(write_date) FROM "%s"'
                   % model._table)
        first, last = cr.fetchone()
        say("  first written        %s" % str(first)[:10])
        say("  last written         %s" % str(last)[:10])
    # ids by SQL, names by ORM: a window action's name is translated, and the
    # cursor hands a jsonb column back as a dict
    cr.execute("SELECT id FROM ir_act_window WHERE res_model = %s", (name,))
    action_ids = [row[0] for row in cr.fetchall()]
    actions = env['ir.actions.act_window'].sudo().browse(         # noqa: F821
        action_ids).exists()
    say("  screens              %s" % (", ".join(actions.mapped('name'))
                                       or "none"))
    # raw SQL to find them, the ORM to read them: a menu's name is translated
    # and comes back as a dict from the cursor, and a dead action reference
    # reads as False through the ORM so a search would miss the broken ones
    cr.execute("SELECT id FROM ir_ui_menu WHERE action = ANY(%s)",
               (['ir.actions.act_window,%s' % i for i in action_ids],))
    menus = env['ir.ui.menu'].sudo().browse(                      # noqa: F821
        [row[0] for row in cr.fetchall()]).mapped('complete_name')
    say("  menus                %s" % (", ".join(menus) or "none"))

    # --- 2. every field ------------------------------------------------------
    title("2. every field of %s" % name, '-')
    say("  %-42s %-12s %-28s %-16s %9s %9s"
        % ('field', 'type', 'target / label', 'filled how', 'rows', 'values'))
    for field in fields_of:
        held, distinct = filled(model, field)
        say("  %-42s %-12s %-28s %-16s %9s %9s"
            % (field.name[:42], field.ttype,
               (field.relation or field.field_description or '')[:28],
               how_filled(model, field),
               '-' if held is None else held,
               '-' if not distinct else distinct))
    never = [f for f in fields_of
             if not compute_code(model, f) and not f.related
             and filled(model, f)[0] in (0,)] if total else []
    if never:
        say()
        say("  %s field(s) no row has ever filled - made and abandoned:"
            % len(never))
        for field in never:
            say("      %-44s %s" % (field.name, field.field_description or ''))

    # --- 3. the arithmetic ---------------------------------------------------
    title("3. the arithmetic - what this model works out for itself", '-')
    computed = fields_of.filtered(lambda f: compute_code(model, f))
    if not computed:
        say("  Nothing on this model is computed. Every figure on it was typed.")
    for field in computed:
        held, _ = filled(model, field)
        say()
        say("  %s   (%s%s)"
            % (field.name, field.ttype,
               ", stored - %s rows hold a value" % held if field.store
               else ", not stored"))
        say("  %s" % (field.field_description or ''))
        if field.depends:
            say("  recomputed when these change: %s" % field.depends)
        else:
            say("  recomputed when: NOTHING - no depends, so it is worked out "
                "once and then goes stale")
        say("  code:")
        block(compute_code(model, field))

    # --- 4. related fields ---------------------------------------------------
    title("4. what is read from somewhere else", '-')
    relateds = fields_of.filtered('related')
    if not relateds:
        say("  Nothing. Every value on this model is its own.")
    for field in relateds:
        say("  %-42s -> %-46s %s"
            % (field.name, field.related,
               "stored" if field.store else "read live"))

    # --- 5. selections -------------------------------------------------------
    title("5. the choices people are given", '-')
    any_selection = False
    for field in fields_of.filtered(lambda f: f.ttype in ('selection',
                                                          'reference')):
        any_selection = True
        say()
        say("  %s   %s" % (field.name, field.field_description or ''))
        values = field.selection_ids
        if not values and field.selection:
            say("      %s" % field.selection)
        for value in values:
            count = 0
            if column_exists(model._table, field.name):
                cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" = %%s'
                           % (model._table, field.name), (value.value,))
                count = cr.fetchone()[0]
            say("      %-30s %-34s %s row(s)"
                % (value.value, value.name, count))
    if not any_selection:
        say("  None.")

    # --- 6. the links --------------------------------------------------------
    title("6. what it points at, and what points at it", '-')
    say("  out")
    for field in fields_of.filtered(
            lambda f: f.ttype in ('many2one', 'many2many', 'one2many')):
        held, distinct = filled(model, field)
        say("      %-42s %-12s -> %-34s %s row(s)%s"
            % (field.name[:42], field.ttype, field.relation or '-',
               '-' if held is None else held,
               ", %s different" % distinct if distinct else ''))
    say()
    say("  in")
    inward = IrField.search([('relation', '=', name)])
    for field in inward:
        if field.model == name:
            continue
        other = env.get(field.model)                             # noqa: F821
        held = filled(other, field)[0] if other is not None else None
        say("      %-42s %-12s on %-34s %s row(s)"
            % (field.name[:42], field.ttype, field.model,
               '-' if held is None else held))
    if not inward.filtered(lambda f: f.model != name):
        say("      nothing outside this model points at it")

    # --- 7. the behaviour ----------------------------------------------------
    title("7. what happens on its own", '-')
    rules = (Automation.sudo().search([('model_id', '=', record.id)])
             if Automation else [])
    say("  %s automation rule(s)" % len(rules))
    for rule in rules:
        say()
        say("  --- %s   [%s]" % (rule.name, 'on' if rule.active else 'OFF'))
        say("      fires on      %s" % rule.trigger)
        if rule.trigger_field_ids:
            say("      when changed  %s"
                % ", ".join(rule.trigger_field_ids.mapped('name')))
        if rule.filter_domain:
            say("      only if       %s" % rule.filter_domain)
        if rule.filter_pre_domain:
            say("      was before    %s" % rule.filter_pre_domain)
        for action in rule.action_server_ids:
            say("      does          %s  (%s)" % (action.name, action.state))
            if action.state == 'code' and action.code:
                block(action.code, '          ')
            if action.state == 'object_write' and action.update_field_id:
                say("          sets %s = %s" % (action.update_field_id.name,
                                                action.value))
            if action.state == 'object_create':
                say("          creates a %s" % (action.crud_model_id.model
                                                if action.crud_model_id else '?'))

    own = Server.search([('model_id', '=', record.id)])
    say()
    say("  %s server action(s)" % len(own))
    for action in own:
        say()
        say("  --- %s   [%s]" % (action.name, action.state))
        if action.binding_model_id:
            say("      appears on the %s screen" % action.binding_model_id.model)
        if action.state == 'code' and action.code:
            block(action.code, '          ')
        elif action.state == 'object_write' and action.update_field_id:
            say("      sets %s = %s" % (action.update_field_id.name,
                                        action.value))
        elif action.state == 'multi':
            say("      runs: %s" % ", ".join(action.child_ids.mapped('name')))

    # code on other models that names this one
    pattern = re.compile(r'(?<![\w.])%s(?![\w])' % re.escape(name))
    elsewhere = [a for a in Server.search([])
                 if a.model_id.id != record.id and pattern.search(a.code or '')]
    if elsewhere:
        say()
        say("  %s action(s) on OTHER models mention this one in their code:"
            % len(elsewhere))
        for action in elsewhere:
            say("      %-6s %-46s on %s"
                % (action.id, (action.name or '')[:46],
                   action.model_id.model if action.model_id else '-'))

    # --- 8. the screens ------------------------------------------------------
    title("8. the screens, and what they put in front of people", '-')
    views = IrView.search([('model', '=', name)], order='type, id')
    for view in views:
        shown = sorted(set(re.findall(r'<field name="([^"]+)"',
                                      view.arch_db or '')))
        say("  %-6s %-46s %s field(s)%s"
            % (view.type, (view.name or '')[:46], len(shown),
               "  inherits %s" % view.inherit_id.name if view.inherit_id else ''))
        if shown:
            say("         %s" % ", ".join(shown))
    if not views:
        say("  No views. It is only ever reached from another model's screen.")

    # --- 9. access -----------------------------------------------------------
    title("9. who may do what", '-')
    for access in IrAccess.search([('model_id', '=', record.id)]):
        say("  %-46s %s   read %s write %s create %s unlink %s"
            % ((access.name or '')[:46],
               access.group_id.full_name if access.group_id else 'EVERYBODY',
               access.perm_read, access.perm_write, access.perm_create,
               access.perm_unlink))
    for rule in IrRule.search([('model_id', '=', record.id)]):
        say("  rule: %-40s %s" % ((rule.name or '')[:40], rule.domain_force))

    # --- 10. samples ---------------------------------------------------------
    if SAMPLES and total:
        title("10. %s real row(s)" % min(SAMPLES, total), '-')
        interesting = [f for f in fields_of
                       if f.ttype not in ('one2many', 'many2many', 'binary')
                       and filled(model, f)[0]]
        for row in model.sudo().search([], limit=SAMPLES, order='id desc'):
            say()
            say("  --- id %s   %s" % (row.id, row.display_name))
            for field in interesting:
                try:
                    value = row[field.name]
                except Exception:
                    continue
                if not value:
                    continue
                if field.ttype == 'many2one':
                    value = "%s (%s)" % (value.display_name, value.id)
                text = str(value).replace('\n', ' ')[:70]
                say("      %-42s %s" % (field.name[:42], text))


title("how to read this")
say("""  Section 3 first. A Studio model keeps its arithmetic on the fields
  themselves, and that code is invisible from every screen - it is the part a
  rewrite loses without anybody noticing until a total comes out wrong.

  Then section 2: a field no row has ever filled does not need porting, and
  saying so out loud is usually worth a day.

  Then 6 and 7 together: 6 says what would break if the model went away, 7 says
  what it was doing to other records while it was there.""")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)
