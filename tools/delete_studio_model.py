"""Delete a Studio model and everything that belonged to it. One at a time.

    SSC_MODEL=x_to_pay odoo-bin shell --no-http < tools/delete_studio_model.py
    SSC_MODEL=x_to_pay SSC_CONFIRM=x_to_pay odoo-bin shell --no-http < tools/delete_studio_model.py

The only tool here with no way back, and the only one that does not take
SSC_WRITE=1 as permission. It wants the model's own name typed again, because a
flag set once for the previous command is not consent for this one.

The rule that matters, learned the hard way twice: a view is only ever edited
inside the savepoint of the removal that needed the edit. If the removal is
refused, the edit is rolled back with it. Stripping the nodes first and
committing them left x_all_requests - a model nobody was deleting - with a form
holding its title and nothing else, because the deletion that the stripping was
for did not go through.

What it refuses to do:

 * delete a model something still points at, unless that link is its own child
   or the link has been dropped first. A foreign key into a table that is gone
   is not a warning, it is a broken database.
 * delete a model with rows whose count does not match what was reported when
   the plan was made - if the number moved, something is writing to it and
   nobody said so.

What it does, in order: the incoming links that are safe to drop, the server
actions and automations that name it, the child line models, and then the model,
whose own views, actions, menus and access rules go with it because Odoo removes
them itself.

The rows are gone at that point. This tool cannot check whether they were
carried anywhere first, and does not pretend to: that is what the comparison
tools were for, and running this is the statement that they were read.
"""
import os
import re

MODEL = os.environ.get('SSC_MODEL') or ''
CONFIRM = os.environ.get('SSC_CONFIRM') or ''
DROP_LINKS = os.environ.get('SSC_DROP_LINKS') == '1'
DROP_CODE = os.environ.get('SSC_DROP_CODE') == '1'
# A view broken for reasons of its own blocks every field whose name appears in
# it, and says the field is at fault. Removing that view is a real change to
# somebody else's screen, so it is asked for rather than assumed - and only
# Studio's own generated defaults are ever candidates, because Odoo builds those
# again from the model when they are gone.
DROP_BROKEN_VIEWS = os.environ.get('SSC_DROP_BROKEN_VIEWS') == '1'

cr = env.cr                                                      # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821

if not MODEL:
    raise SystemExit("Set SSC_MODEL, e.g. SSC_MODEL=x_to_pay")

record = IrModel.search([('model', '=', MODEL)], limit=1)
Model = env.get(MODEL)                                           # noqa: F821
if not record or Model is None:
    raise SystemExit("%s is not a model in this database." % MODEL)


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


# --- 1. the model and its children -------------------------------------------

title("1. %s" % MODEL)

rows = 0
if table_exists(Model._table):
    cr.execute('SELECT COUNT(*) FROM "%s"' % Model._table)
    rows = cr.fetchone()[0]
print("  %s  (%s)" % (record.name, MODEL))
print("  %s row(s)" % rows)

# Its own line models. A one2many from here names most of them, but not for
# ever: an interrupted run that dropped the one2many leaves the line model
# behind, and the next run then sees it as an outside link and offers to drop
# the field and keep the model - two thousand rows in a table nothing reaches.
#
# So the name counts too. Studio calls a line model after its parent, and a
# model called x_all_payslips_line_953a2 with a many2one to x_all_payslips
# belongs to it whether or not the one2many that made it still exists.
children = {}


def remember(model_name):
    child = env.get(model_name)                                  # noqa: F821
    if child is None or model_name in children:
        return
    count = 0
    if table_exists(child._table):
        cr.execute('SELECT COUNT(*) FROM "%s"' % child._table)
        count = cr.fetchone()[0]
    children[model_name] = count


# A line model is named after its parent and points back at it. Both, and
# nothing else.
#
# The rule before this one said: any x_ model this one has a one2many to. That
# is not a line model, that is anything it holds a list of - and x_to_pay holds
# three lists of x_attachments_list, a model with two and a half thousand rows
# that half the payroll reads. It would have been deleted as a line of the
# thing that merely displays it. The preview caught the fields; nothing would
# have caught the model.
# All the way down. A line model has line models of its own, and stopping at
# the first level leaves the grandchildren behind: tables with thirty thousand
# rows in them that nothing can reach, because the model that held the list is
# gone.
frontier = {MODEL}
while frontier:
    found = set()
    for field in IrField.search([('relation', 'in', list(frontier)),
                                 ('ttype', '=', 'many2one')]):
        if field.model in children or field.model == MODEL:
            continue
        if field.model.startswith('%s_line' % field.relation):
            found.add(field.model)
    for name in found:
        remember(name)
    frontier = found

print("\n  line models that belong to it:")
for name, count in sorted(children.items()):
    print("      %-40s %s row(s)" % (name, count))
if not children:
    print("      none")


# --- 2. links in from elsewhere ----------------------------------------------

title("2. what still points at it")

incoming, blocking = [], []
for field in IrField.search([('relation', '=', MODEL)]).sorted(lambda f: f.model):
    if field.model in children:
        continue                       # its own child, going anyway
    table = (env[field.model]._table if env.get(field.model) is not None    # noqa: F821
             else field.model.replace('.', '_'))
    held = 0
    if field.ttype == 'many2many':
        if field.relation_table and table_exists(field.relation_table):
            cr.execute('SELECT COUNT(*) FROM "%s"' % field.relation_table)
            held = cr.fetchone()[0]
    elif column_exists(table, field.name):
        cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL'
                   % (table, field.name))
        held = cr.fetchone()[0]
    incoming.append((field, held))
    if field.state != 'manual':
        blocking.append(field)

for field, held in incoming:
    print("  %-9s %-32s %-34s %s row(s)" % (field.state, field.model, field.name, held))
if not incoming:
    print("  nothing outside its own lines")

if blocking:
    print("\n  %s of them belong to a module and cannot be dropped here:" % len(blocking))
    for field in blocking:
        print("      %s.%s" % (field.model, field.name))


# --- 3. code that names it ----------------------------------------------------

title("3. code that names it")

Server = env['ir.actions.server'].sudo()                         # noqa: F821

# As a whole word, not as a substring. There is a Studio model called x_ - just
# x_ - and it is a substring of every Studio name in the database. Asking which
# server actions name it, by containment, answers 398 of them: nearly all
# belonging to models that are staying. With SSC_DROP_CODE=1 that answer is
# acted on.
NAMES_MODEL = re.compile(r'(?<![\w.])%s(?![\w])' % re.escape(MODEL))
naming = [a for a in Server.search([]) if NAMES_MODEL.search(a.code or '')]
for action in naming:
    print("  action %-6s %s" % (action.id, (action.name or '')[:56]))

Automation = env.get('base.automation')                          # noqa: F821
rules = Automation.sudo().search([('model_id', '=', record.id)]) if Automation else []
for rule in rules:
    print("  rule   %-6s %-46s %s" % (rule.id, (rule.name or '')[:46],
                                      'on' if rule.active else 'off'))
print("\n  %s server action(s), %s automation(s)" % (len(naming), len(rules)))


# --- 4. what the deletion takes with it --------------------------------------

title("4. what goes with it, without being asked")

for label, model_name, domain in (
        ('views', 'ir.ui.view', [('model', '=', MODEL)]),
        ('window actions', 'ir.actions.act_window', [('res_model', '=', MODEL)]),
        ('filters', 'ir.filters', [('model_id', '=', MODEL)]),
        ('access rules', 'ir.model.access', [('model_id', '=', record.id)]),
        ('record rules', 'ir.rule', [('model_id', '=', record.id)]),
        ('messages', 'mail.message', [('model', '=', MODEL)]),
        ('followers', 'mail.followers', [('res_model', '=', MODEL)]),
):
    Target = env.get(model_name)                                 # noqa: F821
    if Target is None:
        continue
    print("  %-16s %s" % (label, Target.sudo().search_count(domain)))


# --- 5. the gate --------------------------------------------------------------

title("5. before this runs")

from lxml import etree                                           # noqa: E402

View = env['ir.ui.view'].sudo()                                  # noqa: F821
going = [MODEL] + list(children)


DEPENDS = re.compile(r"the field '([^']+)\.([^'.]+)' depends on it")

# "The field 'a.b' cannot be removed because the field 'c.d' depends on
# it." Both halves, because the answer is to remove them together: Odoo
# checks the dependency against the set being deleted, and a set holding
# both is not a set with a dangling dependency. Removing them one at a time
# is refused whichever one goes first, which is how x_attachments_list -
# and x_to_pay and x_staff_payslips behind it - stayed put.
CANNOT_REMOVE = re.compile(r"The field '([^']+)\.([^'.]+)' cannot be removed")


def refused_pair(exc):
    """The field that cannot go, and the one standing on it.

    Two patterns rather than one, because the sentence between them wraps and
    a single expression that spans the whole thing matches nothing the day the
    wording changes by a space.
    """
    text = str(exc)
    below = CANNOT_REMOVE.search(text)
    upon = DEPENDS.search(text)
    if not below or not upon:
        return None
    first = IrField.search([('model', '=', below.group(1)),
                            ('name', '=', below.group(2))], limit=1)
    second = IrField.search([('model', '=', upon.group(1)),
                             ('name', '=', upon.group(2))], limit=1)
    both = first | second
    if len(both) != 2:
        return None
    # One of them says a module declares it, which for a field called
    # x_studio_anything is never true - no module has ever declared one. The
    # state is simply wrong, the way it is wrong on res.users, and every tool
    # that respects the state then refuses to touch it. Handed back here,
    # named, and only for a name Studio gave it.
    for one in both:
        if one.state != 'manual' and one.name.startswith('x_'):
            cr.execute("UPDATE ir_model_fields SET state = 'manual' WHERE id = %s",
                       (one.id,))
            one.invalidate_recordset(['state'])
            print("  - state  %s.%s was recorded as a module's" % (one.model, one.name))
    return both if all(f.state == 'manual' for f in both) else None


def why(exc):
    """The whole refusal, indented, because the useful half is never line one.

    "Cannot rename/delete fields that are still present in views:" is a heading;
    the views it is about are on the lines after it. Four rounds of this were
    spent reading the heading and guessing at the list.
    """
    lines = [line.rstrip() for line in str(exc).strip().splitlines() if line.strip()]
    if not lines:
        return ''
    return lines[0] + ''.join('\n           ' + line for line in lines[1:6])


IN_VIEWS = re.compile(r"Fields:\s*(.+?)\s*\n\s*View:\s*(.+?)\s*$",
                      re.DOTALL | re.MULTILINE)
PAIR = re.compile(r"([A-Za-z_][\w.]*)\.([A-Za-z_]\w*)")


MISSING_ACTION = re.compile(r"Action (\d+) \(id: \d+\) does not exist")


def drop_view(view, depth=0):
    """Remove a view, the views that inherit it first.

    inherit_id is a foreign key, and Postgres will not let a view go while
    another names it. The refusal arrives as a bad query on ir_ui_view: it says
    nothing about views, nothing about the model, and nothing about the field
    that was being deleted three frames further up. It is what stopped
    fifty-eight deletions in a row, all of them reading as the model refusing.

    Studio makes two of everything - the default view it generates, and the
    customisation that inherits it - so the parent is never the only one.
    """
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
        print("  ! view   %-6s %s" % (view.id, why(exc)))
        return False


def clear_action_buttons(action_id):
    """Take the buttons that call a deleted action out of the views.

    This tool made this problem. It deletes the server actions that name the
    departing model - correctly, they would raise the next time they ran - and
    leaves the buttons that call them sitting in forms belonging to models that
    stay. Odoo then refuses to validate those views, and every later field
    deletion is told the field is "still present in views", naming a view that
    is broken for a reason nothing to do with the field.

    So the buttons go with the action, the way a field's nodes go with the
    field.
    """
    cr.execute("SELECT id FROM ir_ui_view WHERE arch_db::text LIKE %s",
               ('%' + str(action_id) + '%',))
    changed = 0
    for (view_id,) in cr.fetchall():
        view = View.browse(view_id).exists()
        if not view:
            continue
        try:
            tree = etree.fromstring((view.arch or '').encode())
        except Exception:
            continue
        nodes = tree.xpath("//button[@name='%s'][@type='action']" % action_id)
        if not nodes:
            continue
        for node in nodes:
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
        try:
            with cr.savepoint():
                view.arch = etree.tostring(tree, encoding='unicode')
            changed += len(nodes)
            print("  - button %s button(s) for action %s off view %s"
                  % (len(nodes), action_id, view.id))
        except Exception:
            pass
    return bool(changed)


def repair_orphan_action_buttons():
    """Remove buttons that call an action nobody can find.

    Waiting for the refusal to mention it does not work: the message about a
    missing action only appears when a view is asked to validate itself
    directly. What comes back from a field deletion is the blunt sentence about
    fields still present in views, naming a view that is broken for a reason
    the sentence never mentions.

    So the damage is repaired before anything else is attempted, and repaired
    everywhere rather than where a message happened to point. A button calling
    an action that does not exist is broken whoever broke it - this tool deleting
    the actions that named a departing model, or somebody deleting one by hand
    two years ago.
    """
    cr.execute("SELECT id FROM ir_actions")
    live = {str(row[0]) for row in cr.fetchall()}
    # arch_db is jsonb, and its text form escapes every quote:
    #     {"en_US": "<button name=\\"3204\\" type=\\"action\\"/>"}
    # so a pattern containing a quote matches nothing. Match the tag instead -
    # it has none - and let lxml do the rest.
    cr.execute("""SELECT id FROM ir_ui_view
                   WHERE arch_db::text LIKE '%<button%'""")
    removed = 0
    for (view_id,) in cr.fetchall():
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
        if not orphans:
            continue
        names = sorted({node.get('name') for node in orphans})
        for node in orphans:
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
        try:
            with cr.savepoint():
                view.arch = etree.tostring(tree, encoding='unicode')
            removed += len(orphans)
            print("  - button %s orphan(s) off view %-6s (%s)  action %s"
                  % (len(orphans), view.id, view.model or '-', ', '.join(names)))
        except Exception as exc:
            print("  ! button view %-6s %s" % (view.id, why(exc)))
    if removed:
        cr.commit()
    return removed


def clear_named_views(exc):
    """Take the fields Odoo named, of the models Odoo named, out of that view.

    A Studio customisation view holds a diff - <xpath> fragments, not a whole
    form - so walking a node's ancestors reaches the top of the fragment and
    tells you nothing about which model the node belongs to. Position cannot
    answer there.

    Odoo can. The refusal names the fields and the view: "Fields:
    x_to_pay.x_studio_attendance_id / View: Odoo Studio: Default form view for
    x_attendance_per_month customization" - and it names each field with the
    model it belongs to, which is the half that was being thrown away.

    Both halves are used now, and the position of the node decides whose it is,
    exactly as strip_from_views does. The view Odoo names is often not a view of
    anything being deleted, and a name like x_studio_company_id belongs to
    eighty models.
    """
    gone = MISSING_ACTION.search(str(exc))
    if gone and clear_action_buttons(gone.group(1)):
        return True
    match = IN_VIEWS.search(str(exc))
    if not match:
        return False
    # Odoo names the fields as model.field, and both halves matter. Taking the
    # names alone and removing every node called that, from every view of that
    # name, is what emptied the x_all_requests form: Odoo names a view of a
    # model that has nothing to do with the deletion - a refusal for
    # x_1_1_1_general_assets named the default form of x_e_o_s_gratuity - and
    # x_studio_company_id, x_name and x_studio_notes belong to eighty models
    # each. Sixty-eight deletions of three passes wore a live form down to its
    # title.
    #
    # So the pair is kept, and a node goes only when it is that field of that
    # model, decided by where the node sits.
    pairs = {(model_name, field_name)
             for model_name, field_name in PAIR.findall(match.group(1))}
    # A field on a model that stays is the ordinary case here: the incoming
    # links are dropped off models that are not going anywhere. What must never
    # happen is touching a field nobody is removing, so the test is membership
    # of what is being removed - which is what doomed is - and not the model.
    pairs = {pair for pair in pairs if pair[0] in going or pair in doomed}
    view_name = match.group(2).strip()
    if not pairs or not view_name:
        return False
    views = View.search([('name', '=', view_name)])
    changed = 0
    for view in views:
        if not view.model:
            continue
        try:
            tree = etree.fromstring((view.arch or '').encode())
        except Exception:
            continue
        nodes = []
        for model_name, name in pairs:
            for node in tree.xpath("//field[@name='%s'] | //label[@for='%s']"
                                   % (name, name)):
                owner = node_model(node, view.model)
                if owner == model_name:
                    nodes.append(node)
        if not nodes:
            continue
        for node in nodes:
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
        try:
            with cr.savepoint():
                view.arch = etree.tostring(tree, encoding='unicode')
            changed += len(nodes)
            print("  - node   %s node(s) off view %-6s %s"
                  % (len(nodes), view.id, view_name[:44]))
        except Exception:
            pass
    if changed:
        return True

    # Nothing to remove, and the view still refuses. Then it is broken for a
    # reason of its own and our field is only the name Odoo happened to be
    # holding when it looked. Studio's generated defaults are rebuilt from the
    # model when they go, so removing one costs a customisation nobody made on
    # purpose - but it is still somebody's screen, so it is asked for.
    if not DROP_BROKEN_VIEWS:
        return False
    for view in views:
        if not view.exists():
            continue
        try:
            with cr.savepoint():
                view._check_xml()
            continue                       # this one is fine; leave it alone
        except Exception:
            pass
        view_id, view_model = view.id, view.model or '-'
        if drop_view(view):
            print("  - view   %-6s %-24s removed: it does not validate on its own"
                  % (view_id, view_model))
            changed += 1
    return bool(changed)


class Refused(Exception):
    """A removal that could not be made, carrying the reason for it."""


def unlink_field(field, depth=0):
    """Remove a field, its nodes, and whatever Odoo says is standing on it.

    Studio computed fields lean on each other - a rate is computed from the
    salary, the overtime total from the hours - and Odoo refuses the one
    underneath while the one above exists. It also says which one, by name, in
    the refusal. So rather than work the graph out in advance, the refusal is
    read and the named field removed first.

    Everything that has to happen for the field to go - its nodes out of the
    views that show it, a node out of a view Odoo named, a field above it
    removed first - happens inside one savepoint with the removal itself. If the
    removal is refused in the end, all of it is rolled back and the screens are
    exactly as they were.

    That order is the whole point. The version before this stripped the nodes,
    committed them, and then tried the deletion. When the deletion was refused
    the nodes stayed gone, and x_all_requests - a model nobody was deleting -
    was left with a form holding a title and nothing else.
    """
    if not field.exists():
        return True, ''
    model_name, name = field.model, field.name
    try:
        with cr.savepoint():
            strip_from_views({(model_name, name)}, preview=False)
            reason = _unlink_field(field, depth)
            if reason:
                raise Refused(reason)
        return True, ''
    except Refused as exc:
        return False, str(exc)
    except Exception as exc:
        return False, why(exc)


def _unlink_field(field, depth=0):
    """The attempt itself. Runs inside the caller savepoint, and returns the
    reason it could not be done or an empty string."""
    if not field.exists():
        return ''
    try:
        with cr.savepoint():
            field.unlink()
        return ''
    except Exception as exc:
        if depth <= 6 and clear_named_views(exc):
            return _unlink_field(field, depth + 1)
        both = refused_pair(exc) if depth <= 6 else None
        if both:
            names = ' with '.join('%s.%s' % (f.model, f.name) for f in both)
            for one in both:
                strip_from_views({(one.model, one.name)}, preview=False)
            try:
                with cr.savepoint():
                    (field | both).unlink()
                print("  - pair   %s" % names)
                return ''
            except Exception as second:
                exc = second
        match = DEPENDS.search(str(exc))
        if not match or depth > 6:
            return why(exc)
        above = IrField.search([('model', '=', match.group(1)),
                                ('name', '=', match.group(2))], limit=1)
        if not above or above.state != 'manual' or above == field:
            # Removing the field standing on this one is the remedy, unless the
            # field standing on it is this one: then the two of them lean on
            # each other and only going together settles it, which is what
            # refused_pair above is for.
            return why(exc)
        strip_from_views({(above.model, above.name)}, preview=False)
        reason = _unlink_field(above, depth + 1)
        if reason:
            return reason
        print("  - above  %s.%s" % (match.group(1), match.group(2)))
        return _unlink_field(field, depth + 1)


def unlink_model(model_record, name, depth=0):
    """A model refuses for the same two reasons a field does, and answers to the
    same two remedies: clear the view it named, or remove the field standing on
    one of its own.

    Same rule as unlink_field: every view edit made on the way happens inside
    the savepoint the removal has to succeed in, or it does not stand."""
    if not model_record.exists():
        return True, ''
    try:
        with cr.savepoint():
            reason = _unlink_model(model_record, name, depth)
            if reason:
                raise Refused(reason)
        return True, ''
    except Refused as exc:
        return False, str(exc)
    except Exception as exc:
        return False, why(exc)


def _unlink_model(model_record, name, depth=0):
    if not model_record.exists():
        return ''
    try:
        with cr.savepoint():
            model_record.unlink()
        return ''
    except Exception as exc:
        if depth > 6:
            return why(exc)
        if clear_named_views(exc):
            return _unlink_model(model_record, name, depth + 1)
        both = refused_pair(exc)
        if both:
            names = ' with '.join('%s.%s' % (f.model, f.name) for f in both)
            for one in both:
                strip_from_views({(one.model, one.name)}, preview=False)
            try:
                with cr.savepoint():
                    both.unlink()
                print("  - pair   %s" % names)
                return _unlink_model(model_record, name, depth + 1)
            except Exception:
                pass
        match = DEPENDS.search(str(exc))
        if match:
            above = IrField.search([('model', '=', match.group(1)),
                                    ('name', '=', match.group(2))], limit=1)
            if above and above.state == 'manual':
                strip_from_views({(above.model, above.name)}, preview=False)
                reason = _unlink_field(above)
                if not reason:
                    print("  - above  %s.%s" % (match.group(1), match.group(2)))
                    return _unlink_model(model_record, name, depth + 1)
                return reason
        return why(exc)


def node_model(node, view_model):
    """Which model a <field> node in a view actually belongs to.

    A view of x_salary_batches shows x_studio_basic_salary, and that node is a
    field of x_to_pay: it sits inside an embedded list of them. A view of
    x_all_requests shows a node of the same name that is its own. The name
    cannot tell them apart, and both earlier attempts tried to make it -
    stripping everything with a matching name took three thousand nodes out of
    other people's forms, and stripping only unshared names then left the ones
    that really were ours and blocked the deletion.

    The position answers it. Start at the view's own model and walk down: every
    <field> ancestor that names a relation moves into that relation's model, so
    by the time you reach the node you know whose field it is.
    """
    chain = []
    parent = node.getparent()
    while parent is not None:
        chain.append(parent)
        parent = parent.getparent()
    chain.reverse()

    model = view_model
    for element in chain:
        if element.tag != 'field' or not element.get('name'):
            continue
        current = env.get(model)                                 # noqa: F821
        if current is None:
            return None
        field = current._fields.get(element.get('name'))
        if field is None:
            return None
        if field.relational:
            model = field.comodel_name
    return model


def strip_from_views(targets, preview):
    """Take the departing models' fields off the views that show them.

    Every node is asked whose field it is before it is touched. A node that
    belongs to a model that is staying is left where it is, whatever it is
    called.
    """
    removed, foreign = 0, {}
    wanted = {}
    for model_name, field_name in targets:
        wanted.setdefault(field_name, set()).add(model_name)
    for name in sorted(wanted):
        cr.execute("SELECT id FROM ir_ui_view WHERE arch_db::text LIKE %s",
                   ('%' + name + '%',))
        for (view_id,) in cr.fetchall():
            view = View.browse(view_id).exists()
            if not view or not view.model:
                continue
            try:
                tree = etree.fromstring((view.arch or '').encode())
            except Exception:
                continue
            nodes = tree.xpath("//field[@name='%s'] | //label[@for='%s']"
                               % (name, name))
            ours = []
            for node in nodes:
                owner = node_model(node, view.model)
                if owner in wanted[name]:
                    ours.append(node)
                elif owner:
                    foreign.setdefault(owner, set()).add(name)
            if not ours:
                continue
            if preview:
                print("      %s node(s) of %-42s in view %-6s (%s)"
                      % (len(ours), name, view.id, view.model))
                removed += len(ours)
                continue
            for node in ours:
                parent = node.getparent()
                if parent is not None:
                    parent.remove(node)
            try:
                with cr.savepoint():
                    view.arch = etree.tostring(tree, encoding='unicode')
                removed += len(ours)
            except Exception:
                pass
    if foreign and preview:
        print("\n      left alone, because the node belongs to a model that "
              "stays:")
        for model_name, kept in sorted(foreign.items()):
            print("      %-40s %s" % (model_name, ', '.join(sorted(kept)[:3])))
    # Never committed here. A stripped node is only kept when the deletion it
    # was in the way of goes through, and the caller's savepoint is what decides
    # that. Committing here is what left a live model with an emptied form: the
    # nodes went, the model refused, and nothing put them back.
    return removed


# What the stripper would touch, printed before it touches anything. The number
# is the check: a handful of nodes in the departing model's own forms is right,
# and anything in the thousands means the guard has failed again.
# Everything that is going, as (model, field) pairs: the departing models' own
# fields, the links into them from models that stay, and the readers those links
# feed. A node goes only when it is that field on that model - the question the
# name alone could never answer and the model alone could only half answer.
doomed = set()
for model_name in going:
    target = env.get(model_name)                                 # noqa: F821
    if target is not None:
        doomed |= {(model_name, n) for n in target._fields if n.startswith('x_')}
for field, _held in incoming:
    if field.state == 'manual':
        doomed.add((field.model, field.name))
for reader in IrField.search([('related', '!=', False), ('state', '=', 'manual')]):
    parts = (reader.related or '').split('.')
    if len(parts) < 2:
        continue
    if reader.model in going:
        doomed.add((reader.model, reader.name))
        continue
    current = env.get(reader.model)                              # noqa: F821
    for part in parts[:-1]:
        if current is None or part not in current._fields:
            break
        step = current._fields[part]
        if not step.relational:
            break
        if step.comodel_name in going:
            doomed.add((reader.model, reader.name))
            break
        current = env.get(step.comodel_name)                     # noqa: F821

# The upper bound, not the plan. A node is only ever removed in the same
# savepoint as the field it belongs to, and only when that field is really
# removed - so what actually goes is a subset of this, and if a removal is
# refused none of its nodes go at all.
print("\n  view nodes that would go, if every one of these fields goes:")
would = strip_from_views(doomed, preview=True)
print("  %s node(s)" % would)
if would > 200:
    raise SystemExit(
        "\nSTOPPED: %s is more than any one model's forms contain. Nothing was "
        "changed. Read the list above before going further." % would)




problems = []
if blocking:
    problems.append("%s coded field(s) still point at it" % len(blocking))
if not DROP_LINKS and [f for f, h in incoming if f.state == 'manual']:
    problems.append("%s Studio field(s) point at it - run with SSC_DROP_LINKS=1"
                    % len([f for f, h in incoming if f.state == 'manual']))
if not DROP_CODE and (naming or rules):
    problems.append("%s server action(s) and %s automation(s) name it - run with "
                    "SSC_DROP_CODE=1" % (len(naming), len(rules)))

if CONFIRM != MODEL:
    print("  Nothing has been changed.")
    print("  To delete, run again with SSC_CONFIRM=%s" % MODEL)
    if problems:
        print("\n  and settle these first:")
        for problem in problems:
            print("      - %s" % problem)
    cr.rollback()
    raise SystemExit()

if problems:
    print("  STOPPED:")
    for problem in problems:
        print("      - %s" % problem)
    cr.rollback()
    raise SystemExit("\nNothing was changed.")

# --- 6. do it -----------------------------------------------------------------

title("6. deleting")

# Each removal unblocks the next: a view cannot go while another inherits it, a
# child's many2one cannot go while the parent's one2many names it, and neither
# can go while a view still shows them. Three passes settles it; a fourth has
# never had anything left to do.
for attempt in (1, 2, 3):
    progress = 0

    # the code, first pass only
    if attempt == 1:
        for rule in rules:
            if not rule.exists():
                continue
            try:
                with cr.savepoint():
                    rule.unlink()
                print("  - rule   %s" % rule.id)
                progress += 1
            except Exception as exc:
                print("  ! rule   %s refused: %s"
                      % (rule.id, why(exc)))
        for action, label in [(a, '%s %s' % (a.id, (a.name or '')[:40]))
                              for a in naming]:
            if not action.exists():
                print("  - action %s already gone" % label)
                continue
            action_id = action.id
            try:
                with cr.savepoint():
                    action.unlink()
                print("  - action %s" % label)
                progress += 1
                clear_action_buttons(action_id)
            except Exception as exc:
                # A cron holding the action refuses the delete with a foreign
                # key on ir_cron, which says nothing about crons to anybody
                # reading it. The cron calls code naming a model that is going,
                # so it has nothing left to do either.
                cron = env['ir.cron'].sudo().search(                     # noqa: F821
                    [('ir_actions_server_id', '=', action_id)])
                if cron:
                    try:
                        with cr.savepoint():
                            cron.unlink()
                            action.unlink()
                        print("  - action %s  (with %s cron(s) that called it)"
                              % (label, len(cron)))
                        progress += 1
                        clear_action_buttons(action_id)
                        continue
                    except Exception:
                        pass
                print("  ! action %s  %s"
                      % (label, why(exc)))
        # The names are read here, before the first removal, and not off the
        # record inside the loop. Dropping one field takes others with it - a
        # one2many and the many2one it is the inverse of, res.users.x_studio_name
        # and res.partner.x_studio_name - and asking a deleted record what it was
        # called raises MissingError and takes the whole run down with it. The
        # comment saying this said it before the code did.
        pending = [(f, h, f.model, f.name)
                   for f, h in incoming if f.state == 'manual']
        for field, held, model_name, field_name in pending:
            label = '%s.%s' % (model_name, field_name)
            if not field.exists():
                print("  - field  %-52s already gone" % label)
                continue
            done, reason = unlink_field(field)
            if done:
                print("  - field  %-52s %s row(s) held" % (label, held))
                progress += 1
            else:
                print("  ! field  %-52s %s" % (label, reason))
        cr.commit()

    # Before anything: buttons calling actions that no longer exist. A view
    # holding one fails to validate, and every field deletion that touches that
    # view is then refused with a message about the field - which is never the
    # reason.
    orphaned = repair_orphan_action_buttons()
    if orphaned:
        progress += orphaned

    # The readers first. A related field is a path, and Odoo will not let a
    # field be removed while another field's path runs through it - which is
    # right, and which is why the incoming links refused: account.move.line has
    # an x_studio_employee reading x_studio_pay_slip.x_studio_for_employee, and
    # the pay slip link cannot go while that reader wants it.
    #
    # A reader whose path walks onto a model that is leaving has nothing to read
    # after today. It goes first, and it goes named.
    for reader in IrField.search([('related', '!=', False), ('state', '=', 'manual')]):
        if not reader.exists():
            continue
        parts = (reader.related or '').split('.')
        if len(parts) < 2:
            continue
        # A related field declared on a departing model goes with it, and has to
        # go first: Odoo will not remove a field another field's path runs
        # through, even when both are on the same model and both are leaving.
        current = env.get(reader.model)                          # noqa: F821
        touches = reader.model in going
        for part in parts[:-1]:
            if current is None or part not in current._fields:
                break
            step = current._fields[part]
            if not step.relational:
                break
            if step.comodel_name in going:
                touches = True
                break
            current = env.get(step.comodel_name)                 # noqa: F821
        if not touches:
            continue
        label = '%s.%s' % (reader.model, reader.name)
        done, reason = unlink_field(reader)
        if done:
            print("  - reader %-52s %s" % (label, '.'.join(parts)))
            progress += 1
        else:
            print("  ! reader %-52s %s" % (label, reason))
    cr.commit()

    # views of the departing models, children of an inherited view first
    views = View.search([('model', 'in', going)])
    for view in views.sorted(lambda v: -len(v.inherit_id)):
        if not view.exists():
            continue
        view_id, view_name = view.id, (view.name or '')[:44]
        if drop_view(view):
            print("  - view   %-6s %s" % (view_id, view_name))
            progress += 1
    cr.commit()

    # the parent's one2many, so a child's many2one stops being an inverse
    for name, field in list(Model._fields.items()):
        if field.type != 'one2many' or field.comodel_name not in children:
            continue
        record_field = IrField.search(
            [('model', '=', MODEL), ('name', '=', name)], limit=1)
        if not record_field:
            continue
        done, reason = unlink_field(record_field)
        if done:
            print("  - o2m    %s.%s" % (MODEL, name))
            progress += 1
        else:
            print("  ! o2m    %s.%s %s" % (MODEL, name, reason))
    cr.commit()

    for name in sorted(children):
        child = IrModel.search([('model', '=', name)], limit=1)
        if not child:
            continue
        done, reason = unlink_model(child, name)
        if done:
            print("  - model  %s" % name)
            progress += 1
        else:
            print("  ! model  %s %s" % (name, reason))
    cr.commit()

    left = IrModel.search([('model', '=', MODEL)], limit=1)
    if left:
        done, reason = unlink_model(left, MODEL)
        if done:
            print("  - model  %s" % MODEL)
            progress += 1
        else:
            print("  ! model  %s %s" % (MODEL, reason))
    cr.commit()

    if not IrModel.search_count([('model', '=', MODEL)]):
        break
    if not progress:
        print("\n  pass %s changed nothing - stopping rather than looping" % attempt)
        break
    print("  --- pass %s done, %s change(s); going round again" % (attempt, progress))


title("after")
print("  %s still a model: %s" % (MODEL, bool(IrModel.search_count([('model', '=', MODEL)]))))
print("  table still there: %s" % table_exists(Model._table))
print("""
  Restart, then open the payroll menus. A model deleted while something still
  referred to it does not fail here - it fails on the first screen that opens
  after.""")
