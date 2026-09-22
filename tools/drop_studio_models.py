"""Delete the named Studio models. Nothing else is touched.

    cd ~/src/user
    SSC_MODELS=a,b,c odoo-bin shell -d <database> --no-http < tools/drop_studio_models.py

    APPLY=1   delete. Without it nothing is touched and everything is listed.

THE RULE THIS TOOL EXISTS TO KEEP
---------------------------------
Delete the named models, their own fields, their own views. Where something
else links to them, break the link and nothing more. No other model is
affected - not a native one, not another Studio one.

So every record removed here is found by its OWN model being one of the
targets. Never by searching a view arch for a name (x_name lives on dozens of
Studio models, and that search reaches the whole database). Never by a property
a record happens to have, like being an empty menu - half the native menus are
empty containers, and a sweep for emptiness climbs the tree until Settings is
gone. Both of those happened; this is what replaced them.

Anything carrying an ir.model.data row owned by a module belongs to that module
and is left alone.

THE ONE UNAVOIDABLE OUTSIDE CHANGE
----------------------------------
A many2one on another model pointing at a target. The column cannot outlive
what it points at, so it goes, and the dry run names it with the number of rows
holding a value. A view showing that column is KEPT: only that one field node
is removed from its arch.

THIS IS NOT REVERSIBLE.
"""
import os
import time

from lxml import etree

APPLY = os.environ.get('APPLY') == '1'
WIDTH = 100

DEFAULT = []
MODELS = [m.strip() for m in (os.environ.get('SSC_MODELS') or '').split(',') if m.strip()] \
    or DEFAULT

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

IrModel = env['ir.model'].sudo()
IrField = env['ir.model.fields'].sudo()
Data = env['ir.model.data'].sudo()
View = env['ir.ui.view'].sudo().with_context(active_test=False)


def title(text):
    print()
    print("=" * WIDTH)
    print(text)
    print("=" * WIDTH)


if not MODELS:
    print("  Name the models: SSC_MODELS=x_one,x_two")
    raise SystemExit

# ----------------------------------------------------------------------
# 1. The models. The named ones, plus the comodels Studio made for their
# one2many fields - and a comodel qualifies only when it is provably part of
# the parent: its name carries the parent name as a prefix, AND nothing
# outside this set points at it. Anything else is reported and left alone.
# ----------------------------------------------------------------------
targets, missing = {}, []
for name in MODELS:
    model = IrModel.search([('model', '=', name)], limit=1)
    if model:
        targets[name] = model
    else:
        missing.append(name)

if missing:
    for name in missing:
        print("  %s is not on this database - skipped." % name)

# mail.thread and rating give every model a one2many of their own -
# message_ids, activity_ids, website_message_ids, rating_ids. They belong to
# the mixin, not to this model, and they are never comodels to delete.
MIXIN = ('message_', 'activity_', 'rating_', 'website_message_', 'my_activity_')

extra, refused = {}, []
for name in list(targets):
    for field_name, meta in env[name].fields_get().items():
        if meta.get('type') != 'one2many' or field_name.startswith(MIXIN):
            continue
        child = meta.get('relation')
        if not (child or '').startswith('x_'):
            continue
        if not child or child in targets or child in extra:
            continue
        if not IrModel.search_count([('model', '=', child)]):
            continue
        if not child.startswith(name):
            refused.append((child, "named unlike its parent %s" % name))
            continue
        outside = IrField.search([('relation', '=', child)]).filtered(
            lambda f: f.model != name and f.model not in targets)
        if outside:
            refused.append((child, "%s also points at it" % outside[0].model))
            continue
        extra[child] = "one2many of %s" % name

names = set(targets) | set(extra)
ordered = sorted(extra) + list(targets)          # children before their parents

title("1. WHAT WOULD GO")
print("  %-42s %-9s %s" % ("MODEL", "ROWS", "WHY"))
print("  " + "-" * (WIDTH - 4))
total_rows = 0
for name in targets:
    rows = env[name].with_context(active_test=False).search_count([])
    total_rows += rows
    print("  %-42s %-9s %s" % (name[-42:], rows, "named"))
for name in sorted(extra):
    rows = env[name].with_context(active_test=False).search_count([])
    total_rows += rows
    print("  %-42s %-9s %s" % (name[-42:], rows, extra[name]))
print("  " + "-" * (WIDTH - 4))
print("  %-42s %s row(s) in %s model(s)" % ("TOTAL", total_rows, len(names)))

if refused:
    print()
    print("  LEFT ALONE - a comodel of a target that is not provably part of it:")
    for child, why in refused:
        print("      %-42s %s" % (child[-42:], why))
    print("  Name one on SSC_MODELS if you want it gone too.")

# ----------------------------------------------------------------------
# 2. What sits ON these models, and only what sits on them. Every record here
# is found by its own model being a target, and skipped if a module owns it.
# ----------------------------------------------------------------------
title("2. WHAT SITS ON THEM")

attached, protected = {}, {}


def owner_of(records):
    """{record id: owning module} for the records a module claims."""
    if not records:
        return {}
    rows = Data.search_read([('model', '=', records._name),
                             ('res_id', 'in', records.ids)], ['res_id', 'module'])
    return {row['res_id']: row['module'] for row in rows}


def collect(label, model_name, field):
    Model = env.get(model_name)
    if Model is None:
        return
    found = Model.sudo().with_context(active_test=False).search(
        [(field, 'in', sorted(names))])
    owners = owner_of(found)
    ours = found.filtered(
        lambda record: (owners.get(record.id) or 'studio_customization')
        in ('studio_customization', '__export__'))
    attached[label] = ours
    if found - ours:
        protected[label] = found - ours


collect("view", 'ir.ui.view', 'model')
collect("window action", 'ir.actions.act_window', 'res_model')
collect("server action", 'ir.actions.server', 'model_id.model')
collect("access rule", 'ir.model.access', 'model_id.model')
collect("record rule", 'ir.rule', 'model_id.model')
collect("filter", 'ir.filters', 'model_id')
collect("attachment", 'ir.attachment', 'res_model')
collect("message", 'mail.message', 'model')
collect("follower", 'mail.followers', 'res_model')
collect("activity", 'mail.activity', 'res_model')
if env.get('base.automation') is not None:
    collect("automation", 'base.automation', 'model_id.model')

# A cron whose model is a target, or whose code names one.
crons = env['ir.cron'].sudo().with_context(active_test=False)
keep = crons.browse()
for cron in crons.search([]):
    action = cron.ir_actions_server_id
    code = (action.code or '') if action else ''
    if (cron.model_id and cron.model_id.model in names) or any(n in code for n in names):
        keep |= cron
attached["scheduled action"] = keep

# A menu goes only when the action it opens is one of ours. Its parents are
# handled after the deletion, and only if this run emptied them.
action_ids = set(attached.get("window action", env['ir.actions.act_window']).ids)
menus = env['ir.ui.menu'].sudo().with_context(active_test=False)
keep = menus.browse()
for menu in menus.search([]):
    action = menu.action
    if action and action._name == 'ir.actions.act_window' and action.id in action_ids:
        keep |= menu
attached["menu"] = keep

for label in sorted(attached):
    records = attached[label]
    if not records:
        continue
    print()
    print("  %s (%s):" % (label, len(records)))
    for record in records[:15]:
        try:
            shown = record.display_name
        except Exception:                                       # noqa: BLE001
            shown = record.id
        print("      %s" % shown)
    if len(records) > 15:
        print("      ... and %s more" % (len(records) - 15))

if any(protected.values()):
    print()
    print("  LEFT ALONE - a module owns these, so they are its to remove:")
    for label in sorted(protected):
        if protected[label]:
            print("      %-18s %s record(s)" % (label, len(protected[label])))

# ----------------------------------------------------------------------
# 3. The only change that reaches outside the list.
# ----------------------------------------------------------------------
title("3. WHAT THIS COSTS OUTSIDE THE LIST")

inbound = IrField.search([('relation', 'in', sorted(names)),
                          ('model', 'not in', sorted(names))])
if inbound:
    print("  %s column(s) on other models point at one of these. A column cannot"
          % len(inbound))
    print("  outlive what it points at, so each goes, and its values with it.")
    print("  The last column says WHICH target pulls it, so a target can be")
    print("  dropped from the list to keep the column that hangs off it:")
    print()
    print("      %-30s %-30s %-8s    %s"
          % ("MODEL", "COLUMN", "ROWS", "POINTS AT"))
    for field in inbound:
        filled = 0
        Model = env.get(field.model)
        if Model is not None and field.name in Model._fields:
            filled = Model.sudo().with_context(active_test=False).search_count(
                [(field.name, '!=', False)])
        print("      %-30s %-30s %-8s -> %s"
              % (field.model[-30:], field.name[-30:],
                 "%s row%s" % (filled, "" if filled == 1 else "s"), field.relation))
    native = [f for f in inbound if not f.model.startswith('x_')]
    if native:
        print()
        print("  !! %s of those are on NATIVE models:" % len(native))
        for field in native:
            print("        %s.%s" % (field.model, field.name))
else:
    print("  nothing outside the list points at any of them")

# The manual fields on other models that DEPEND on those columns - a Studio
# related field whose path starts with one of them, a computed field that
# reads one. Under _force_unlink Odoo removes these along with the column,
# silently (ir_model.py, _prepare_update, the else branch), and the view that
# showed them is not told: "x_studio_project_id field is undefined" on the
# next form open. So they are found here, before anything goes, listed, and
# their view nodes removed with the columns' own. The closure, not only the
# first hop: a related of a related goes the same way.
dependents = []
seen = set()
frontier = [env[f.model]._fields[f.name] for f in inbound
            if f.model in env and f.name in env[f.model]._fields]
while frontier:
    field = frontier.pop()
    for dep in env.registry.get_dependent_fields(field):
        key = (dep.model_name, dep.name)
        if not dep.manual or dep.model_name in names or key in seen:
            continue
        seen.add(key)
        dependents.append((dep.model_name, dep.name, field.model_name, field.name))
        frontier.append(dep)
if dependents:
    print()
    print("  %s field(s) on other models depend on those columns. Odoo removes them"
          % len(dependents))
    print("  with the column, so they are treated as going too:")
    print("      %-30s %-32s %s" % ("MODEL", "FIELD", "DEPENDS ON"))
    for model_name, name, via_model, via in dependents:
        print("      %-30s %-32s %s.%s" % (model_name[-30:], name[-32:], via_model[-22:], via[-22:]))

# The views that show those columns - or the fields going with them. Edited,
# never deleted.
edits = []
doomed_fields = [(f.model, f.name) for f in inbound] + [(m, n) for m, n, _, _ in dependents]
for model_name, name in doomed_fields:
    token = 'name="%s"' % name
    for view in View.search([('model', '=', model_name), ('arch_db', 'like', name)]):
        if token in (view.arch_db or ''):
            edits.append((view, name))
if edits:
    print()
    print("  %s view(s) elsewhere show one of those columns. Each view is KEPT"
          % len(edits))
    print("  and only that one field node is removed from its arch:")
    for view, field_name in edits[:20]:
        print("      %-40s drop the %s node"
              % ((view.display_name or str(view.id))[:40], field_name[-30:]))
    if len(edits) > 20:
        print("      ... and %s more" % (len(edits) - 20))

# ----------------------------------------------------------------------
title("4. DELETE")

if not APPLY:
    print("  DRY RUN - nothing was touched.")
    print("  Re-run with APPLY=1 once sections 1 to 3 are acceptable.")
    env.cr.rollback()
else:
    # Each phase commits on its own. One transaction for the lot means a
    # deadlock in the last phase throws away the first three, and dropping a
    # column deadlocks with the branch's own web worker often enough to matter.
    env.cr.execute("SET lock_timeout = '60s'")

    def attempt(work, label, tries=5):
        for number in range(1, tries + 1):
            try:
                work()
                env.cr.commit()
                return True
            except Exception as exc:                            # noqa: BLE001
                env.cr.rollback()
                env.cr.execute("SET lock_timeout = '60s'")
                reason = " ".join(str(exc).split())[:90]
                if number == tries:
                    print("  %-20s gave up after %s tries: %s" % (label, tries, reason))
                    return False
                print("  %-20s attempt %s failed (%s), waiting %ss"
                      % (label, number, reason, number * 5))
                time.sleep(number * 5)
        return False

    def sweep(table, column, label, batch=5000):
        """Delete rows of a bookkeeping table keyed by model name, by SQL.

        mail.message, mail.followers and mail.activity are pure bookkeeping:
        one row per (model, res_id), nothing computed from them. Unlinking them
        through the ORM one at a time pulled the followers and partners of
        every message - a SELECT on res_partner with four hundred thousand ids
        in it - and the connection died 23,397 messages into 74,620. A DELETE
        by model name is what these rows are for, and the tables that hang
        off them (notifications, tracking values, reactions) cascade in
        PostgreSQL. Batched, each batch committed, so a run that dies resumes.
        """
        total = 0
        while True:
            env.cr.execute(
                "DELETE FROM %s WHERE id IN (SELECT id FROM %s WHERE %s = ANY(%%s) LIMIT %%s)"
                % (table, table, column), (sorted(names), batch))
            count = env.cr.rowcount
            env.cr.commit()
            total += count
            if count < batch:
                break
        if total:
            print("  %-20s %s removed" % (label, total))

    def drop(records, label, chunk=500):
        """Unlink in chunks, each chunk committed, and in passes: a view that
        is another view's parent only goes once the child has, and the same
        holds for menus. One record at a time was the previous shape, and it
        held one transaction open across seventy thousand unlinks."""
        if not records:
            return
        total = len(records)
        left = records
        last = ''
        while left:
            stuck = left.browse()
            for start in range(0, len(left), chunk):
                piece = left[start:start + chunk]
                try:
                    with env.cr.savepoint():
                        piece.unlink()
                except Exception:                               # noqa: BLE001
                    # The chunk has one bad record in it; find it alone.
                    for record in piece:
                        try:
                            with env.cr.savepoint():
                                record.unlink()
                        except Exception as exc:                # noqa: BLE001
                            stuck |= record
                            last = " ".join(str(exc).split())[:80]
                env.cr.commit()
            if len(stuck) == len(left):
                print("  %-20s %s of %s removed, %s refused: %s"
                      % (label, total - len(stuck), total, len(stuck), last))
                break
            left = stuck
        else:
            print("  %-20s %s of %s removed" % (label, total, total))
        env.cr.commit()

    # Whose parents to reconsider afterwards - captured before the menus go,
    # because a deleted menu no longer has one.
    Menus = env['ir.ui.menu'].sudo().with_context(active_test=False)
    parents = set(attached.get("menu", Menus).mapped('parent_id').ids)

    # What is BENEATH a menu that is about to go. ir.ui.menu.unlink does not
    # delete children - it detaches them and promotes them to the top level -
    # so deleting "Setup" because its model was a target turned Work Entry
    # Types, Working Schedules and Salary Rule into three new apps on the
    # dashboard. Each descendant is decided here first: Studio-owned and
    # opening nothing or a native model, it goes with its parent, deepest
    # first; opening a Studio model that still exists, or owned by a module,
    # it is moved up to the doomed menu's own parent so it stays inside the
    # app instead of surfacing as an app of its own.
    menu_owner = {row['res_id']: row['module'] for row in
                  Data.search_read([('model', '=', 'ir.ui.menu')], ['res_id', 'module'])}

    def beneath(menu):
        out = []
        for child in Menus.search([('parent_id', '=', menu.id)]):
            out.append(child)
            out.extend(beneath(child))
        return out

    def opens_live_studio(menu):
        action = menu.action
        model = None
        if action and action._name == 'ir.actions.act_window':
            model = action.res_model
        elif action and action._name == 'ir.actions.server' and action.model_id:
            model = action.model_id.model
        return bool(model and model.startswith('x_') and model in env and model not in names)

    with_parent, lifted = Menus, 0
    for menu in attached.get("menu", Menus):
        for child in beneath(menu):
            module = menu_owner.get(child.id)
            studio = module in (None, 'studio_customization', '__export__')
            if studio and not opens_live_studio(child):
                with_parent |= child
            else:
                child.write({'parent_id': menu.parent_id.id})
                lifted += 1
    if with_parent:
        drop(with_parent.sorted(key=lambda m: -(m.complete_name or '').count('/')),
             "menu beneath")
    if lifted:
        print("  %-20s %s moved up a level rather than promoted to the top"
              % ("menu kept", lifted))
        env.cr.commit()

    for label in ("menu", "scheduled action", "automation", "server action",
                  "window action", "view", "record rule", "access rule",
                  "filter", "attachment"):
        drop(attached.get(label), label)

    # The chatter. Activities first (they reference nothing that follows),
    # then followers, then messages - and their notifications cascade.
    sweep('mail_activity', 'res_model', "activity")
    sweep('mail_followers', 'res_model', "follower")
    sweep('mail_message', 'model', "message")

    # The field nodes on other models' views. Those views survive.
    fixed = 0
    for view, field_name in edits:
        try:
            with env.cr.savepoint():
                arch = etree.fromstring(view.arch_db.encode())
                gone = False
                for node in arch.xpath("//field[@name='%s']" % field_name):
                    node.getparent().remove(node)
                    gone = True
                if gone:
                    view.write({'arch': etree.tostring(arch, encoding='unicode')})
                    fixed += 1
        except Exception as exc:                                # noqa: BLE001
            print("      view %s not edited: %s"
                  % (view.id, " ".join(str(exc).split())[:80]))
    if edits:
        print("  %-20s %s of %s edited (one field node removed)"
              % ("outside view", fixed, len(edits)))
    env.cr.commit()

    # Under the same flag as the target fields, and for the same reason:
    # Odoo refuses a field "still present in views" after LIKE-ing its name
    # against every view in the database. Twelve of twenty-five refused that
    # way once, the models went anyway (PostgreSQL drops the constraint with
    # the table), and twelve field definitions were left pointing at nothing.
    forced = dict(env.context, _force_unlink=True)
    drop(inbound.with_context(forced), "inbound column")

    # A table of millions goes in one statement, first. The messages,
    # followers, activities and attachments of its rows are already swept
    # above, so unlinking them twenty thousand at a time buys nothing and
    # cost an hour on thirteen million store lines; and while such a table
    # stands, every row deleted from a model it references is checked
    # against all of it. TRUNCATE when everything that references the table
    # is itself on the list (CASCADE reaches only those); DELETE otherwise.
    big = {}
    for name in ordered:
        Model = env.get(name)
        if Model is None or not Model._auto:
            continue
        env.cr.execute("SELECT reltuples::bigint FROM pg_class WHERE relname = %s", (Model._table,))
        found = env.cr.fetchone()
        if found and found[0] > 100000:
            big[name] = Model._table
    target_tables = {env[n]._table for n in ordered if n in env}
    for name, table in big.items():
        env.cr.execute("""
            SELECT DISTINCT c.conrelid::regclass::text
              FROM pg_constraint c
             WHERE c.contype = 'f' AND c.confrelid = %s::regclass
        """, (table,))
        referrers = {row[0].strip('"') for row in env.cr.fetchall()} - {table}
        env.cr.execute('SELECT count(*) FROM "%s"' % table)
        count = env.cr.fetchone()[0]
        if referrers <= target_tables:
            env.cr.execute('TRUNCATE TABLE "%s" CASCADE' % table)
            how = "truncated"
        else:
            env.cr.execute('DELETE FROM "%s"' % table)
            how = "deleted in one statement"
        env.cr.commit()
        print("  %-42s %s row(s) %s" % (name[-42:], count, how))

    for name in ordered:
        Model = env.get(name)
        if Model is None:
            continue
        Rows = Model.sudo().with_context(active_test=False)
        count = Rows.search_count([])
        if not count:
            continue
        done, failed = 0, ''
        while True:
            rows = Rows.search([], limit=20000)
            if not rows:
                break
            try:
                with env.cr.savepoint():
                    rows.unlink()
                env.cr.commit()
                done += len(rows)
            except Exception as exc:                            # noqa: BLE001
                env.cr.rollback()
                env.cr.execute("SET lock_timeout = '60s'")
                failed = " ".join(str(exc).split())[:70]
                break
        if failed:
            print("  %-42s %s of %s row(s) deleted, then: %s"
                  % (name[-42:], done, count, failed))
        else:
            print("  %-42s %s row(s) deleted" % (name[-42:], done))

    # Odoo refuses to drop a field while another depends on it, and refuses
    # again for fields "still present in views" - a check that LIKEs the field
    # name against every view in the database, so x_name is present in views on
    # any database that has had Studio on it. Both are skipped under
    # _force_unlink, the context Odoo sets on itself when a module is
    # uninstalled and its models go. Same situation, same route.
    attempt(lambda: IrField.with_context(forced)
            .search([('model', 'in', sorted(names))]).unlink(), "field drop")

    remaining = list(ordered)
    while remaining:
        stuck = []
        for name in remaining:
            model = IrModel.with_context(forced).search([('model', '=', name)], limit=1)
            if not model:
                continue
            if attempt(model.unlink, "drop %s" % name[-14:], tries=3):
                print("  %-42s model removed" % name[-42:])
            else:
                stuck.append(name)
        if len(stuck) == len(remaining):
            print()
            print("  %s model(s) would not go:" % len(stuck))
            for name in stuck:
                print("      %s" % name)
            break
        remaining = stuck

    # The menus above are gone; their parents may now be headings over nothing.
    # A parent goes only if THIS run emptied it, it is Studio's or unowned, and
    # it has no action of its own. A menu a module owns is that module's - it
    # comes back on the next upgrade regardless - and emptiness alone is never
    # evidence: half the native menus are empty containers.
    Menu = env['ir.ui.menu'].sudo().with_context(active_test=False)
    owners = {row['res_id']: row['module'] for row in
              Data.search_read([('model', '=', 'ir.ui.menu')], ['res_id', 'module'])}
    candidates = set(parents)
    while candidates:
        went = set()
        for menu_id in sorted(candidates):
            menu = Menu.browse(menu_id).exists()
            if not menu:
                went.add(menu_id)
                continue
            module = owners.get(menu.id)
            if module and module not in ('studio_customization', '__export__'):
                continue
            if menu.action or Menu.search_count([('parent_id', '=', menu.id)]):
                continue
            parent = menu.parent_id.id
            try:
                with env.cr.savepoint():
                    print("  %-42s emptied by this run, removed"
                          % (menu.complete_name or '')[-42:])
                    menu.unlink()
                went.add(menu_id)
                if parent:
                    candidates.add(parent)
            except Exception:                                   # noqa: BLE001
                went.add(menu_id)
        candidates -= went
        if not went:
            break
        env.cr.commit()

    env.cr.commit()
    print()
    print("  Done, and committed phase by phase. This cannot be undone.")

print()
print("=" * WIDTH)
