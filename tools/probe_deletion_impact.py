"""Everything that would be affected by deleting the named models. Reads only.

    cd ~/src/user
    SSC_MODELS=x_employeeslist,x_projects_list \\
      odoo-bin shell -d <database> --no-http < tools/probe_deletion_impact.py

drop_studio_models' section 3 counts the columns that point at a target. That
is the part PostgreSQL enforces; it is not the part that hurts. What hurts is
everything that READS those columns and will keep running after they are gone:

  * a related field on another model whose path starts with one of them
    (x_studio_employee.x_studio_basic_salary - Studio makes hundreds)
  * a computed field whose code or depends names one of them
  * a server action, an automation, a cron, whose code or domain names the
    model or one of the columns
  * a record rule or a saved filter whose domain names one
  * a view on another model whose arch names one - a form, a list, a search
  * a window action, a report, a mail template on the model
  * data that is not a foreign key but still holds the id: integers named
    after it, and the config parameters the migrations left behind

Every one of those is listed here, per target, in the order it matters, with
the model it sits on and whether that model is native. Nothing is changed.
"""
import os
import re
from collections import defaultdict

WIDTH = 100
MODELS = [m.strip() for m in (os.environ.get('SSC_MODELS') or '').split(',') if m.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

IrModel = env['ir.model'].sudo()
IrField = env['ir.model.fields'].sudo()
Data = env['ir.model.data'].sudo()
View = env['ir.ui.view'].sudo().with_context(active_test=False)

if not MODELS:
    print("  Name the models: SSC_MODELS=x_one,x_two")
    raise SystemExit


def title(text):
    print()
    print("=" * WIDTH)
    print(text)
    print("=" * WIDTH)


def sub(text):
    print()
    print("  " + text)
    print("  " + "-" * (WIDTH - 4))


def kind(model_name):
    return "studio" if (model_name or '').startswith('x_') else "NATIVE"


def owner_of(model_name, ids):
    if not ids:
        return {}
    return {r['res_id']: r['module'] for r in
            Data.search_read([('model', '=', model_name), ('res_id', 'in', list(ids))],
                             ['res_id', 'module'])}


def count_sql(table, where, params=()):
    env.cr.execute('SELECT count(*) FROM "%s" WHERE %s' % (table, where), params)
    return env.cr.fetchone()[0]


for target in MODELS:
    model = IrModel.search([('model', '=', target)], limit=1)
    if not model:
        title("%s - not on this database" % target)
        continue
    Target = env[target].sudo().with_context(active_test=False)
    total = Target.search_count([])
    active = Target.search_count([('active', '=', True)]) if 'active' in Target._fields else total

    title("%s   %s rows (%s active)   %s" % (target, total, active, model.name))

    # ------------------------------------------------------------------
    # 1. Its own shape: the one2many comodels Studio made for it.
    # ------------------------------------------------------------------
    sub("1. ITS OWN CHILDREN (one2many comodels named after it)")
    own_children = []
    for fname, meta in Target.fields_get().items():
        if meta.get('type') != 'one2many' or not (meta.get('relation') or '').startswith(target):
            continue
        child = meta['relation']
        if child in env:
            rows = env[child].sudo().with_context(active_test=False).search_count([])
            own_children.append((child, fname, rows))
            print("  %-44s via %-28s %s rows" % (child[-44:], fname[-28:], rows))
    if not own_children:
        print("  none")

    # ------------------------------------------------------------------
    # 2. Columns on OTHER models that point at it. The foreign keys.
    # ------------------------------------------------------------------
    sub("2. COLUMNS ON OTHER MODELS THAT POINT AT IT (these go with it)")
    inbound = IrField.search([('relation', '=', target), ('model', '!=', target)],
                             order='model, name')
    inbound = inbound.filtered(lambda f: not f.model.startswith(target))
    inbound_by_model = defaultdict(list)
    print("  %-30s %-32s %-9s %-7s %s" % ("MODEL", "FIELD", "TYPE", "KIND", "ROWS HOLDING A VALUE"))
    for f in inbound:
        Other = env.get(f.model)
        filled = "-"
        if Other is not None and f.name in Other._fields:
            if f.ttype == 'many2one':
                filled = Other.sudo().with_context(active_test=False).search_count([(f.name, '!=', False)])
            elif f.ttype == 'many2many' and f.relation_table:
                try:
                    filled = count_sql(f.relation_table, "TRUE")
                except Exception:                               # noqa: BLE001
                    env.cr.rollback()
                    filled = "?"
            elif f.ttype == 'one2many':
                filled = "(inverse of a column on %s)" % target
        inbound_by_model[f.model].append(f.name)
        print("  %-30s %-32s %-9s %-7s %s" % (f.model[-30:], f.name[-32:], f.ttype, kind(f.model), filled))
    if not inbound:
        print("  none")
    natives = [f for f in inbound if kind(f.model) == "NATIVE"]
    if natives:
        print()
        print("  !! %s of these are on NATIVE models: %s"
              % (len(natives), ", ".join("%s.%s" % (f.model, f.name) for f in natives)))

    inbound_names = {f.name for f in inbound}

    # ------------------------------------------------------------------
    # 3. Fields that READ those columns - related paths and compute code.
    #    They stay behind, pointing at a field that no longer exists.
    # ------------------------------------------------------------------
    sub("3. FIELDS ON OTHER MODELS THAT READ THROUGH THOSE COLUMNS (left broken)")
    readers = []
    for f in inbound:
        siblings = IrField.search([('model', '=', f.model), ('name', '!=', f.name)])
        for s in siblings:
            why = None
            rel = s.related or ''
            if rel.split('.')[0] == f.name:
                why = "related: %s" % rel
            elif s.compute and re.search(r'\b%s\b' % re.escape(f.name), s.compute):
                why = "compute code names %s" % f.name
            elif s.depends and re.search(r'\b%s\b' % re.escape(f.name), s.depends):
                why = "depends on %s" % f.name
            if why:
                readers.append((s.model, s.name, s.ttype, why))
    # And related paths from anywhere that name the target's fields two hops in.
    for s in IrField.search([('related', 'like', '.%'), ('model', '!=', target)]):
        parts = (s.related or '').split('.')
        if len(parts) >= 2:
            head = IrField.search([('model', '=', s.model), ('name', '=', parts[0])], limit=1)
            if head and head.relation == target and (s.model, s.name) not in {(r[0], r[1]) for r in readers}:
                readers.append((s.model, s.name, s.ttype, "related: %s" % s.related))
    print("  %-30s %-34s %-10s %s" % ("MODEL", "FIELD", "TYPE", "WHY IT BREAKS"))
    for r in sorted(set(readers)):
        print("  %-30s %-34s %-10s %s" % (r[0][-30:], r[1][-34:], r[2], r[3][:50]))
    if not readers:
        print("  none")

    # ------------------------------------------------------------------
    # 4. Logic that names the model or those columns.
    # ------------------------------------------------------------------
    sub("4. LOGIC THAT NAMES THE MODEL OR THOSE COLUMNS")
    tokens = [target] + sorted(inbound_names)
    pattern = re.compile(r'\b(%s)\b' % "|".join(re.escape(t) for t in tokens))

    def hits(text):
        return sorted(set(pattern.findall(text or '')))

    found = 0
    Server = env['ir.actions.server'].sudo()
    for a in Server.search([('state', '=', 'code')]):
        if a.model_id.model == target:
            continue                # goes with the model anyway
        h = hits(a.code)
        if h:
            found += 1
            print("  server action %-5s %-38s on %-24s names %s"
                  % (a.id, (a.name or '')[:38], (a.model_id.model or '')[-24:], ", ".join(h)))
    Auto = env.get('base.automation')
    if Auto is not None:
        for a in Auto.sudo().with_context(active_test=False).search([]):
            if a.model_id.model == target:
                continue
            text = " ".join(str(getattr(a, n, '') or '') for n in
                            ('filter_domain', 'filter_pre_domain'))
            trig = a.trigger_field_ids.filtered(lambda t: t.relation == target)
            h = hits(text) + (["trigger on %s" % ", ".join(trig.mapped('name'))] if trig else [])
            if h:
                found += 1
                print("  automation    %-5s %-38s on %-24s %s%s"
                      % (a.id, (a.name or '')[:38], (a.model_id.model or '')[-24:],
                         "" if a.active else "(inactive) ", ", ".join(h)))
    for c in env['ir.cron'].sudo().with_context(active_test=False).search([]):
        code = c.ir_actions_server_id.code if c.ir_actions_server_id else ''
        h = hits(code)
        if h:
            found += 1
            print("  cron          %-5s %-38s %s%s"
                  % (c.id, (c.name or '')[:38], "" if c.active else "(inactive) ", ", ".join(h)))
    for r in env['ir.rule'].sudo().with_context(active_test=False).search([]):
        if r.model_id.model == target:
            continue
        h = hits(r.domain_force)
        if h:
            found += 1
            print("  record rule   %-5s %-38s on %-24s names %s"
                  % (r.id, (r.name or '')[:38], (r.model_id.model or '')[-24:], ", ".join(h)))
    for flt in env['ir.filters'].sudo().with_context(active_test=False).search([('model_id', '!=', target)]):
        h = hits((flt.domain or '') + " " + (flt.context or ''))
        if h:
            found += 1
            print("  filter        %-5s %-38s on %-24s names %s"
                  % (flt.id, (flt.name or '')[:38], (flt.model_id or '')[-24:], ", ".join(h)))
    for a in env['ir.actions.act_window'].sudo().search([('res_model', '!=', target)]):
        h = hits((a.domain or '') + " " + (a.context or ''))
        if h:
            found += 1
            print("  window action %-5s %-38s on %-24s names %s"
                  % (a.id, (a.name or '')[:38], (a.res_model or '')[-24:], ", ".join(h)))
    if not found:
        print("  none")

    # ------------------------------------------------------------------
    # 5. Views on other models that show those columns or name the model.
    # ------------------------------------------------------------------
    sub("5. VIEWS ON OTHER MODELS THAT NAME THE MODEL OR THOSE COLUMNS")
    shown = 0
    for other, names in sorted(inbound_by_model.items()):
        for v in View.search([('model', '=', other)]):
            arch = v.arch_db or ''
            h = [n for n in names if ('name="%s"' % n) in arch] + ([target] if target in arch else [])
            if h:
                shown += 1
                own = owner_of('ir.ui.view', [v.id]).get(v.id) or 'studio_customization'
                print("  view %-6s %-44s on %-22s [%s] %s"
                      % (v.id, (v.name or '')[:44], other[-22:], own[:12], ", ".join(sorted(set(h)))))
    for v in View.search([('arch_db', 'like', target), ('model', 'not in', [target] + list(inbound_by_model))]):
        shown += 1
        own = owner_of('ir.ui.view', [v.id]).get(v.id) or 'studio_customization'
        print("  view %-6s %-44s on %-22s [%s] names the model in its arch"
              % (v.id, (v.name or '')[:44], (v.model or '')[-22:], own[:12]))
    if not shown:
        print("  none")

    # ------------------------------------------------------------------
    # 6. Things ON the model that a user may miss - reports, templates.
    # ------------------------------------------------------------------
    sub("6. ON THE MODEL ITSELF - reports, mail templates, menus, automations")
    n = 0
    for r in env['ir.actions.report'].sudo().search([('model', '=', target)]):
        n += 1
        print("  report        %-5s %s" % (r.id, r.name))
    for t in env['mail.template'].sudo().search([('model_id.model', '=', target)]):
        n += 1
        print("  mail template %-5s %s" % (t.id, t.name))
    acts = env['ir.actions.act_window'].sudo().search([('res_model', '=', target)])
    for m in env['ir.ui.menu'].sudo().with_context(active_test=False).search([]):
        if m.action and m.action._name == 'ir.actions.act_window' and m.action.id in acts.ids:
            n += 1
            print("  menu          %-5s %s" % (m.id, m.complete_name))
    if Auto is not None:
        for a in Auto.sudo().with_context(active_test=False).search([('model_id.model', '=', target)]):
            n += 1
            print("  automation    %-5s %-40s %s" % (a.id, a.name, "" if a.active else "(inactive)"))
    if not n:
        print("  none")

    # ------------------------------------------------------------------
    # 7. Ids kept without a foreign key - integers and config parameters.
    # ------------------------------------------------------------------
    sub("7. IDS HELD WITHOUT A FOREIGN KEY (survive the delete, mean nothing after)")
    n = 0
    for f in IrField.search([('ttype', '=', 'integer'), ('model', '!=', target),
                             '|', ('name', 'ilike', 'studio_ref'), ('name', 'ilike', 'legacy')]):
        Other = env.get(f.model)
        if Other is None or f.name not in Other._fields:
            continue
        filled = Other.sudo().with_context(active_test=False).search_count([(f.name, '!=', 0)])
        if filled:
            n += 1
            print("  %-30s %-28s %s rows hold an id (which model's id is not recorded)"
                  % (f.model[-30:], f.name[-28:], filled))
    for p in env['ir.config_parameter'].sudo().search([('key', 'ilike', 'migration')]):
        n += 1
        print("  parameter     %-52s %s chars" % (p.key[:52], len(p.value or '')))
    if not n:
        print("  none")

print()
print("=" * WIDTH)
env.cr.rollback()
