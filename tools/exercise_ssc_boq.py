"""Price a job the way a quantity surveyor would, and roll it all back."""
from odoo.exceptions import UserError, ValidationError
from odoo.tools import mute_logger
from psycopg2.errors import UniqueViolation

Boq = env['ssc.boq']                                              # noqa: F821
Section = env['ssc.boq.section']                                  # noqa: F821
Line = env['ssc.boq.line']                                        # noqa: F821
Split = env['ssc.boq.line.zone']                                  # noqa: F821
Package = env['ssc.boq.package']                                  # noqa: F821
Zone = env['ssc.project.zone']                                    # noqa: F821
Project = env['project.project']                                  # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-60s %s" % (label, detail))


project = Project.create({
    'name': "Al Rayyan Residences", 'ssc_is_construction': True,
    'ssc_code': 'SSC-2026-017',
})
block_a = Zone.create({'project_id': project.id, 'name': "Block A", 'code': 'BA'})
ground = Zone.create({'project_id': project.id, 'name': "Ground Floor",
                      'code': 'BA-GF', 'parent_id': block_a.id})
first = Zone.create({'project_id': project.id, 'name': "First Floor",
                     'code': 'BA-F1', 'parent_id': block_a.id})

# --- the bill ----------------------------------------------------------------
boq = Boq.create({'project_id': project.id, 'purpose': 'contract'})
check("a bill is numbered by the sequence, not by hand",
      boq.name.startswith('BOQ/'), boq.name)
check("the first bill of a project is revision nought",
      boq.revision == 0, boq.revision)
check("it reads as its reference and revision",
      boq.display_name.endswith('(Rev 0)'), boq.display_name)
check("the employer is read off the project, not typed",
      boq.client_id == project.ssc_client_id)

blockwork = Section.create({
    'boq_id': boq.id, 'code': '3', 'name': "Block Works",
    'work_type_id': env.ref('ssc_project.work_arc_block').id,   # noqa: F821
    'sequence': 30,
})
electrical = Section.create({
    'boq_id': boq.id, 'code': '7', 'name': "Electrical",
    'work_type_id': env.ref('ssc_project.work_electrical').id,  # noqa: F821
    'sequence': 70,
})
check("a bill reads as its number and name",
      blockwork.display_name == 'Bill 3 - Block Works', blockwork.display_name)
check("a bill knows its discipline through its trade",
      blockwork.discipline == 'architectural', blockwork.discipline)

heading = Line.create({
    'section_id': blockwork.id, 'display_type': 'line_section',
    'name': "Internal walls", 'sequence': 1,
})
wall_200 = Line.create({
    'section_id': blockwork.id, 'code': '3.01', 'sequence': 10,
    'name': "Supply and lay 200mm solid concrete block to internal walls",
    'quantity': 900.0, 'unit_price': 45.0, 'cost_unit': 32.0,
})
wall_100 = Line.create({
    'section_id': blockwork.id, 'code': '3.02', 'sequence': 20,
    'name': "Ditto but 100mm", 'quantity': 400.0,
    'unit_price': 30.0, 'cost_unit': 34.0,
})
cable = Line.create({
    'section_id': electrical.id, 'code': '7.01', 'sequence': 10,
    'name': "Supply and install 4mm2 cable", 'quantity': 1200.0,
    'unit_price': 12.0, 'cost_unit': 9.0,
})

check("an item takes its unit from its trade",
      wall_200.uom_id == env.ref('uom.product_uom_square_meter'),  # noqa: F821
      wall_200.uom_id.display_name)
check("an item takes its trade from its bill",
      wall_200.work_type_id == env.ref('ssc_project.work_arc_block'))  # noqa: F821
check("the cable took the electrical trade, not the blockwork one",
      cable.work_type_id == env.ref('ssc_project.work_electrical'))  # noqa: F821
check("amount is quantity times rate", wall_200.amount == 40500.0,
      wall_200.amount)
check("budgeted cost is quantity times budget rate",
      wall_200.amount_cost == 28800.0, wall_200.amount_cost)
check("margin is worked out per item",
      round(wall_200.margin_percent, 2) == 28.89, wall_200.margin_percent)
check("an item priced under its budget shows a negative margin",
      wall_100.margin_amount == -1600.0, wall_100.margin_amount)
check("a heading carries no money", heading.amount == 0.0, heading.amount)

check("a bill totals only its priced items",
      blockwork.amount_total == 52500.0, blockwork.amount_total)
check("a bill counts only its priced items",
      blockwork.line_count == 2, blockwork.line_count)
check("the bill of quantities totals its bills",
      boq.amount_total == 66900.0, boq.amount_total)
check("and its budget", boq.amount_cost == 53200.0, boq.amount_cost)
check("and its margin",
      boq.margin_amount == 13700.0, boq.margin_amount)
check("the bill counts every line, headings and all",
      boq.line_count == 4, boq.line_count)

wall_200.unit_price = 50.0
check("changing a rate moves the item, the bill and the whole thing",
      wall_200.amount == 45000.0 and blockwork.amount_total == 57000.0
      and boq.amount_total == 71400.0,
      "%s / %s / %s" % (wall_200.amount, blockwork.amount_total,
                        boq.amount_total))

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):          # noqa: F821
        heading.quantity = 10
    check("a heading cannot be given a quantity", False, "it was allowed")
except ValidationError:
    check("a heading cannot be given a quantity", True)

# --- the split across the building -------------------------------------------
Split.create({'line_id': wall_200.id, 'zone_id': ground.id, 'quantity': 500.0})
Split.create({'line_id': wall_200.id, 'zone_id': first.id, 'quantity': 350.0})
on_ground = wall_200.zone_ids.filtered(lambda s: s.zone_id == ground)
check("a split is worth its quantity at the bill rate",
      on_ground.amount == 25000.0, on_ground.amount)
check("the item knows how much of it has been placed",
      wall_200.quantity_allocated == 850.0, wall_200.quantity_allocated)
check("and how much has not",
      wall_200.quantity_unallocated == 50.0, wall_200.quantity_unallocated)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):          # noqa: F821
        Split.create({'line_id': wall_200.id, 'zone_id': ground.id,
                      'quantity': 5.0})
    check("an item cannot be split into one zone twice", False, "it was allowed")
except UniqueViolation:
    check("an item cannot be split into one zone twice", True)

other = Project.create({'name': "Another Job", 'ssc_is_construction': True})
stray = Zone.create({'project_id': other.id, 'name': "Elsewhere"})
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):          # noqa: F821
        Split.create({'line_id': wall_200.id, 'zone_id': stray.id,
                      'quantity': 5.0})
    check("an item cannot be split into another job's zone", False,
          "it was allowed")
except ValidationError:
    check("an item cannot be split into another job's zone", True)

# --- packages ----------------------------------------------------------------
package = Package.create({
    'boq_id': boq.id, 'code': 'PKG-BW', 'name': "Blockwork to Block A",
    'work_type_id': env.ref('ssc_project.work_arc_block').id,   # noqa: F821
    'zone_ids': [(6, 0, [block_a.id])],
    'line_ids': [(6, 0, [wall_200.id, wall_100.id])],
})
check("a package is worth the items in it",
      package.amount_total == 57000.0, package.amount_total)
check("and knows what it was budgeted at",
      package.amount_cost == 42400.0, package.amount_cost)
check("and counts them", package.line_count == 2, package.line_count)

# --- approving, superseding, revising ----------------------------------------
empty = Boq.create({'project_id': other.id})
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):          # noqa: F821
        empty.action_approve()
    check("an empty bill cannot be approved", False, "it was allowed")
except UserError:
    check("an empty bill cannot be approved", True)

boq.action_approve()
check("approving sets the state", boq.state == 'approved', boq.state)
check("the project now knows its live bill",
      project.ssc_boq_id == boq, project.ssc_boq_id.display_name)
check("and its value", project.ssc_boq_amount == 71400.0,
      project.ssc_boq_amount)
check("and what it was budgeted to cost",
      project.ssc_boq_cost == boq.amount_cost and boq.amount_cost > 0,
      project.ssc_boq_cost)

# --- the budget beside the spend ---------------------------------------------
Plan = env['account.analytic.plan']                               # noqa: F821
plan = Plan.search([], limit=1) or Plan.create({'name': "Projects"})
project.account_id = env['account.analytic.account'].create({     # noqa: F821
    'name': project.name, 'plan_id': plan.id})
check("a project with nothing posted has cost nothing",
      project.ssc_actual_cost == 0.0, project.ssc_actual_cost)
env['account.analytic.line'].create([                             # noqa: F821
    {'name': "cement", 'account_id': project.account_id.id, 'amount': -1000.0},
    {'name': "steel", 'account_id': project.account_id.id, 'amount': -250.5},
    {'name': "certificate", 'account_id': project.account_id.id, 'amount': 5000.0},
])
project.invalidate_recordset(['ssc_actual_cost', 'ssc_cost_remaining'])
check("actual cost is the costs on the analytic account, not the revenue",
      project.ssc_actual_cost == 1250.5, project.ssc_actual_cost)
check("budget remaining is budget less actual",
      project.ssc_cost_remaining == project.ssc_boq_cost - 1250.5,
      project.ssc_cost_remaining)

revision = boq.copy({'state': 'draft', 'purpose': 'variation'})
check("a revision is the next number",
      revision.revision == 1, revision.revision)
check("a revision carries the bills across",
      len(revision.section_ids) == 2, len(revision.section_ids))
check("and the items in them",
      len(revision.line_ids) == 4, len(revision.line_ids))
check("and prices the same", revision.amount_total == 71400.0,
      revision.amount_total)

revision.section_ids[0].line_ids[1].quantity = 1000.0
revision.action_approve()
check("approving a revision supersedes the one before it",
      boq.state == 'superseded', boq.state)
check("the project follows the new one",
      project.ssc_boq_id == revision, project.ssc_boq_id.display_name)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):          # noqa: F821
        boq.action_reset_to_draft()
    check("a superseded bill cannot be reopened", False, "it was allowed")
except UserError:
    check("a superseded bill cannot be reopened", True)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):          # noqa: F821
        Boq.create({'project_id': project.id, 'revision': 1})
    check("a project cannot have one revision number twice", False,
          "it was allowed")
except UniqueViolation:
    check("a project cannot have one revision number twice", True)

# --- who may do what ---------------------------------------------------------
engineer_group = env.ref('ssc_project.group_project_engineer')     # noqa: F821
user = env['res.users'].create({                                   # noqa: F821
    'name': "Site Engineer", 'login': 'site.engineer.boq',
    'group_ids': [(6, 0, [env.ref('base.group_user').id,           # noqa: F821
                          engineer_group.id])],
})
try:
    Boq.with_user(user).search([])[0].amount_total
    check("an engineer can read the bill", True)
except Exception as error:
    check("an engineer can read the bill", False, str(error)[:60])
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db',             # noqa: F821
                                         'odoo.addons.base.models.ir_rule'):
        Line.with_user(user).browse(wall_200.id).unit_price = 99.0
    check("an engineer cannot reprice an item", False, "it was allowed")
except Exception:
    check("an engineer cannot reprice an item", True)
try:
    Split.with_user(user).create({'line_id': cable.id, 'zone_id': ground.id,
                                  'quantity': 100.0})
    check("an engineer can split a quantity across zones", True)
except Exception as error:
    check("an engineer can split a quantity across zones", False,
          str(error)[:60])
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db',             # noqa: F821
                                         'odoo.addons.base.models.ir_rule'):
        Line.with_user(user).browse(wall_200.id).read(['cost_unit'])
    check("an engineer cannot see the budget rate", False, "it was readable")
except Exception:
    check("an engineer cannot see the budget rate", True)

# --- the screens -------------------------------------------------------------
for xmlid in ('ssc_boq.view_ssc_boq_form', 'ssc_boq.view_ssc_boq_list',
              'ssc_boq.view_ssc_boq_search',
              'ssc_boq.view_ssc_boq_section_form',
              'ssc_boq.view_ssc_boq_section_list',
              'ssc_boq.view_ssc_boq_section_search',
              'ssc_boq.view_ssc_boq_line_form',
              'ssc_boq.view_ssc_boq_line_list',
              'ssc_boq.view_ssc_boq_line_search',
              'ssc_boq.view_ssc_boq_line_zone_list',
              'ssc_boq.view_ssc_boq_line_zone_search',
              'ssc_boq.view_ssc_boq_package_form',
              'ssc_boq.view_ssc_boq_package_list',
              'ssc_boq.view_ssc_boq_package_search'):
    view = env.ref(xmlid)                                          # noqa: F821
    try:
        env[view.model].get_view(view.id, view.type)               # noqa: F821
        check("view opens: %s" % xmlid.split('.')[-1], True)
    except Exception as error:
        check("view opens: %s" % xmlid.split('.')[-1], False, str(error)[:70])

try:
    env['project.project'].get_view(                               # noqa: F821
        env.ref('project.edit_project').id, 'form')                # noqa: F821
    check("the project form still opens with both our pages on it", True)
except Exception as error:
    check("the project form still opens with both our pages on it", False,
          str(error)[:70])

# the same form as the engineer, who cannot see the budget columns
try:
    env['project.project'].with_user(user).get_view(                # noqa: F821
        env.ref('project.edit_project').id, 'form')                 # noqa: F821
    env['ssc.boq'].with_user(user).get_view(                        # noqa: F821
        env.ref('ssc_boq.view_ssc_boq_form').id, 'form')            # noqa: F821
    check("the screens open for a user who cannot see the budget", True)
except Exception as error:
    check("the screens open for a user who cannot see the budget", False,
          str(error)[:70])

print()
print("PASS  %s" % len(ok))
for line in ok:
    print("   ok   %s" % line)
if bad:
    print()
    print("FAIL  %s" % len(bad))
    for line in bad:
        print("   XX   %s" % line)
else:
    print()
    print("nothing failed")

env.cr.rollback()                                                  # noqa: F821
print("rolled back")
