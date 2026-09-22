"""A family of Studio models as a data model: what they are, and how they join.

    SSC_MODELS=x_boq,x_boq_scope,x_sectorss \
        odoo-bin shell --no-http --shell-interface=python < tools/map_studio_family.py
    SSC_OUT=~/family_map.md    where to write the long version

Reads only.

study_studio_model.py answers what one model holds. dump_all_studio_logic.py
answers what it does. This answers the question you have when you are replacing
a system rather than a screen: what are the entities, which one is the spine,
what hangs off it, and where do the quantities and the money actually live.

Six sections:

  1. the entities        rows, last written, reachable from a menu
  2. the graph           every link inside the family, with direction and how
                         many rows use it - which is what tells a real relation
                         apart from one somebody made and abandoned
  3. the doors           links in from outside and out to the world: the ones
                         out are what the family depends on, the ones in are
                         what depends on it
  4. where the numbers are   quantity, price, amount and percentage fields, per
                         model, with how many rows hold them
  5. the behaviour       automations and server actions, and which of them
                         reach across models
  6. the orphans         line models whose parent is gone, and fields nothing
                         has ever filled

The graph is the important one. Studio models join by convention rather than by
constraint - two models with the same contractor and project, a code copied into
a char field - so the links it draws are the ones the database actually holds,
and the ones it cannot draw are named at the end as things to ask about.
"""
import os
import re

MODELS = [m.strip() for m in (os.environ.get('SSC_MODELS') or '').split(',') if m.strip()]
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/family_map.md')

cr = env.cr                                                      # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
Server = env['ir.actions.server'].sudo()                         # noqa: F821
Automation = env.get('base.automation')                          # noqa: F821

if not MODELS:
    raise SystemExit("Set SSC_MODELS=a,b,c")

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say()
    say(rule * 96)
    say(text)
    say(rule * 96)


def table_exists(table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


def rows_of(model_name):
    model = env.get(model_name)                                  # noqa: F821
    if model is None or not table_exists(model._table):
        return 0
    cr.execute('SELECT COUNT(*) FROM "%s"' % model._table)
    return cr.fetchone()[0]


def held(model_name, field):
    """How many rows of a model hold a value in one of its fields."""
    model = env.get(model_name)                                  # noqa: F821
    if model is None:
        return 0
    if field.ttype == 'many2many':
        if field.relation_table and table_exists(field.relation_table):
            cr.execute('SELECT COUNT(*) FROM "%s"' % field.relation_table)
            return cr.fetchone()[0]
        return 0
    if field.ttype == 'one2many':
        return rows_of(field.relation) if field.relation else 0
    if not table_exists(model._table) or not column_exists(model._table, field.name):
        return 0
    cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL'
               % (model._table, field.name))
    return cr.fetchone()[0]


# the family, and the line models that belong to it
family = set(MODELS)
while True:
    found = set()
    for field in IrField.search([('ttype', '=', 'many2one'),
                                 ('relation', 'in', list(family))]):
        if field.model in family:
            continue
        if field.model.startswith('%s_line' % field.relation):
            found.add(field.model)
    if not found:
        break
    family |= found

lines_of = {}
for name in family:
    for field in IrField.search([('ttype', '=', 'many2one'), ('relation', '=', name)]):
        if field.model.startswith('%s_line' % name):
            lines_of.setdefault(name, set()).add(field.model)


# --- 1. the entities ---------------------------------------------------------

title("1. the entities")

cr.execute("SELECT id, res_model FROM ir_act_window")
actions = {}
for action_id, res_model in cr.fetchall():
    actions.setdefault(res_model, []).append(action_id)
cr.execute("SELECT action FROM ir_ui_menu WHERE action IS NOT NULL")
menu_actions = set()
for (action,) in cr.fetchall():
    if action and ',' in action:
        kind, _sep, ident = action.partition(',')
        if kind == 'ir.actions.act_window' and ident.isdigit():
            menu_actions.add(int(ident))

say("  %-34s %-30s %8s %-11s %-7s %s"
    % ('model', 'name', 'rows', 'last write', 'opened', 'line models'))
for name in sorted(family, key=lambda n: -rows_of(n)):
    record = IrModel.search([('model', '=', name)], limit=1)
    model = env.get(name)                                        # noqa: F821
    last = '-'
    if model is not None and table_exists(model._table) \
            and column_exists(model._table, 'write_date') and rows_of(name):
        cr.execute('SELECT MAX(write_date) FROM "%s"' % model._table)
        stamp = cr.fetchone()[0]
        last = str(stamp)[:10] if stamp else '-'
    opened = ('menu' if any(a in menu_actions for a in actions.get(name, []))
              else ('screen' if actions.get(name) else '-'))
    kids = lines_of.get(name, set())
    say("  %-34s %-30s %8s %-11s %-7s %s"
        % (name, (record.name or '')[:30] if record else 'NOT A MODEL',
           rows_of(name), last, opened,
           "%s (%s rows)" % (len(kids), sum(rows_of(k) for k in kids)) if kids else ''))


# --- 2. the graph ------------------------------------------------------------

title("2. the graph - how they join, and how much the join is used")

edges = []
for name in sorted(family):
    for field in IrField.search([('model', '=', name),
                                 ('ttype', 'in', ('many2one', 'one2many', 'many2many'))]):
        if field.relation not in family:
            continue
        edges.append((name, field.name, field.ttype, field.relation, held(name, field)))

say("  %-34s %-40s %-11s %-30s %s"
    % ('from', 'field', 'kind', 'to', 'rows using it'))
for source, field_name, kind, target, count in sorted(edges, key=lambda e: -e[4]):
    say("  %-34s %-40s %-11s %-30s %s"
        % (source, field_name[:40], kind, target, count))
say()
say("  %s link(s) inside the family" % len(edges))
dead = [e for e in edges if e[4] == 0]
if dead:
    say("  %s of them are used by no row at all - made and abandoned:" % len(dead))
    for source, field_name, kind, target, _count in dead[:12]:
        say("      %s.%s -> %s" % (source, field_name, target))


# --- 3. the doors ------------------------------------------------------------

title("3. the doors - what the family depends on, and what depends on it")

outward, inward = [], []
for name in sorted(family):
    for field in IrField.search([('model', '=', name),
                                 ('ttype', 'in', ('many2one', 'many2many'))]):
        if not field.relation or field.relation in family:
            continue
        outward.append((name, field.name, field.relation, held(name, field)))
for field in IrField.search([('relation', 'in', list(family))]):
    if field.model in family:
        continue
    inward.append((field.model, field.name, field.relation,
                   held(field.model, field)))

say("  out - what these models point at")
seen = {}
for source, field_name, target, count in outward:
    seen.setdefault(target, 0)
    seen[target] += count
for target, count in sorted(seen.items(), key=lambda kv: -kv[1])[:20]:
    say("      %-40s %s row(s) point at it" % (target, count))

say()
say("  in - what points at these models")
for source, field_name, target, count in sorted(inward, key=lambda e: -e[3])[:25]:
    say("      %-34s %-40s -> %-26s %s" % (source, field_name[:40], target, count))
say()
say("  %s link(s) in from outside the family" % len(inward))


# --- 4. where the numbers are ------------------------------------------------

title("4. where the quantities and the money are")

MONEY = re.compile(r'qty|quant|amount|price|rate|total|value|cost|percent|perc|'
                   r'factor|done|balance|sum', re.I)
for name in sorted(family):
    numbers = []
    for field in IrField.search([('model', '=', name),
                                 ('ttype', 'in', ('float', 'monetary', 'integer'))]):
        if not MONEY.search(field.name):
            continue
        count = held(name, field)
        if count:
            numbers.append((field.name, field.ttype, count))
    if not numbers:
        continue
    say("\n  %s   (%s rows)" % (name, rows_of(name)))
    for field_name, kind, count in sorted(numbers, key=lambda n: -n[2])[:14]:
        say("      %-46s %-10s %s" % (field_name, kind, count))


# --- 5. the behaviour --------------------------------------------------------

title("5. the behaviour")

ids = IrModel.search([('model', 'in', list(family))]).ids
rules = Automation.sudo().search([('model_id', 'in', ids)]) if Automation else []
own = Server.search([('model_id', 'in', ids)])

say("  %s automation(s), %s server action(s) on the family" % (len(rules), len(own)))
say()
for name in sorted(family):
    record = IrModel.search([('model', '=', name)], limit=1)
    if not record:
        continue
    mine = own.filtered(lambda a: a.model_id == record)
    if mine:
        say("  %-34s %s action(s)" % (name, len(mine)))

# code on other models that names one of these
pattern = re.compile(r'(?<![\w.])(%s)(?![\w])'
                     % '|'.join(sorted((re.escape(n) for n in family),
                                       key=len, reverse=True)))
elsewhere = [a for a in Server.search([])
             if a.model_id.id not in ids and pattern.search(a.code or '')]
say()
say("  %s action(s) on OTHER models name one of these in their code:" % len(elsewhere))
for action in elsewhere[:20]:
    say("      %-6s %-40s on %s"
        % (action.id, (action.name or '')[:40],
           action.model_id.model if action.model_id else '-'))


# --- 6. the orphans ----------------------------------------------------------

title("6. what is already broken or abandoned")

for name in sorted(family):
    model = env.get(name)                                        # noqa: F821
    if model is None or not table_exists(model._table):
        continue
    total = rows_of(name)
    if not total:
        continue
    parents = IrField.search([('model', '=', name), ('ttype', '=', 'many2one'),
                              ('relation', 'in', list(family))])
    for field in parents:
        if not field.name.endswith('_id') and 'x_studio' not in field.name:
            continue
        if not column_exists(model._table, field.name):
            continue
        cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NULL'
                   % (model._table, field.name))
        loose = cr.fetchone()[0]
        if loose and loose > total * 0.05:
            say("  %-34s %-40s %s of %s rows have no parent"
                % (name, field.name[:40], loose, total))


title("what to do with this")
say("""  Section 2 is the data model somebody would have drawn if anybody had. Read
  it first: a link used by three thousand rows is a real relation, and one used
  by none is a field made in an afternoon and never filled.

  Section 3 says what the new application must keep talking to - project.project,
  res.partner, product.template - and what will break when these models go.

  Section 4 is where the arithmetic lives, and therefore what has to be computed
  rather than typed.

  Section 6 is what is already wrong today, so it is not mistaken for something
  the migration did.""")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)
