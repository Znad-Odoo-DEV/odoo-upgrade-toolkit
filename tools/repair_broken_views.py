"""Find the views that will not validate, and mend the ones with a known cause.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/repair_broken_views.py

A view that fails to validate poisons everything near it. Odoo refuses to delete
or retype any field whose name appears in a broken view - and reports that as
"the field is still present in views", naming a view that is broken for a reason
that has nothing to do with the field. Every tool that touches a field then
stops on a wall it did not build and cannot see.

One cause is ours and is repaired here: a button calling an action that no
longer exists. Deleting a server action is right when the model it names is
going; leaving the button that calls it is what turns a tidy removal into a
blocked database.

Everything else is reported with the whole message, because the whole message is
the only useful part and every tool in this directory has cut it short at least
once.

Why this is worth running on its own, before anything else: Odoo re-validates
the custom views of the database whenever a manual field is removed, so a single
view that will not validate refuses every Studio field deletion anywhere - and
refuses it with a sentence about the field, naming a view that has nothing to do
with it. One broken view stopped fifty-eight model deletions in a row.

SSC_DROP_BROKEN=1 removes the ones that are left, the views inheriting them
first: inherit_id is a foreign key, and a parent whose child still names it
fails as a bad query on ir_ui_view rather than as anything readable.
"""
import os
import re

from lxml import etree

DRY_RUN = os.environ.get('SSC_WRITE') != '1'
# Removing a view that will not validate, once its cause has been read and is
# not one this tool knows how to mend. Asked for separately from SSC_WRITE=1,
# because the buttons are a repair and this is a removal.
DROP_BROKEN = os.environ.get('SSC_DROP_BROKEN') == '1'

cr = env.cr                                                      # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def _validates(view):
    try:
        with cr.savepoint():
            view._check_xml()
        return True
    except Exception:
        return False


def ours(view):
    """Whether this teardown is entitled to remove a view.

    Only when the model it belongs to does not exist. Nothing else, and the rule
    used to be looser: any view of a model whose name began with x_ counted as
    Studio's and therefore disposable. It is not. x_staff_attendance,
    x_structural_elements and x_subcontractors are models people use every day,
    and their forms were broken before any of this started - by native projects
    taking x_studio_under_saud_shehatha_construction_llc off project.project and
    leaving the domains that asked for it.

    A broken view gets mended. A view whose model is gone gets removed. There is
    no third case, and inventing one is how a form ends up holding its title and
    nothing else.
    """
    model = view.model or ''
    return bool(model) and env.get(model) is None                # noqa: F821


def drop_view(view, depth=0):
    """Remove a view, the views that inherit it first."""
    if not view.exists():
        return True
    if depth <= 6:
        for child in View.search([('inherit_id', '=', view.id)]):
            drop_view(child, depth + 1)
    try:
        with cr.savepoint():
            view.unlink()
        return True
    except Exception as exc:
        print("  ! %-6s %s" % (view.id, why(exc)))
        return False


def why(exc):
    """The head and the tail of the refusal, because the cause is at the end.

    "Error while validating view near:" is a heading, what follows it is an
    excerpt of the arch, and the sentence that says what is actually wrong -
    Field x does not exist in model y - is the last line of all. Printing the
    first six lines prints the heading and five lines of XML, which is how
    twelve broken views were looked at without once being read.
    """
    lines = [line.rstrip() for line in str(exc).strip().splitlines() if line.strip()]
    if not lines:
        return ''
    if len(lines) <= 6:
        shown = lines
    else:
        shown = lines[:2] + ['...'] + lines[-3:]
    return shown[0] + ''.join('\n           ' + line for line in shown[1:])


# --- 1. buttons calling an action that is gone -------------------------------

title("1. buttons calling an action that no longer exists")

FIELD_GONE = re.compile(r'Field "([^"]+)" does not exist in model "([^"]+)"')
# Unknown field "project.project.x_studio_under_saud_shehatha_construction_llc"
# in domain of <field name="x_studio_project">
DOMAIN_GONE = re.compile(
    r'Unknown field "([^"]+)" in domain of <field name="([^"]+)">')

cr.execute("SELECT id FROM ir_actions")
live = {str(row[0]) for row in cr.fetchall()}

# arch_db is jsonb and its text form escapes every quote, so a pattern with a
# quote in it matches nothing. Match the tag, which has none.
cr.execute("""SELECT id FROM ir_ui_view WHERE arch_db::text LIKE '%<button%'""")
candidates = [row[0] for row in cr.fetchall()]

plan = []
for view_id in candidates:
    view = View.browse(view_id).exists()
    if not view:
        continue
    try:
        tree = etree.fromstring((view.arch or '').encode())
    except Exception:
        continue
    orphans = [node for node in tree.xpath("//button[@type='action']")
               if (node.get('name') or '').isdigit()
               and node.get('name') not in live]
    if orphans:
        plan.append((view, tree, orphans))

for view, _tree, orphans in plan:
    names = sorted({node.get('name') for node in orphans})
    print("  %-6s %-30s %s button(s)  action %s"
          % (view.id, view.model or '-', len(orphans), ', '.join(names)))
print("\n  %s view(s) hold %s orphan button(s)"
      % (len(plan), sum(len(o) for _v, _t, o in plan)))


# --- 2. what still will not validate ----------------------------------------

title("2. views that fail to validate as things stand")

broken = []
for view in View.search([]):
    try:
        with cr.savepoint():
            view._check_xml()
    except Exception as exc:
        broken.append((view, str(exc)))

for view, reason in broken[:25]:
    print("\n  %-6s %-26s %s" % (view.id, view.model or '-', (view.name or '')[:40]))
    print("         %s" % why(reason))
if len(broken) > 25:
    print("\n  ... and %s more" % (len(broken) - 25))
print("\n  %s view(s) fail" % len(broken))


# --- 2b. the ones whose cause is a field that is not there -------------------

title("2b. views naming a field their model does not have")

mendable = []
for view, reason in broken:
    match = FIELD_GONE.search(reason)
    if not match:
        continue
    field_name, model_name = match.group(1), match.group(2)
    owner = env.get(model_name)                                  # noqa: F821
    if owner is not None and field_name in owner._fields:
        continue                          # it does exist; the cause is elsewhere
    mendable.append((view, field_name, model_name))
    print("  %-6s %-26s %-42s not in %s"
          % (view.id, view.model or '-', field_name, model_name))
print("\n  %s view(s) can have the node taken out" % len(mendable))


# --- 2c. domains asking a model for a field it does not have ----------------

title("2c. domains naming a field the model they filter does not have")

domainless = []
for view, reason in broken:
    match = DOMAIN_GONE.search(reason)
    if not match:
        continue
    domainless.append((view, match.group(1), match.group(2)))
    print("  %-6s %-26s on %-30s no %s"
          % (view.id, view.model or '-', match.group(2), match.group(1)))
print("\n  %s view(s) hold a domain that cannot be evaluated" % len(domainless))
if domainless:
    print("""
  The domain goes and the field stays. These were broken before any of this
  began - the Studio fields those domains ask for were taken off project.project
  and product.template when the native projects went live - and a form that will
  not open is worse than a dropdown that offers everything. Say so to whoever
  uses the screen: the filtering is gone, not the field.""")
if mendable:
    print("""
  Taking the node out is tried and then checked: if the view validates
  afterwards the change stays, and if it does not the change is rolled back and
  the view is reported as it was. A field nobody can resolve is not a layout
  worth keeping, but being wrong about which node it was is.""")

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing changed. Run again with SSC_WRITE=1 to remove the")
    print("  orphan buttons in section 1, and SSC_DROP_BROKEN=1 as well to remove")
    print("  whatever section 2 still holds afterwards.")
    cr.rollback()
    raise SystemExit()


# --- 3. remove them ----------------------------------------------------------

title("3. removing the orphan buttons")

removed = 0
if not plan:
    print("  none to remove")
for view, tree, orphans in plan:
    for node in orphans:
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    try:
        with cr.savepoint():
            view.arch = etree.tostring(tree, encoding='unicode')
        removed += len(orphans)
        print("  > %-6s %-30s %s removed" % (view.id, view.model or '-', len(orphans)))
    except Exception as exc:
        print("  ! %-6s %s" % (view.id, why(exc)))
cr.commit()

print("\n  %s button(s) removed" % removed)


if mendable:
    title("3b. taking those nodes out")

    for view, field_name, model_name in mendable:
        if not view.exists() or _validates(view):
            continue
        try:
            tree = etree.fromstring((view.arch or '').encode())
        except Exception:
            continue
        nodes = tree.xpath("//field[@name='%s'] | //label[@for='%s']"
                           % (field_name, field_name))
        if not nodes:
            print("  . %-6s %-42s not in this view's own arch" % (view.id, field_name))
            continue
        for node in nodes:
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
        try:
            with cr.savepoint():
                view.arch = etree.tostring(tree, encoding='unicode')
                view._check_xml()
            print("  - %-6s %-26s %s node(s) of %s"
                  % (view.id, view.model or '-', len(nodes), field_name))
        except Exception as exc:
            # The write is rolled back with the savepoint, so the view is
            # exactly as it was and the next section will still report it.
            view.invalidate_recordset()
            print("  . %-6s %-26s kept: %s" % (view.id, view.model or '-', why(exc)))
    cr.commit()


if domainless:
    title("3c. taking those domains out")

    for view, wanted, node_name in domainless:
        if not view.exists() or _validates(view):
            continue
        try:
            tree = etree.fromstring((view.arch or '').encode())
        except Exception:
            continue
        nodes = [node for node in tree.xpath("//field[@name='%s']" % node_name)
                 if node.get('domain')]
        if not nodes:
            print("  . %-6s %-30s no domain in this view own arch"
                  % (view.id, node_name))
            continue
        for node in nodes:
            del node.attrib['domain']
        try:
            with cr.savepoint():
                view.arch = etree.tostring(tree, encoding='unicode')
                view._check_xml()
            print("  - %-6s %-26s domain off %s (wanted %s)"
                  % (view.id, view.model or '-', node_name, wanted))
        except Exception as exc:
            view.invalidate_recordset()
            print("  . %-6s %-26s kept: %s" % (view.id, view.model or '-', why(exc)))
    cr.commit()


title("4. what fails now")

still = []
for view in View.search([]):
    if _validates(view):
        continue
    still.append(view)
    if len(still) <= 15:
        try:
            with cr.savepoint():
                view._check_xml()
        except Exception as exc:
            print("\n  %-6s %-26s %s"
                  % (view.id, view.model or '-', (view.name or '')[:40]))
            print("         %s" % why(exc))
print("\n  %s view(s) still fail" % len(still))

if still and DROP_BROKEN:
    title("5. removing them")
    gone, kept = 0, []
    # Studio's own first: removing a broken customisation mends every native
    # view it inherits, and those are then no longer on the list to argue about.
    for view in sorted(still, key=lambda v: not ours(v)):
        if not view.exists():
            continue
        view_id, view_model = view.id, view.model or '-'
        name = (view.name or '')[:40]
        if _validates(view):
            print("  . %-6s %-26s mended by an earlier removal" % (view_id, view_model))
            continue
        if not ours(view):
            kept.append((view_id, view_model, name))
            continue
        if drop_view(view):
            gone += 1
            print("  - %-6s %-26s %s" % (view_id, view_model, name))
    cr.commit()
    print("\n  %s view(s) removed" % gone)
    if kept:
        print("  %s left alone - not Studio's, and the model still exists:" % len(kept))
        for view_id, view_model, name in kept:
            print("      %-6s %-26s %s" % (view_id, view_model, name))
    print("  %s view(s) still fail"
          % sum(1 for v in View.search([]) if not _validates(v)))
print("""
  A view that still fails is broken for a reason this tool does not know, and
  the reason is printed above rather than guessed at. Until it is mended, every
  field whose name appears in it cannot be removed or retyped - and the refusal
  will name the field rather than the view.""")
