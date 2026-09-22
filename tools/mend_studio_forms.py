"""Mend a Studio form whose fields went, when Odoo will not name them one by one.

    SSC_VIEWS=7861,2525 odoo-bin shell --no-http --shell-interface=python < tools/mend_studio_forms.py
    APPLY=1 to write. Without it: report only.

repair_views_missing_fields.py asks Odoo which field is missing and removes
that; it stops when the next error is not a missing field. Here the arch is
read instead: every display node (no position attribute) whose name is not a
field of the view's model is removed, a domain that names a field the comodel
no longer has is emptied, a button that calls a method its model does not
have is removed (the v18 default form carried an action_snooze button on the
activity list that Odoo 19's mail.activity no longer answers to), and the
base view is validated once at the end. Written only if it validates; the
full error is printed otherwise.
"""
import os
import re
from lxml import etree

APPLY = os.environ.get('APPLY') == '1'
VIEW_IDS = [int(x) for x in (os.environ.get('SSC_VIEWS') or '').replace(' ', '').split(',') if x]
View = env['ir.ui.view'].sudo().with_context(active_test=False, lang='en_US')  # noqa: F821


def arch_of(view):
    return view.arch_db.get('en_US') if isinstance(view.arch_db, dict) else view.arch


def base_of(view):
    while view.inherit_id:
        view = view.inherit_id
    return view


def model_at(node, model):
    """The model a node sits on: the view's, narrowed by every embedding <field>."""
    chain = [anc for anc in node.iterancestors() if anc.tag == 'field' and not anc.get('position')]
    for field_node in reversed(chain):
        field = model._fields.get(field_node.get('name'))
        if field is None or not field.comodel_name:
            return None
        model = env[field.comodel_name]                          # noqa: F821
    return model


def check(view):
    try:
        with env.cr.savepoint():                                 # noqa: F821
            base_of(view)._check_xml()
        return None
    except Exception as exc:
        return ' '.join(str(exc).split())


for view in View.browse(VIEW_IDS):
    model = env[view.model]                                      # noqa: F821
    tree = etree.fromstring(arch_of(view).encode())
    removed, emptied = [], []
    # a node inside an embedded subview belongs to the comodel of the field
    # that embeds it - the v18 default form listed partners with a "mobile"
    # column that res.partner no longer has in 19
    for node in list(tree.iter('field')):
        if node.get('position'):
            continue
        owner = model_at(node, model)
        if owner is None:
            continue
        name = node.get('name')
        if name not in owner._fields:
            removed.append('%s (on %s)' % (name, owner._name) if owner is not model else name)
            node.getparent().remove(node)
            continue
        field = owner._fields[name]
        domain = node.get('domain') or ''
        if domain and field.comodel_name:
            comodel = env[field.comodel_name]                    # noqa: F821
            names = set(re.findall(r'["\']([a-z_0-9.]+)["\']\s*,', domain))
            dead = [n for n in names if n.split('.')[0] not in comodel._fields]
            if dead:
                emptied.append((name, domain, dead))
                node.set('domain', '[]')
    dead_buttons = []
    for node in list(tree.iter('button')):
        if node.get('position') or node.get('type') not in (None, 'object'):
            continue
        name = node.get('name') or ''
        if not name or name.startswith('%('):
            continue
        owner = model_at(node, model)
        if owner is not None and not hasattr(owner, name):
            dead_buttons.append((name, owner._name))
            node.getparent().remove(node)
    print("\nview %s  %s  %s" % (view.id, view.model, (view.name or '')[:50]))
    print("  before:", (check(view) or 'valid')[-300:])
    for n in removed:
        print("  drop node      %s" % n)
    for name, domain, dead in emptied:
        print("  empty domain   %s  was %s  (dead: %s)" % (name, domain[:80], ', '.join(dead)))
    for name, owner in dead_buttons:
        print("  drop button    %s  (no such method on %s)" % (name, owner))
    if not removed and not emptied and not dead_buttons:
        print("  nothing found to change in this view's own arch")
        continue
    new_arch = etree.tostring(tree, encoding='unicode')
    if not APPLY:
        print("  DRY RUN - not written")
        continue
    try:
        with env.cr.savepoint():                                 # noqa: F821
            view.write({'arch_db': new_arch})
            base_of(view)._check_xml()
        env.cr.commit()                                          # noqa: F821
        print("  WRITTEN and validated, committed")
    except Exception as exc:
        print("  REFUSED, rolled back: %s" % ' '.join(str(exc).split())[-500:])
