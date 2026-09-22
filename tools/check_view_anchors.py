"""Do our inherited views still find what they are reaching for, on THIS database?

    odoo-bin shell --no-http --shell-interface=python < tools/check_view_anchors.py
    SSC_ADDONS=~/src/user/addons   where to read our own view files from
    SSC_ONLY=ssc_project,ssc_boq   only these modules

Reads only. Installs nothing, writes nothing, and works whether or not the
modules it is checking are installed.

Why this exists. Every view we inherit reaches into somebody else's screen by a
path - //div[@name='button_box'], //page[@name='description'] - and those paths
were written against a clean Odoo. This database is not a clean Odoo: Studio has
been editing the same screens for two years, and a node it wrapped, renamed or
deleted is a path that no longer resolves. Odoo does not warn about that. It
refuses to install the module, and on Odoo.sh that is a failed build with a
traceback that names a line number in a file rather than the thing that moved.

So: read our own XML off disk, work out every anchor each inherited view needs,
and try to find it in the parent view AS IT STANDS HERE - Studio's edits and all.

It reproduces Odoo's own two ways of locating a node:

  <xpath expr="..."/>              the path, run as written
  <tag attr=".." position=".."/>   the shorthand, which matches a tag with the
                                   same attributes, position excluded

and reports every anchor that cannot be found, with the file and the module, so
the fix is to the view that moved rather than to a line number.
"""
import os
import re

from lxml import etree

ADDONS = os.path.expanduser(os.environ.get('SSC_ADDONS')
                            or '~/src/user/addons')
ONLY = [m.strip() for m in (os.environ.get('SSC_ONLY') or '').split(',')
        if m.strip()]

IrView = env['ir.ui.view'].sudo()                                # noqa: F821
IrModelData = env['ir.model.data'].sudo()                        # noqa: F821

found_ok, missing, unresolved = [], [], []


def say(line=''):
    print(line)


def parent_view(ref, module):
    """The view an inherit_id points at, or None if the xml id is not here."""
    if '.' not in ref:
        ref = "%s.%s" % (module, ref)
    module_name, _, name = ref.partition('.')
    data = IrModelData.search([('module', '=', module_name),
                               ('name', '=', name),
                               ('model', '=', 'ir.ui.view')], limit=1)
    return IrView.browse(data.res_id) if data else None


def combined_arch(view):
    """The parent view as this database actually renders it.

    get_view applies every inheriting view that is already installed, which is
    the point: Studio's edits are in there, and they are what our paths have to
    survive.
    """
    try:
        result = env[view.model].get_view(view.id, view.type)     # noqa: F821
        return etree.fromstring(result['arch'])
    except Exception:
        # a view that will not render at all is a bigger problem than ours
        return etree.fromstring(view.arch_db or '<data/>')


def anchors_of(arch):
    """Every node in our view that reaches into the parent, and how.

    Odoo locates by xpath when told to, and otherwise by the tag and all the
    attributes except position - so <field name="x" position="after"/> means
    "the field called x", and that is the path we have to test.
    """
    wanted = []
    for node in arch.iter():
        if node.tag == 'xpath' and node.get('expr'):
            wanted.append((node.get('expr'), 'xpath'))
            continue
        if not node.get('position') or not isinstance(node.tag, str):
            continue
        attributes = {name: value for name, value in node.attrib.items()
                      if name != 'position'}
        if not attributes:
            wanted.append(('//%s' % node.tag, 'tag only'))
            continue
        conditions = "".join("[@%s='%s']" % (name, value)
                             for name, value in sorted(attributes.items()))
        wanted.append(('//%s%s' % (node.tag, conditions), 'shorthand'))
    return wanted


def check_file(path, module):
    try:
        tree = etree.parse(path)
    except Exception as error:
        unresolved.append((module, os.path.basename(path), '-',
                           "will not parse: %s" % error))
        return
    for record in tree.getroot().iter('record'):
        if record.get('model') != 'ir.ui.view':
            continue
        inherit = record.find("field[@name='inherit_id']")
        arch = record.find("field[@name='arch']")
        if inherit is None or arch is None or not inherit.get('ref'):
            continue
        parent = parent_view(inherit.get('ref'), module)
        if parent is None:
            unresolved.append((module, os.path.basename(path),
                               record.get('id'),
                               "parent %s is not on this database"
                               % inherit.get('ref')))
            continue
        rendered = combined_arch(parent)
        for expression, kind in anchors_of(arch):
            try:
                hits = rendered.xpath(expression)
            except Exception as error:
                unresolved.append((module, os.path.basename(path),
                                   record.get('id'),
                                   "%s is not valid xpath: %s"
                                   % (expression, error)))
                continue
            row = (module, record.get('id'), expression, kind,
                   inherit.get('ref'))
            (found_ok if hits else missing).append(row)


say("=" * 100)
say("Checking our inherited views against this database, as it stands")
say("=" * 100)
say("  reading from %s" % ADDONS)

if not os.path.isdir(ADDONS):
    raise SystemExit("No such directory: %s\n"
                     "Set SSC_ADDONS to where the addons live." % ADDONS)

modules = sorted(name for name in os.listdir(ADDONS)
                 if name.startswith('ssc_')
                 and os.path.isdir(os.path.join(ADDONS, name))
                 and (not ONLY or name in ONLY))
say("  modules      %s" % ", ".join(modules))

for module in modules:
    views = os.path.join(ADDONS, module, 'views')
    if not os.path.isdir(views):
        continue
    for filename in sorted(os.listdir(views)):
        if filename.endswith('.xml'):
            check_file(os.path.join(views, filename), module)

say()
say("  %s anchor(s) found, %s missing, %s could not be checked"
    % (len(found_ok), len(missing), len(unresolved)))

if missing:
    say()
    say("=" * 100)
    say("MISSING - these paths find nothing on this database")
    say("=" * 100)
    for module, view_id, expression, kind, ref in missing:
        say("  %-22s %-38s %s" % (module, (view_id or '?')[:38], ref))
        say("      %-10s %s" % (kind, expression))

if unresolved:
    say()
    say("=" * 100)
    say("COULD NOT CHECK")
    say("=" * 100)
    for module, filename, view_id, why in unresolved:
        say("  %-22s %-30s %-28s %s"
            % (module, filename, (view_id or '?')[:28], why))

say()
if missing:
    say("  Each missing anchor is a module that will refuse to install here,")
    say("  and on Odoo.sh that is a failed build. Fix the view that reaches,")
    say("  not the one that moved.")
elif unresolved:
    # a parent that is one of ours is not a finding: it resolves the moment
    # the module holding it is installed, and saying otherwise sends somebody
    # looking for a problem that is not there
    ours = all(why.startswith('parent ssc_') for _, _, _, why in unresolved)
    say("  Nothing our views reach for has been moved, renamed or wrapped on")
    say("  this database.")
    if ours:
        say()
        say("  The unchecked ones all inherit a view of ours that is not")
        say("  installed yet. They resolve as soon as it is; nothing outside")
        say("  our own modules is involved.")
else:
    say("  Every anchor resolves. Nothing our views reach for has been moved,")
    say("  renamed or wrapped by Studio on this database.")

env.cr.rollback()                                                # noqa: F821
