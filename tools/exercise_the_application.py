"""Run one job end to end: priced, programmed, let, built, measured, paid.

One quantity typed by a site engineer has to move eight figures across five
modules and disagree with none of them. That is the whole claim this
application makes, and this is the test of it.
"""
from datetime import date

from odoo.exceptions import ValidationError
from odoo.tools import mute_logger

Project = env['project.project']                                  # noqa: F821
Zone = env['ssc.project.zone']                                    # noqa: F821
Boq = env['ssc.boq']                                              # noqa: F821
Section = env['ssc.boq.section']                                  # noqa: F821
Line = env['ssc.boq.line']                                        # noqa: F821
Split = env['ssc.boq.line.zone']                                  # noqa: F821
Package = env['ssc.boq.package']                                  # noqa: F821
Programme = env['ssc.programme']                                  # noqa: F821
Period = env['ssc.progress.period']                               # noqa: F821
Contract = env['ssc.subcontract']                                 # noqa: F821
Item = env['ssc.subcontract.item']                                # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-64s %s" % (label, detail))


# --- 1. the job --------------------------------------------------------------
project = Project.create({
    'name': "Al Rayyan Residences", 'ssc_is_construction': True,
    'ssc_code': 'SSC-2026-017', 'ssc_date_start': date(2026, 1, 1),
    'ssc_duration_days': 365,
})
block = Zone.create({'project_id': project.id, 'name': "Block A", 'code': 'BA'})
ground = Zone.create({'project_id': project.id, 'name': "Ground Floor",
                      'code': 'BA-GF', 'parent_id': block.id, 'area_sqm': 1200})
first = Zone.create({'project_id': project.id, 'name': "First Floor",
                     'code': 'BA-F1', 'parent_id': block.id, 'area_sqm': 950})
check("1. the job knows how big it is from its zones",
      project.ssc_zone_area == 2150.0, project.ssc_zone_area)

# --- 2. priced ---------------------------------------------------------------
boq = Boq.create({'project_id': project.id, 'purpose': 'contract'})
blockwork = Section.create({
    'boq_id': boq.id, 'code': '3', 'name': "Block Works", 'sequence': 30,
    'work_type_id': env.ref('ssc_project.work_arc_block').id})   # noqa: F821
wall = Line.create({
    'section_id': blockwork.id, 'code': '3.01', 'quantity': 900.0,
    'name': "Supply and lay 200mm blockwork", 'unit_price': 50.0,
    'cost_unit': 34.0})
Split.create({'line_id': wall.id, 'zone_id': ground.id, 'quantity': 500.0})
Split.create({'line_id': wall.id, 'zone_id': first.id, 'quantity': 400.0})
package = Package.create({
    'boq_id': boq.id, 'code': 'PKG-BW', 'name': "Blockwork to Block A",
    'zone_ids': [(6, 0, [block.id])], 'line_ids': [(6, 0, [wall.id])]})
boq.action_approve()
check("2. the job is priced at forty-five thousand",
      boq.amount_total == 45000.0, boq.amount_total)
check("   and budgeted at thirty thousand six hundred",
      boq.amount_cost == 30600.0, boq.amount_cost)
check("   so the project carries the bill value",
      project.ssc_boq_amount == 45000.0, project.ssc_boq_amount)

# --- 3. programmed -----------------------------------------------------------
programme = Programme.create({'project_id': project.id})
programme.action_generate_from_packages()
activity = programme.activity_ids[0]
activity.write({'date_start': date(2026, 1, 1),
                'date_finish': date(2026, 3, 31)})
programme.action_set_baseline()
check("3. the activity is worth the package, without being told",
      activity.amount_planned == 45000.0, activity.amount_planned)
check("   and is the whole programme, so it weighs a hundred",
      activity.weight == 100.0, activity.weight)

# --- 4. let ------------------------------------------------------------------
mason = env['res.partner'].create({'name': "Gulf Masonry LLC"})   # noqa: F821
contract = Contract.create({
    'partner_id': mason.id, 'project_id': project.id,
    'description': "Blockwork to Block A", 'package_id': package.id})
item = Item.create({
    'contract_id': contract.id, 'name': "200mm blockwork",
    'boq_line_id': wall.id, 'unit': 'sqm', 'quantity': 900.0,
    'unit_price': 36.0})
check("4. the contract knows what the package was sold for",
      contract.amount_sold == 45000.0, contract.amount_sold)
check("   and what it is being bought for",
      contract.amount_untaxed == 32400.0, contract.amount_untaxed)
check("   so the margin is a subtraction, not an argument",
      contract.margin_amount == 12600.0, contract.margin_amount)
check("   the item margin per unit is fourteen",
      item.margin_unit == 14.0, item.margin_unit)
check("   and it is not being bought above the bill",
      item.is_losing is False, item.is_losing)

item.unit_price = 55.0
check("   buying above the bill rate is flagged on the item",
      item.is_losing is True, item.is_losing)
check("   and counted on the contract",
      contract.item_losing_count == 1, contract.item_losing_count)
item.unit_price = 36.0

other = Project.create({'name': "Another Job", 'ssc_is_construction': True})
other_boq = Boq.create({'project_id': other.id})
other_section = Section.create({'boq_id': other_boq.id, 'name': "Bill"})
other_line = Line.create({'section_id': other_section.id, 'name': "Something",
                          'quantity': 1.0, 'unit_price': 1.0})
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        item.boq_line_id = other_line
    check("   an item cannot buy another job's bill item", False,
          "it was allowed")
except ValidationError:
    check("   an item cannot buy another job's bill item", True)

# --- 5. built and measured ---------------------------------------------------
january = Period.create({'project_id': project.id,
                         'date_from': date(2026, 1, 1),
                         'date_to': date(2026, 1, 31)})
january.action_generate_lines()
gf = january.line_ids.filtered(lambda line: line.zone_id == ground)

# the one number anybody types
gf.quantity = 500.0

january.action_submit()
january.action_approve()

check("5. one quantity was typed, and the item is measured",
      gf.quantity_cumulative == 500.0, gf.quantity_cumulative)
check("   the ground floor is a hundred per cent done",
      gf.percent_complete == 100.0, gf.percent_complete)
check("   twenty-five thousand was earned",
      january.amount_period == 25000.0, january.amount_period)
check("   the project says fifty-five per cent complete",
      round(project.ssc_percent_complete, 4)
      == round(25000.0 / 45000.0 * 100, 4), project.ssc_percent_complete)
check("   the activity earned the same twenty-five thousand",
      activity.amount_earned == 25000.0, activity.amount_earned)
check("   and the programme with it",
      programme.amount_earned == 25000.0, programme.amount_earned)
check("   the whole bill is not finished, only the ground floor",
      round(activity.percent_complete, 4)
      == round(25000.0 / 45000.0 * 100, 4), activity.percent_complete)

# and against the baseline
planned = activity._planned_to(date(2026, 1, 31))
check("   the baseline says a third of it should have been earned by then",
      round(planned, 2) == round(45000.0 * 31 / 90, 2), planned)
check("   so on the last day of January the job was ahead",
      activity.amount_earned > planned,
      "%s earned against %s planned" % (activity.amount_earned, round(planned)))

# --- 6. and none of it disagrees --------------------------------------------
check("6. the bill total is still what the sections come to",
      boq.amount_total == sum(boq.section_ids.mapped('amount_total')),
      boq.amount_total)
check("   the package is still worth its items",
      package.amount_total == sum(package.line_ids.mapped('amount')),
      package.amount_total)
check("   the programme is still worth its top activities",
      programme.amount_planned == sum(
          programme.activity_ids.filtered(lambda a: not a.parent_id)
          .mapped('amount_planned')), programme.amount_planned)
check("   what was earned is what was measured",
      programme.amount_earned == january.amount_period,
      programme.amount_earned)
check("   and what was sold less what was bought is the margin",
      contract.amount_sold - contract.amount_untaxed == contract.margin_amount,
      contract.margin_amount)

# --- 7. the application ------------------------------------------------------
root = env.ref('ssc_project.menu_ssc_progress_root')               # noqa: F821
sections = root.child_id.filtered('active')
check("7. the application has its five sections and configuration",
      len(sections) == 6, ", ".join(sections.mapped('name')))
check("   the subcontracts moved under it",
      env.ref('ssc_subcontract.menu_ssc_subcontract_contracts').parent_id  # noqa: F821
      == env.ref('ssc_project.menu_ssc_procurement_root'),        # noqa: F821
      env.ref(                                                     # noqa: F821
          'ssc_subcontract.menu_ssc_subcontract_contracts').parent_id.name)
check("   and their own top-level menu is switched off, not deleted",
      env.ref('ssc_subcontract.menu_ssc_subcontract_root').active is False)  # noqa: F821
check("   every section leads somewhere",
      all(menu.child_id or menu.action for menu in sections),
      ", ".join(menu.name for menu in sections
                if not menu.child_id and not menu.action) or "all of them")

for xmlid, model, kind in (
        ('ssc_subcontract_boq.view_ssc_subcontract_form_boq',
         'ssc.subcontract', 'form'),
        ('ssc_subcontract.view_ssc_subcontract_form', 'ssc.subcontract', 'form'),
        ('ssc_subcontract.view_ssc_subcontract_item_form',
         'ssc.subcontract.item', 'form'),
        ('ssc_subcontract.view_ssc_subcontract_item_list',
         'ssc.subcontract.item', 'list'),
        ('ssc_subcontract.view_ssc_subcontract_item_search',
         'ssc.subcontract.item', 'search'),
        ('project.edit_project', 'project.project', 'form')):
    try:
        env[model].get_view(env.ref(xmlid).id, kind)               # noqa: F821
        check("   view opens: %s" % xmlid.split('.')[-1], True)
    except Exception as error:
        check("   view opens: %s" % xmlid.split('.')[-1], False,
              str(error)[:70])

# and as somebody who is not allowed to see any of the money
reader_group = env.ref('ssc_project.group_project_reader')         # noqa: F821
reader = env['res.users'].create({                                 # noqa: F821
    'name': "Document Controller", 'login': 'reader.test',
    'group_ids': [(6, 0, [env.ref('base.group_user').id,           # noqa: F821
                          reader_group.id])]})
for model, xmlid, kind in (
        ('ssc.boq', 'ssc_boq.view_ssc_boq_form', 'form'),
        ('ssc.programme', 'ssc_planning.view_ssc_programme_form', 'form'),
        ('ssc.progress.period',
         'ssc_progress.view_ssc_progress_period_form', 'form'),
        ('ssc.subcontract', 'ssc_subcontract.view_ssc_subcontract_form',
         'form')):
    try:
        env[model].with_user(reader).get_view(                     # noqa: F821
            env.ref(xmlid).id, kind)                               # noqa: F821
        check("   opens for a reader: %s" % model, True)
    except Exception as error:
        check("   opens for a reader: %s" % model, False, str(error)[:70])

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
