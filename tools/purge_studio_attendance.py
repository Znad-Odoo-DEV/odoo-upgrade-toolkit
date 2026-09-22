"""Remove the Studio customisations that sit on hr.attendance.

    odoo-bin shell -d <database> --no-http < tools/purge_studio_attendance.py

It is a DRY RUN by default - it prints what it would remove and changes nothing.
Once the list has been read and agreed, opt in for that one run:

    PURGE_ATTENDANCE_DELETE=1 odoo-bin shell -d <database> --no-http \
        < tools/purge_studio_attendance.py

The switch lives in the environment rather than in the file so that the copy on
the branch is never the armed one.

Scope: every manual (Studio) field on hr.attendance - x_studio_set_check_in,
x_studio_set_check_out and anything else Studio put there - together with what
references them: inherited views, saved filters, server actions and automations.

Odoo's own crons (_cron_auto_check_out, _cron_absence_detection) belong to the
hr_attendance module, so they are listed as KEPT and never removed: only rows
whose xmlid is missing or lives in studio_customization are candidates.

Order matters. Automations and server actions go first (they read the fields),
then the views are stripped of the field nodes, then the fields themselves - so
nothing is ever left pointing at a column that has already been dropped.
"""

import os

from lxml import etree

DELETE = os.environ.get('PURGE_ATTENDANCE_DELETE') == '1'
MODEL = 'hr.attendance'
STUDIO_MODULES = ('studio_customization',)


def owner_module(record):
    """Return the module owning a record, or '' when it has no xmlid."""
    data = env['ir.model.data'].search([
        ('model', '=', record._name), ('res_id', '=', record.id)], limit=1)
    return data.module or ''


def is_studio(record):
    """True for rows Studio created: no xmlid at all, or a studio one."""
    module = owner_module(record)
    return module == '' or module in STUDIO_MODULES


# --- the custom fields ------------------------------------------------------
fields = env['ir.model.fields'].search([
    ('model', '=', MODEL), ('state', '=', 'manual')])
field_names = fields.mapped('name')

print(f"=== {len(fields)} Studio field(s) on {MODEL}")
for f in fields:
    print(f"  FIELD  {f.name} ({f.ttype}) - {f.field_description}")

# --- automations ------------------------------------------------------------
model_row = env['ir.model']._get(MODEL)
automations = env['base.automation'].with_context(active_test=False).search([
    ('model_id', '=', model_row.id)])
print(f"\n=== {len(automations)} automation(s) on {MODEL}")
for a in automations:
    print(f"  AUTO   id={a.id} trigger={a.trigger} active={a.active}")

# --- server actions: Studio ones, plus any that mention a doomed field ------
doomed_actions = env['ir.actions.server'].browse()
kept_actions = env['ir.actions.server'].browse()
for action in env['ir.actions.server'].search([('model_id', '=', model_row.id)]):
    mentions = any(name in (action.code or '') for name in field_names)
    if is_studio(action) or mentions:
        doomed_actions |= action
        why = 'mentions a Studio field' if mentions else 'created by Studio'
        print(f"  ACTION id={action.id} {action.name} - {why}")
    else:
        kept_actions |= action

# --- crons: only the Studio ones ------------------------------------------
doomed_crons = env['ir.cron'].with_context(active_test=False).browse()
for cron in env['ir.cron'].with_context(active_test=False).search(
        [('model_id', '=', model_row.id)]):
    if is_studio(cron):
        doomed_crons |= cron
        print(f"  CRON   id={cron.id} {cron.cron_name} - created by Studio")
    else:
        print(f"  KEPT   cron id={cron.id} {cron.cron_name} "
              f"(owned by {owner_module(cron)})")

# --- views and saved filters that name a doomed field ----------------------
views = env['ir.ui.view'].with_context(active_test=False).browse()
for name in field_names:
    views |= env['ir.ui.view'].with_context(active_test=False).search(
        [('arch_db', 'like', name)])
print(f"\n=== {len(views)} view(s) reference a Studio field")
for v in views:
    print(f"  VIEW   id={v.id} {v.name} ({v.type}) module={owner_module(v) or '-'}")

filters = env['ir.filters'].browse()
for name in field_names:
    filters |= env['ir.filters'].search(['|', ('domain', 'like', name),
                                         ('context', 'like', name)])
for f in filters:
    print(f"  FILTER id={f.id} {f.name}")

if not DELETE:
    print("\n=== DRY RUN - nothing removed. "
          "Re-run with PURGE_ATTENDANCE_DELETE=1 to apply.")
else:
    # Readers first, so nothing evaluates a field mid-removal.
    for group in (automations, doomed_actions, doomed_crons, filters):
        for rec in group:
            try:
                with env.cr.savepoint():
                    rec.unlink()
                print(f"  removed {rec._name} id={rec.id}")
            except Exception as exc:
                print(f"  !! could not remove {rec._name} id={rec.id}: "
                      f"{str(exc).splitlines()[0][:120]}")

    # Strip the field nodes out of every view that names one. A view left with
    # no children after the strip had no other purpose, so it goes as well.
    for view in views.exists():
        try:
            with env.cr.savepoint():
                tree = etree.fromstring(view.arch_db.encode())
                dropped = 0
                for node in tree.xpath('//*[@name]'):
                    if node.get('name') in field_names:
                        node.getparent().remove(node)
                        dropped += 1
                if len(tree) == 0:
                    view.unlink()
                    print(f"  removed empty view id={view.id}")
                elif dropped:
                    view.arch_db = etree.tostring(tree, encoding='unicode')
                    print(f"  stripped {dropped} node(s) from view id={view.id}")
        except Exception as exc:
            print(f"  !! could not clean view id={view.id}: "
                  f"{str(exc).splitlines()[0][:120]}")

    # The columns last: by now nothing reads them.
    for field in fields.exists():
        try:
            with env.cr.savepoint():
                name = field.name
                field.unlink()
                print(f"  removed field {name}")
        except Exception as exc:
            print(f"  !! could not remove field {field.name}: "
                  f"{str(exc).splitlines()[0][:120]}")

    env.cr.commit()
    print("=== removed and committed")
