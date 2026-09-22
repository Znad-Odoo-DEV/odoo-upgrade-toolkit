"""The views the browser cannot open, the field that breaks each, and the way to drop it.

    cd ~/src/user
    # report:
    odoo-bin shell -d <database> --no-http < tools/drop_orphan_view_fields.py 2>&1 | grep -v " INFO "
    # write:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/drop_orphan_view_fields.py 2>&1 | grep -v " INFO "

WHY THIS EXISTS

x_site_payment_certifi was deleted on 2026-09-15 and took account.move's
x_studio_spc - the Many2one from an invoice to its certificate - with it. The
Studio view that put that field on the invoice form stayed, because deleting
a model does not visit the views that name its fields, and Odoo 19 checks a
view against its model only when the view is written. Nothing said a word
until somebody opened an invoice.

HOW IT LOOKS, WHICH IS THE PART THE FIRST VERSION GOT WRONG

The first version read each inherited view's own arch and judged every field
node against the model. That reported 117 views, 111 of them Odoo's own,
because in an inherited arch `<field name="team_id" position="after">` is an
ANCHOR - it names where to put things - and a node under it is not "inside
team_id's sub-view". It would have cut 14 live fields out of a Studio view on
hr.attendance.overtime.ruleset.

So this asks the question the browser asks: for every root view (no
inherit_id) of every model, it builds the combined arch the way get_view does
and validates every field node against the model it is rendered for -
descending into a one2many's inline sub-view with that field's comodel. Only
when THAT fails does it go looking for which inherited view carried the node,
by matching the node's serialised form. A root arch that passes is a screen
that opens, whatever the individual pieces look like.

WHAT IS WRITTEN

Only Studio views (module studio_customization) and only the orphan nodes,
removed from the arch in place. A view of our own naming a missing field is
reported and left alone: that is a defect in a module, and the module is where
it is fixed. A Studio view left with nothing but empty xpaths is archived
rather than deleted, so it can be read back.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

from lxml import etree

from odoo.tools.view_validation import get_expression_field_names

WIDTH = 110
APPLY = os.environ.get('SSC_APPLY') == '1'

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
View = env['ir.ui.view'].sudo()
Data = env['ir.model.data'].sudo()


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def module_of(view):
    data = Data.search([('model', '=', 'ir.ui.view'), ('res_id', '=', view.id)], limit=1)
    return data.module or '(no module - made in the database)'


def models_of(node, root_model):
    """(model, parent model) a node in a COMBINED arch is rendered for.

    In a combined arch there are no anchors left: a field ancestor with a
    sub-view is a real relational field, so the chain of field ancestors,
    root-first, walks the comodels. The parent model is the one an
    expression's `parent.x` reads - the record holding the one2many.
    """
    chain = []
    parent = node.getparent()
    while parent is not None:
        if parent.tag == 'field' and parent.get('name'):
            chain.append(parent.get('name'))
        parent = parent.getparent()
    model, above = root_model, None
    for holder in reversed(chain):
        field = env[model]._fields.get(holder) if model in env else None
        if field is None or not getattr(field, 'comodel_name', None):
            return None, None
        model, above = field.comodel_name, model
    return model, above


def field_model_of(node, root_model):
    return models_of(node, root_model)[0]


# The attributes whose value is a Python expression over the record's
# fields. A field named only there - invisible="x_studio_approved_mr" - breaks
# the view exactly as a missing name= does, and Odoo refuses to write the arch
# until it is gone: that is what stopped the first write of this tool.
EXPRESSION_ATTRIBUTES = ('invisible', 'readonly', 'required', 'column_invisible')


def names_in(expression):
    """The field names an expression reads - Odoo's own reading of it.

    A regex over the words found `get` in context.get(), `length` in
    len(...) and `allowed_company_ids` from the evaluation context, and
    called every one of them a missing field. get_expression_field_names is
    what the view validator itself uses: it parses the expression, keeps the
    root of each name, and drops context, parent, the builtins and the
    evaluation context's own names. A name it returns that the model lacks is
    exactly what the validator would refuse.
    """
    if not expression:
        return set()
    try:
        names = set(get_expression_field_names(expression))
    except (SyntaxError, ValueError):
        return set()
    # The lower-case literals the validator lets through; a bare "true" in
    # column_invisible is not a field of anything.
    return {n for n in names if n not in ('true', 'false', 'none')}


def broken_fields(root):
    """[(name, model, where)] the combined arch cannot render.

    ``where`` is 'name' when the node itself names the missing field, or the
    attribute whose expression does.
    """
    Model = env[root.model]
    try:
        combined = etree.fromstring(Model.get_view(root.id, root.type)['arch'])
    except Exception as error:                                       # noqa: BLE001
        return [('(get_view failed)', root.model, str(error)[:80])]
    bad = []
    for node in combined.iter():
        if not isinstance(node.tag, str):
            continue
        model, above = models_of(node, root.model)
        if model is None or model not in env:
            continue
        fields = env[model]._fields
        if node.tag == 'field' and node.get('name') and node.get('name') not in fields:
            bad.append((node.get('name'), model, 'name'))
        for attribute in EXPRESSION_ATTRIBUTES:
            for word in names_in(node.get(attribute)):
                if word.startswith('parent.'):
                    # The enclosing record's field, read from a sub-view.
                    # Only the first hop is a field of the parent model; the
                    # rest is whatever that field's record has.
                    hop = word.split('.')[1]
                    if above and above in env and hop not in env[above]._fields:
                        bad.append((word, above, attribute))
                    continue
                if word not in fields:
                    bad.append((word, model, attribute))
    return bad


def carrier_of(root, name, model):
    """The view - root or one of its inherited views - whose arch puts a field
    of that name where a node of that model is rendered. The root first,
    then every active inherited view in application order."""
    for view in root | root.inherit_children_ids.filtered('active').sorted('priority'):
        try:
            arch = etree.fromstring(view.arch_db or '<x/>')
        except etree.XMLSyntaxError:
            continue
        for node in arch.iter():
            if not isinstance(node.tag, str) or node.get('position'):
                # An anchor - a node with a position attribute - names where
                # to put things and never breaks a render.
                continue
            if node.tag == 'field' and node.get('name') == name:
                return view, node
            if any(name in names_in(node.get(a)) for a in EXPRESSION_ATTRIBUTES):
                return view, node
    return None, None


# --- every root view of every model ----------------------------------------
title("1. screens the browser cannot open, and the field that stops each")
roots = View.search([('active', '=', True), ('model', '!=', False),
                     ('inherit_id', '=', False)], order='model, id')
found = []          # (root, name, model, carrier view, carrier node)
seen = set()
for root in roots:
    if root.model not in env or root.type not in (
            'form', 'list', 'kanban', 'search', 'calendar', 'pivot', 'graph'):
        continue
    for name, model, where in broken_fields(root):
        carrier, node = carrier_of(root, name, model)
        key = (carrier.id if carrier else root.id, name, model)
        if key in seen:
            continue
        seen.add(key)
        found.append((root, name, model, carrier, node, where))

if not found:
    print("  none - every screen opens")
by_carrier = defaultdict(list)
for root, name, model, carrier, node, where in found:
    by_carrier[carrier or root].append((root, name, model, node, where))
studio, ours = [], []
for carrier, items in by_carrier.items():
    module = module_of(carrier)
    (studio if module == 'studio_customization' else ours).append((carrier, module, items))
    print("\n  [%s] %-48s model %-22s %s" % (carrier.id, (carrier.name or '?')[:48],
                                             carrier.model, module))
    for root, name, model, node, where in items:
        print("      %-32s on %-26s breaks %s [%s]   %s"
              % (name, model, root.type, root.id,
                 "named" if where == 'name' else "in %s=" % where))

# --- what would be done --------------------------------------------------------
title("2. what would be written")
print("  %s Studio view(s) to clean, %s of our own reported only" % (len(studio), len(ours)))
for carrier, _module, _items in ours:
    print("    !! %s [%s] - fix the module, not the database" % (carrier.name, carrier.id))

if not APPLY:
    env.cr.rollback()
    title("report only - nothing written. SSC_APPLY=1 to write.")
    raise SystemExit

cleaned = archived = 0
for carrier, _module, items in studio:
    arch = etree.fromstring(carrier.arch_db)
    names = {name for _root, name, _model, _node, _where in items}
    for node in list(arch.iter()):
        if not isinstance(node.tag, str) or node.get('position'):
            continue
        if node.tag == 'field' and node.get('name') in names:
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
            continue
        # An expression reading a field that is gone cannot be evaluated any
        # more, so it goes; the element stays and shows as it would with the
        # condition false.
        for attribute in EXPRESSION_ATTRIBUTES:
            if names & names_in(node.get(attribute)):
                del node.attrib[attribute]
    xpaths = arch.findall('.//xpath')
    if carrier.inherit_id and xpaths and all(len(x) == 0 for x in xpaths):
        carrier.active = False
        archived += 1
        continue
    carrier.arch_db = etree.tostring(arch, encoding='unicode')
    cleaned += 1
env.cr.commit()
title("APPLIED")
print("  %s view(s) cleaned, %s archived as empty shells" % (cleaned, archived))
print("  Run again: the report must come back empty for the models touched.")
