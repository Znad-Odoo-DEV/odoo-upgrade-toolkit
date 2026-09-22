"""Drop the fourteen money readers and make them again, monetary this time.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/rebuild_employee_money_readers.py

Odoo will not change the type of a field that exists - "drop it and create it
again" is the message, and it means it - and it will not drop a field a view
still shows. So the field has to come out of its views, be dropped, be made
again as monetary pointing at ssc.employee, and go back into those views in the
place it came from.

Nothing is lost by dropping them. They are not stored, they hold no column, and
Odoo took them off their models the moment the repoint broke the path. What is
lost by doing it carelessly is the layout: a field put back at the end of a form
is not where anybody expects to read a salary.

So the position is recorded before the node is removed - the parent's path
through the tree and the index among its siblings - and used to put it back.

All of them together, or none. The views holding these readers are broken by
nothing but them (repair_views_missing_fields leaves the money nodes in place
for this), and ir.ui.view.write validates on the way in - so a view holding
four missing readers will not accept the removal of one. The nodes go out by
SQL, every touched view is validated once they are all out, and only then are
the fields dropped and made again; one refusal rolls the whole step back.

It runs in two passes when it has to. A manual field created here is not always
live in the same transaction, and a view naming a field the registry has not
heard of will not save. When that happens the plan is written to a config
parameter and the script says to restart and run it again; the second pass reads
the plan and only puts the nodes back.
"""
import json
import os

from lxml import etree

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

PLAN_KEY = 'ssc.employee_migration.money_reader_views'

# the last step of the broken path -> the monetary field on hr.employee (hr.version behind it)
MONEY = {
    'x_studio_basic_salary': 'wage',
    'x_studio_house_allowance': 'l10n_ae_housing_allowance',
    'x_studio_other_allowance': 'l10n_ae_other_allowances',
    'x_studio_transportation_allowance': 'l10n_ae_transportation_allowance',
    'x_studio_totalgross_salary': 'l10n_ae_total_salary',
}

# Models on their way out. Rebuilding a field on a model that is about to be
# deleted is work done twice and risk taken once: the surgery below moves nodes
# around in live views, and there is no reason to do that to a form nobody will
# open again.
GOING = {'x_to_pay'}

cr = env.cr                                                      # noqa: F821
param = env['ir.config_parameter'].sudo()                        # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def lands_on_employee(model_name, parts):
    current = env.get(model_name)                                # noqa: F821
    if current is None or len(parts) < 2:
        return False
    for part in parts[:-1]:
        if part not in current._fields:
            return False
        field = current._fields[part]
        if not field.relational:
            return False
        current = env.get(field.comodel_name)                    # noqa: F821
        if current is None:
            return False
    return current._name == 'hr.employee'


def views_mentioning(name):
    """Every view Odoo would look at, found the way Odoo finds them.

    ir.model.fields.unlink searches arch_db for the name across every view,
    whatever model it is of, and then asks each one to validate itself with the
    field taken out of the registry. So a field node in somebody else's form -
    a one2many list embedded in another model - counts, and so does a label, and
    so does a name inside an invisible= expression.

    Searching only the field's own model, which is what the first attempt did,
    finds none of those and reports zero while Odoo reports fourteen.
    """
    cr.execute("SELECT id FROM ir_ui_view WHERE arch_db::text LIKE %s",
               ('%' + name + '%',))
    found, awkward = [], []
    for (view_id,) in cr.fetchall():
        view = View.browse(view_id).exists()
        if not view:
            continue
        arch = view.arch or ''
        try:
            tree = etree.fromstring(arch.encode())
        except Exception:
            continue
        placements = []
        for node in tree.xpath("//field[@name='%s'] | //label[@for='%s']" % (name, name)):
            parent = node.getparent()
            if parent is None:
                continue
            placements.append({
                'tag': node.tag,
                'parent': tree.getroottree().getpath(parent),
                'index': list(parent).index(node),
                'attrib': dict(node.attrib),
            })
        # A name inside an expression - invisible, readonly, a domain - cannot be
        # taken out and put back; removing it would change what the view does.
        elsewhere = [
            '%s=%s' % (key, value[:40])
            for element in tree.iter()
            for key, value in element.attrib.items()
            if name in value and not (element.tag in ('field', 'label')
                                      and key in ('name', 'for'))
        ]
        if placements or elsewhere:
            found.append((view, placements, elsewhere))
    return found


# --- 1. the plan --------------------------------------------------------------

title("1. what will be rebuilt")

resume = json.loads(param.get_param(PLAN_KEY) or '[]')
if resume:
    print("  a plan from an earlier run is waiting: %s field(s) to put back into"
          " their views" % len(resume))
else:
    work = []
    for field in IrField.search([('related', '!=', False), ('ttype', '=', 'float')]):
        parts = (field.related or '').split('.')
        if len(parts) < 2 or parts[-1] not in MONEY:
            continue
        if field.model in GOING:
            continue
        if not lands_on_employee(field.model, parts):
            continue
        new_related = '.'.join(parts[:-1] + [MONEY[parts[-1]]])
        placements = views_mentioning(field.name)
        work.append((field, new_related, placements))

    stuck = []
    for field, new_related, placements in sorted(work, key=lambda w: (w[0].model, w[0].name)):
        nodes = sum(len(p) for _v, p, _e in placements)
        expressions = [(v, e) for v, _p, e in placements if e]
        print("  %-24s %-30s %s node(s) in %s view(s)"
              % (field.model, field.name, nodes, len(placements)))
        print("      -> %s" % new_related)
        for view, elsewhere in expressions:
            stuck.append((field, view, elsewhere))
            print("      ! view %-6s names it inside an expression: %s"
                  % (view.id, ', '.join(elsewhere[:2])))
    if stuck:
        print("\n  %s view(s) use the name in an expression. Those are left "
              "alone:" % len(stuck))
        print("  a name inside invisible= or a domain cannot be lifted out and put")
        print("  back, and removing it would change what the view does.")
    print("\n  %s field(s)" % len(work))

    if not work:
        print("  nothing to do")
        raise SystemExit()

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing changed. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 2. out of the views, dropped, made again --------------------------------

def arch_of(view):
    cr.execute("SELECT arch_db->>'en_US', arch_db FROM ir_ui_view WHERE id = %s", (view.id,))
    text, raw = cr.fetchone()
    if text is None:
        text = raw if isinstance(raw, str) else json.dumps(raw)
    return text


def set_arch(view, text):
    """Write arch_db without ir.ui.view.write, which validates on the way in.

    The views holding these readers are broken by nothing but them -
    repair_views_missing_fields left the money nodes in place on purpose - so
    a view with four missing readers does not validate with three, and lifting
    them one at a time through the ORM was refused five times out of five."""
    cr.execute("""UPDATE ir_ui_view
                     SET arch_db = jsonb_set(COALESCE(arch_db, '{}'::jsonb), '{en_US}', to_jsonb(%s::text))
                   WHERE id = %s""", (text, view.id))
    view.invalidate_recordset(['arch_db', 'arch'])


def failure(view):
    """None when the combined view validates; the flattened message otherwise."""
    try:
        with cr.savepoint():
            view._check_xml()
        return None
    except Exception as exc:                                    # noqa: BLE001
        return " ".join(str(exc).split())


class Refused(Exception):
    pass


if not resume:
    title("2. rebuilding")

    # All of them together, or none. Every node goes out first, by SQL; every
    # touched view is then asked to validate - if one does not, it is broken by
    # something other than a money reader and nothing here is right to change;
    # only then are the fields dropped and made again.
    plan, touched = [], {}
    try:
        with cr.savepoint():
            for field, new_related, placements in work:
                plan.append({
                    'model': field.model,
                    'name': field.name,
                    'label': field.field_description,
                    'related': new_related,
                    'help': field.help or False,
                    'views': [{'view': view.id, 'places': places}
                              for view, places, _elsewhere in placements],
                })
                for view, places, _elsewhere in placements:
                    if not places:
                        continue
                    tree = etree.fromstring(arch_of(view).encode())
                    for node in tree.xpath("//field[@name='%s'] | //label[@for='%s']"
                                           % (field.name, field.name)):
                        node.getparent().remove(node)
                    set_arch(view, etree.tostring(tree, encoding='unicode'))
                    touched[view.id] = view
            print("  %s node(s) lifted out of %s view(s)"
                  % (sum(len(p) for _f, _r, pl in work for _v, p, _e in pl), len(touched)))

            still_broken = []
            for view in touched.values():
                message = failure(view)
                if message:
                    still_broken.append((view.id, message))
            if still_broken:
                raise Refused('validating the views with every money node out',
                              '; '.join('view %s: %s' % (view_id, message[:400])
                                        for view_id, message in still_broken))

            for spec, (field, new_related, _placements) in zip(plan, work):
                step = 'unlinking %s.%s' % (spec['model'], spec['name'])
                try:
                    field.unlink()
                    step = 'creating %s.%s' % (spec['model'], spec['name'])
                    model_record = IrModel.search([('model', '=', spec['model'])], limit=1)
                    IrField.create({
                        'model_id': model_record.id,
                        'model': spec['model'],
                        'name': spec['name'],
                        'field_description': spec['label'],
                        'ttype': 'monetary',
                        'related': new_related,
                        'readonly': True,
                        'state': 'manual',
                    })
                except Exception as exc:                        # noqa: BLE001
                    raise Refused(step, " ".join(str(exc).split())[:700])
                print("  > %-24s %-30s monetary" % (spec['model'], spec['name']))
    except Refused as refused:
        cr.rollback()
        step, why = refused.args
        print()
        print("  refused while %s - nothing changed:" % step)
        print("      %s" % why)
        raise SystemExit()

    cr.commit()
    print()
    print("  %s rebuilt" % len(plan))
    param.set_param(PLAN_KEY, json.dumps(plan))
    cr.commit()
    resume = plan


# --- 3. back into the views ---------------------------------------------------

title("3. putting them back where they were")

# A manual field is not always live in the transaction that made it, and a view
# naming a field the registry has not heard of will not save.
not_live = [spec for spec in resume
            if env.get(spec['model']) is None                      # noqa: F821
            or spec['name'] not in env[spec['model']]._fields]     # noqa: F821
if not_live:
    print("  %s field(s) are not live in this registry yet." % len(not_live))
    print("  The plan is saved. Run:")
    print("      odoosh-restart http")
    print("      SSC_WRITE=1 odoo-bin shell --no-http < %s" % __file__.split('/')[-1]
          if '__file__' in dir() else
          "      SSC_WRITE=1 odoo-bin shell --no-http < tools/rebuild_employee_money_readers.py")
    raise SystemExit()

restored, failed = 0, []
for spec in resume:
    for entry in spec['views']:
        view = View.browse(entry['view']).exists()
        if not view:
            continue
        try:
            with cr.savepoint():
                tree = etree.fromstring((view.arch or '').encode())
                root = tree.getroottree()
                for place in sorted(entry['places'], key=lambda p: p['index']):
                    parents = root.xpath(place['parent'])
                    if not parents:
                        failed.append((spec['model'], spec['name'], view.id,
                                       'parent %s is gone' % place['parent']))
                        continue
                    node = etree.Element(place.get('tag') or 'field')
                    for key, value in place['attrib'].items():
                        node.set(key, value)
                    parents[0].insert(place['index'], node)
                    restored += 1
                view.arch = etree.tostring(tree, encoding='unicode')
        except Exception as exc:
            failed.append((spec['model'], spec['name'], view.id,
                           str(exc).strip().splitlines()[0]))
cr.commit()

print("  %s node(s) put back" % restored)
if failed:
    print("  %s could not be:" % len(failed))
    for model, name, view_id, why in failed:
        print("      %-22s %-28s view %-6s %s" % (model, name, view_id, why))
else:
    param.set_param(PLAN_KEY, '')
    cr.commit()

title("summary")
print("""  Restart, then open a To Pay and an End of Service. These have shown nothing
  since the repoint - they were off their models entirely - so whatever appears
  now is the first figure they have carried in either direction.""")
