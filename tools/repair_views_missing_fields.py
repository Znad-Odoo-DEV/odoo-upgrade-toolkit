"""Mend the Studio views Odoo refuses to validate, by removing what Odoo names.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http < tools/repair_views_missing_fields.py
    SSC_VIEWS=2208,4422    only these view ids (default: every Studio-owned view)

    APPLY=1   edit. Without it, list only.

When a column is force-unlinked, or a related path stops resolving, Odoo
drops the manual field from its model - silently - and the view that showed
it is not told. The next form open stops on "field is undefined", and until
then the broken view poisons its neighbours: Odoo refuses to remove or retype
any field whose name appears in it, and reports that as the field being
present in views rather than as the view being broken.

Guessing which model a field node belongs to from the arch does not work on
inherited views - a <field position="after"> is a locator, an <xpath> into a
list has no field ancestor - so this asks Odoo instead: _check_xml on the
view, and when the answer is

    Field "X" does not exist in model "M"

remove the display nodes named X - never a locator, which carries a position
attribute - and ask again, until the view validates or the answer is
something else, which is reported and left.

Two things about where Odoo checks and where the node lives. _check_xml
validates the COMBINED arch, the base view with everything that inherits from
it applied, so the error surfaces on the base view while the node that names
the missing field is usually in a Studio customization inheriting from it.
The node is looked for in the view itself first and then down through every
Studio-owned view that inherits from it. And ir.ui.view.write validates on
its way in, which refuses the first removal whenever a second field is also
missing; so during the search the arch is written by SQL, and the view is
validated by the same _check_xml once the search is done - and again, on the
real write, before anything is committed.

One thing the arch does say, and is used: on a view that inherits from
nothing, a node's model is known. Walk up to the nearest <field> that embeds
a subview and resolve it from the view's own model - the outer form's x_name
is on the form's model, the x_name inside <field name="x_employee_ids"><list>
is on hr.employee. So when Odoo names model M, a node the arch places on some
other model is never touched; only nodes on M, or nodes whose model the arch
cannot tell (everything in an inherited view), are candidates. Without this
the form's own x_name was renamed to "name", then dropped when Odoo objected
to that, and the embedded column was reached only afterwards.

Only views Studio owns are edited. A view a module owns is never touched.
"""
import json
import os
import re

from lxml import etree

APPLY = os.environ.get('APPLY') == '1'
VIEW_IDS = [int(x) for x in (os.environ.get('SSC_VIEWS') or '').replace(' ', '').split(',') if x]
MAX_ROUNDS = 24

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env
cr = env.cr
View = env['ir.ui.view'].sudo().with_context(active_test=False)
Data = env['ir.model.data'].sudo()

MISSING = re.compile(r'Field "([^"]+)" does not exist in model "([^"]+)"')

# Left in place on purpose: the money readers. tools/rebuild_employee_money_readers
# lifts their nodes out itself, recording where each one sat, so it can put the
# field back monetary in the same spot. Remove them here and there is nothing
# to put back. A view broken by nothing but these counts as mended here.
MONEY_LATER = {'x_studio_basic_salary', 'x_studio_gross_salary', 'x_studio_total_salary',
               'x_studio_total_gross_salary'}

# Renamed rather than removed: a column of the old employee list shown in an
# embedded list that now lists hr.employee. Dropping x_name would leave the
# list with no columns; the native record has the same column under its own name.
RENAMES = {('hr.employee', 'x_name'): 'name', ('hr.employee', 'x_active'): 'active'}

owner = {r['res_id']: r['module'] for r in
         Data.search_read([('model', '=', 'ir.ui.view')], ['res_id', 'module'])}


def studio_owned(view):
    return owner.get(view.id) in (None, 'studio_customization', '__export__')


def failure(view):
    """None when the combined view validates; the flattened message otherwise."""
    try:
        with cr.savepoint():
            view._check_xml()
        return None
    except Exception as exc:                                    # noqa: BLE001
        return " ".join(str(exc).split())


def family(view):
    """The view and every Studio-owned view inheriting from it, depth first."""
    out = [view]
    for child in View.search([('inherit_id', '=', view.id)], order='priority, id'):
        if studio_owned(child):
            out.extend(family(child))
    return out


def arch_of(view):
    cr.execute("SELECT arch_db->>'en_US', arch_db FROM ir_ui_view WHERE id = %s", (view.id,))
    text, raw = cr.fetchone()
    if text is None:
        # a view without a translation key, or a plain string
        text = raw if isinstance(raw, str) else json.dumps(raw)
    return text


def set_arch(view, text):
    """Write arch_db without ir.ui.view.write, which validates on the way in."""
    cr.execute("""UPDATE ir_ui_view
                     SET arch_db = jsonb_set(COALESCE(arch_db, '{}'::jsonb), '{en_US}', to_jsonb(%s::text))
                   WHERE id = %s""", (text, view.id))
    view.invalidate_recordset(['arch_db', 'arch'])


def node_model(node, view):
    """The model a display node is shown on when the arch can say - a view
    that inherits from nothing, resolved through the fields that embed it -
    or None when it cannot (an inherited view: xpaths and locators give no
    model)."""
    if view.inherit_id:
        return None
    embedding = []
    parent = node.getparent()
    while parent is not None:
        if parent.tag == 'field' and not parent.get('position'):
            embedding.append(parent.get('name'))
        parent = parent.getparent()
    model = view.model
    for field_name in reversed(embedding):
        field = env[model]._fields.get(field_name) if model in env else None
        if field is None or not getattr(field, 'comodel_name', None):
            return None
        model = field.comodel_name
    return model


def remove_display_nodes(name, model, views, rename_to=None):
    """Remove - or rename, when rename_to is given - the <field name=name>
    display nodes of the first view in `views` whose own arch holds any that
    the arch places on `model`, or cannot place at all. A node the arch puts
    on another model is left where it is. Returns (view, count) or (None, 0)."""
    for v in views:
        try:
            tree = etree.fromstring(arch_of(v).encode())
        except Exception:                                       # noqa: BLE001
            continue
        named = [n for n in tree.iter('field') if n.get('name') == name and not n.get('position')]
        placed = [(n, node_model(n, v)) for n in named]
        nodes = [n for n, m in placed if m == model] or [n for n, m in placed if m is None]
        if not nodes:
            continue
        for n in nodes:
            if rename_to:
                n.set('name', rename_to)
            else:
                n.getparent().remove(n)
        set_arch(v, etree.tostring(tree, encoding='unicode'))
        return v, len(nodes)
    return None, 0


def only_money_left(message):
    """True when the one thing Odoo still objects to is a money reader."""
    match = MISSING.search(message or '')
    return bool(match) and match.group(1) in MONEY_LATER


def lift_money(views):
    """Take the money-reader nodes out of these views, by SQL, so Odoo can be
    asked what ELSE is missing. Only ever inside a savepoint that is rolled
    back: the nodes stay in place for rebuild_employee_money_readers. Without
    this the search stopped at the first money reader and never saw
    x_studio_year1grat behind it in view 8549."""
    for v in views:
        try:
            tree = etree.fromstring(arch_of(v).encode())
        except Exception:                                       # noqa: BLE001
            continue
        nodes = [n for n in tree.iter('field')
                 if n.get('name') in MONEY_LATER and not n.get('position')]
        nodes += [n for n in tree.iter('label') if n.get('for') in MONEY_LATER]
        if not nodes:
            continue
        for n in nodes:
            n.getparent().remove(n)
        set_arch(v, etree.tostring(tree, encoding='unicode'))


def validates_without_money(base, kin):
    """The combined view's error with the money nodes out of the way, or None.
    Lifted in a savepoint that is rolled back, so nothing moves."""
    with cr.savepoint() as sp:
        lift_money(kin)
        left = failure(base)
        sp.rollback()
    for v in kin:
        v.invalidate_recordset(['arch_db', 'arch'])
    return left


def plan_for(view):
    """[(field, model, in_view_id, count)] and the error left at the end (None
    when the view validates once they are gone). Done for real inside a
    savepoint that is rolled back before returning."""
    removals, residual = [], None
    with cr.savepoint() as sp:
        kin = family(view)
        lift_money(kin)                 # rolled back with the savepoint
        for _round in range(MAX_ROUNDS):
            message = failure(view)
            if message is None:
                break
            match = MISSING.search(message)
            if not match:
                residual = message
                break
            name, model = match.group(1), match.group(2)
            if name in MONEY_LATER:
                residual = None             # the money rebuild takes it from here
                break
            rename_to = RENAMES.get((model, name))
            where, count = remove_display_nodes(name, model, kin, rename_to)
            if where is None:
                residual = ("Odoo names %s.%s but neither this view nor any Studio view "
                            "inheriting from it holds a display node of that name on that "
                            "model" % (model, name))
                break
            removals.append((name, model, where.id, count, rename_to))
        else:
            residual = "still failing after %s rounds" % MAX_ROUNDS
        sp.rollback()
    for v in family(view):
        v.invalidate_recordset(['arch_db', 'arch'])
    return removals, residual


ids = VIEW_IDS or [r['res_id'] for r in Data.search_read(
    [('model', '=', 'ir.ui.view'), ('module', '=', 'studio_customization')], ['res_id'])]
views = View.browse(ids).exists()

print("  checking %s view(s)" % len(views))
broken, fixable, stuck, seen = 0, [], [], set()
for view in views:
    if not studio_owned(view) or view.id in seen:
        continue
    if failure(view) is None:
        continue
    # A broken combined arch shows up on the base and on every child; work it
    # once, from the base.
    base = view
    while base.inherit_id and base.inherit_id.id in views.ids:
        base = base.inherit_id
    if base.id in seen:
        continue
    seen.add(base.id)
    broken += 1
    removals, residual = plan_for(base)
    line = "  view %-6s %-24s %s" % (base.id, (base.model or '')[-24:], (base.name or '')[:40])
    if removals and residual is None:
        fixable.append((base, removals))
        print(line)
        for name, model, in_view, count, rename_to in removals:
            verb = ("rename to %s" % rename_to) if rename_to else "drop"
            print("      %-16s %-40s in view %-6s (%s node(s); Odoo: not on %s)"
                  % (verb, name, in_view, count, model))
        left = failure(base)
        if left and only_money_left(left):
            print("      then only money readers are missing - left for rebuild_employee_money_readers")
    elif not removals and residual is None:
        print(line + "   only money readers are missing - left for rebuild_employee_money_readers")
    else:
        stuck.append((base, removals, residual))
        print(line + "   LEFT ALONE")
        for name, model, in_view, count, rename_to in removals:
            print("      would %s %-30s in view %s, but it does not end there"
                  % ("rename" if rename_to else "drop", name, in_view))
        print("      %s" % (residual or '')[:160])

print()
print("  %s broken, %s mendable by removing what Odoo names, %s left alone"
      % (broken, len(fixable), len(stuck)))

if not fixable:
    cr.rollback()
elif not APPLY:
    print("  DRY RUN - nothing changed. Re-run with APPLY=1.")
    cr.rollback()
else:
    done = 0
    for base, removals in fixable:
        try:
            with cr.savepoint():
                kin = family(base)
                for name, model, _in_view, _count, rename_to in removals:
                    remove_display_nodes(name, model, kin, rename_to)
                for v in kin:
                    v.invalidate_recordset(['arch_db', 'arch'])
                left = validates_without_money(base, kin)
                if left:
                    raise ValueError(left)          # must validate, or the savepoint unwinds
            done += 1
        except Exception as exc:                                # noqa: BLE001
            print("      view %s reverted: %s" % (base.id, " ".join(str(exc).split())[:120]))
    cr.commit()
    print("  %s of %s view(s) mended and re-validated. Committed." % (done, len(fixable)))
