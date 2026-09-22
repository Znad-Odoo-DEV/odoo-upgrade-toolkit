"""Three live automations still read the Studio project models that are going.

    SSC_WRITE=1 odoo-bin shell --no-http --shell-interface=python < tools/retire_project_studio_readers.py

The Studio requests and store applications are still in daily use, and three
of their automations reach into models the Progress and Planning round is
deleting. Delete first and every material request and every stock consumption
stops with a KeyError in front of whoever pressed the button. So:

    2324  x_all_requests, on create/write of a material request
          reads x_items_needed for the project quantity and the sector quantity
          of each material. The block is removed; the two figures stay at
          zero, which is what they were for 97 per cent of lines - Studio's own
          mirror columns copied a value only when it was not zero, and of 5,189
          lines 142 ever got a project quantity (docs/requests_study_findings).
          Stock, previous requests and the balance are untouched.

    2827  x_all_requests, on create/write
          copies two consultant e-mails from x_new_projects onto the request.
          x_new_projects holds six rows and is going; the native project carries
          a consultant partner (ssc_consultant_id, ssc_project). The action now
          reads that partner's e-mail and clears the second address. Where the
          native project has no consultant yet, the request gets no address,
          exactly as it did for a project x_new_projects did not list.

    2362  x_transaction 'Set true', the store's receive/consume/stock/transfer
          on a 'Consumed' transaction it also added the quantity onto
          x_consumed_materials, per material and per sector. That block is
          removed; the store, the daily report and the sector stay as they are.

Text rewrites, deliberately narrow: each block is matched line by line with
whitespace free, and the action is left alone if the block is not found
exactly once. Dry run prints the diff of every change.
"""
import difflib
import os
import re

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

cr = env.cr                                                      # noqa: F821
Server = env['ir.actions.server'].sudo()                         # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def block_pattern(lines):
    """A regex matching these source lines in order, whatever the indentation.

    Blank lines between them are allowed: production's 2324 has one between
    the search and the "if proj_qty", and the copy read on test_2 did not.
    """
    return re.compile(r'\n[ \t]*' + r'\s*\n[ \t]*'.join(re.escape(l.strip()) for l in lines) + r'[ \t]*\n',
                      re.MULTILINE)


ITEMS_NEEDED_BLOCK = """
            proj_qty = env['x_items_needed'].search([
                ('x_studio_project', '=', record.x_studio_which_project_.id),
                ('x_studio_item', '=', materials.x_studio_material_code_1.id)
            ], limit=1)
            if proj_qty:
                proj = proj_qty.x_studio_quantity or 0
                if record.x_studio_which_sector:
                    sector_id = record.x_studio_which_sector.id
                    for section in proj_qty.x_studio_sector_1:
                        if section.x_studio_sector.id == sector_id:
                            sect = section.x_studio_quantity or 0
                            break
""".strip('\n').splitlines()

CONSUMED_BLOCK = """
    con_check = env['x_consumed_materials'].search([('x_studio_project', '=', record.x_studio_project.id)], limit=1)
    if con_check:
        for line in con_check.x_studio_materials_details_1:
            if str(line.x_name).strip() == str(record.x_studio_item_1.name).strip():
                old_qty = line.x_studio_quantity_consumed or 0.0
                new_qty = record.x_studio_quantity or 0.0
                total = old_qty + new_qty
                line.write({'x_studio_quantity_consumed': total})
        sector_name = record.x_studio_sector.x_name
        matching_sector = con_check.x_studio_per_sector.filtered(lambda s: str(s.x_name).strip() == sector_name)
        if matching_sector:
            existing_sector = matching_sector[0]
            for line in existing_sector.x_studio_sect_qty:
                if str(line.x_name).strip() == str(record.x_studio_item_1.name).strip():
                    old_qty = line.x_studio_quantity_consumed or 0.0
                    new_qty = record.x_studio_quantity or 0.0
                    total = old_qty + new_qty
                    line.write({'x_studio_quantity_consumed': total})
""".strip('\n').splitlines()

# The native project carries the two addresses themselves (ssc_requests puts
# ssc_consultant_email / ssc_consultant_re_email on project.project, and the
# certificate repair filled them from the 95 Studio certificates that had
# them), with the consultant partner's e-mail as the fallback. No attribute
# starting with an underscore: safe_eval refuses those inside a server action,
# so the guard is done here, once, by checking what the link points at.
CONSULTANT_CODE = """\
if record.x_studio_which_project_:
    project = record.x_studio_which_project_
    email = project.ssc_consultant_email
    if not email and project.ssc_consultant_id:
        email = project.ssc_consultant_id.email
    record.write({'x_studio_consultant_email': email or False,
                  'x_studio_consultant_re_email': project.ssc_consultant_re_email or False})
"""


def consultant_code(code):
    field = env['x_all_requests']._fields.get('x_studio_which_project_')  # noqa: F821
    target = field.comodel_name if field else None
    if target != 'project.project':
        raise ValueError("2827: x_studio_which_project_ points at %s, not project.project" % target)
    Project = env['project.project']                                    # noqa: F821
    for name in ('ssc_consultant_email', 'ssc_consultant_re_email', 'ssc_consultant_id'):
        if name not in Project._fields:
            raise ValueError("2827: project.project has no %s here" % name)
    return CONSULTANT_CODE


def remove_block(code, lines, label):
    pattern = block_pattern(lines)
    hits = pattern.findall(code)
    if len(hits) != 1:
        raise ValueError("%s: block found %s time(s), expected exactly once" % (label, len(hits)))
    return pattern.sub('\n', code, count=1)


plans, refused = [], []
for action_id, label, make in (
        (2324, 'material request: drop the x_items_needed lookup',
         lambda code: remove_block(code, ITEMS_NEEDED_BLOCK, '2324')),
        (2362, "store 'Set true': drop the x_consumed_materials block",
         lambda code: remove_block(code, CONSUMED_BLOCK, '2362')),
        (2827, 'consultant e-mails from the native project, not x_new_projects',
         consultant_code)):
    action = Server.browse(action_id).exists()
    if not action:
        refused.append((action_id, 'gone already'))
        continue
    old = (action.code or '').replace('\r\n', '\n')
    try:
        new = make(old)
    except ValueError as exc:
        refused.append((action_id, str(exc)))
        continue
    if 'x_items_needed' in new or 'x_consumed_materials' in new or 'x_new_projects' in new:
        refused.append((action_id, 'still names a model that is going after the rewrite'))
        continue
    plans.append((action, label, old, new))

title("1. what changes")
for action, label, old, new in plans:
    where = ('automation %s (%s)' % (action.base_automation_id.id,
                                      'active' if action.base_automation_id.active else 'inactive')
             if action.base_automation_id else action.usage)
    print("\n  %-6s %-28s on %-16s %s" % (action.id, (action.name or '')[:28], action.model_id.model, where))
    print("         %s" % label)
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm='', n=1):
        if line.startswith(('---', '+++')):
            continue
        print("         %s" % line[:120])
if refused:
    print("\n  left alone:")
    for action_id, why in refused:
        print("      %-6s %s" % (action_id, why))

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()

title("2. writing")
for action, label, old, new in plans:
    with cr.savepoint():
        action.write({'code': new})
    print("  > %s rewritten" % action.id)
cr.commit()
print("\n  %s rewritten, %s left alone. Restart the web workers: odoosh-restart http" % (len(plans), len(refused)))
