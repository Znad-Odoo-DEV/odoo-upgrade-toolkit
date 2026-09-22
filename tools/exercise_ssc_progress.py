"""Measure a job over three months and check every figure that follows."""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tools import mute_logger
from psycopg2.errors import UniqueViolation

Period = env['ssc.progress.period']                               # noqa: F821
PLine = env['ssc.progress.line']                                  # noqa: F821
Programme = env['ssc.programme']                                  # noqa: F821
Boq = env['ssc.boq']                                              # noqa: F821
Section = env['ssc.boq.section']                                  # noqa: F821
Line = env['ssc.boq.line']                                        # noqa: F821
Split = env['ssc.boq.line.zone']                                  # noqa: F821
Package = env['ssc.boq.package']                                  # noqa: F821
Zone = env['ssc.project.zone']                                    # noqa: F821
Project = env['project.project']                                  # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-64s %s" % (label, detail))


# --- a priced, programmed job ------------------------------------------------
project = Project.create({'name': "Al Rayyan Residences",
                          'ssc_is_construction': True})
ground = Zone.create({'project_id': project.id, 'name': "Ground Floor",
                      'code': 'GF'})
first = Zone.create({'project_id': project.id, 'name': "First Floor",
                     'code': 'F1'})
boq = Boq.create({'project_id': project.id})
blockwork = Section.create({
    'boq_id': boq.id, 'code': '3', 'name': "Block Works",
    'work_type_id': env.ref('ssc_project.work_arc_block').id,     # noqa: F821
})
electrical = Section.create({
    'boq_id': boq.id, 'code': '7', 'name': "Electrical",
    'work_type_id': env.ref('ssc_project.work_electrical').id,    # noqa: F821
})
wall = Line.create({'section_id': blockwork.id, 'code': '3.01',
                    'name': "200mm blockwork", 'quantity': 900.0,
                    'unit_price': 50.0})
Split.create({'line_id': wall.id, 'zone_id': ground.id, 'quantity': 500.0})
Split.create({'line_id': wall.id, 'zone_id': first.id, 'quantity': 400.0})
cable = Line.create({'section_id': electrical.id, 'code': '7.01',
                     'name': "4mm2 cable", 'quantity': 1200.0,
                     'unit_price': 12.0})
Line.create({'section_id': blockwork.id, 'display_type': 'line_section',
             'name': "Internal walls"})
pkg_block = Package.create({
    'boq_id': boq.id, 'code': 'PKG-BW', 'name': "Blockwork",
    'line_ids': [(6, 0, [wall.id])],
})
pkg_elec = Package.create({
    'boq_id': boq.id, 'code': 'PKG-EL', 'name': "Electrical",
    'line_ids': [(6, 0, [cable.id])],
})
boq.action_approve()
check("the job is priced", boq.amount_total == 59400.0, boq.amount_total)

programme = Programme.create({'project_id': project.id})
programme.action_generate_from_packages()
block_act = programme.activity_ids.filtered(lambda a: a.package_id == pkg_block)
elec_act = programme.activity_ids.filtered(lambda a: a.package_id == pkg_elec)
block_act.write({'date_start': date(2026, 1, 1),
                 'date_finish': date(2026, 4, 30)})
elec_act.write({'date_start': date(2026, 3, 1),
                'date_finish': date(2026, 6, 30)})
programme.action_set_baseline()
check("and programmed", programme.state == 'baseline', programme.state)

# --- the first measurement ---------------------------------------------------
january = Period.create({'project_id': project.id,
                         'date_from': date(2026, 1, 1),
                         'date_to': date(2026, 1, 31)})
check("a measurement is numbered by the sequence",
      january.name.startswith('PRG-M/'), january.name)
check("and is the first of its project", january.sequence_no == 1,
      january.sequence_no)
check("and takes the project's approved bill",
      january.boq_id == boq, january.boq_id.display_name)

january.action_generate_lines()
check("filling from the bill makes a line per item, split where it was split",
      january.line_count == 3, january.line_count)
check("and leaves the headings off it",
      all(not line.boq_line_id.display_type for line in january.line_ids))

january.action_generate_lines()
check("running it again does not double anything",
      january.line_count == 3, january.line_count)

gf_wall = january.line_ids.filtered(
    lambda line: line.boq_line_id == wall and line.zone_id == ground)
f1_wall = january.line_ids.filtered(
    lambda line: line.boq_line_id == wall and line.zone_id == first)
elec = january.line_ids.filtered(lambda line: line.boq_line_id == cable)
check("a line knows what the bill allows it in its own zone",
      gf_wall.quantity_contract == 500.0, gf_wall.quantity_contract)
check("and what that is worth", gf_wall.amount_contract == 25000.0,
      gf_wall.amount_contract)
check("an item nobody split is measured whole",
      elec.quantity_contract == 1200.0, elec.quantity_contract)

gf_wall.quantity = 300.0
check("what was measured is worth quantity times the bill rate",
      gf_wall.amount_period == 15000.0, gf_wall.amount_period)
check("nothing was measured before, so to date is this period",
      gf_wall.quantity_cumulative == 300.0, gf_wall.quantity_cumulative)
check("the percentage is a division, not a typed number",
      gf_wall.percent_complete == 60.0, gf_wall.percent_complete)
check("and it knows what is left", gf_wall.quantity_remaining == 200.0,
      gf_wall.quantity_remaining)
check("the sheet totals what was measured on it",
      january.amount_period == 15000.0, january.amount_period)

january.action_submit()
january.action_approve()
check("approving stamps who and when",
      january.approved_by == env.user and bool(january.approved_on),  # noqa: F821
      str(january.approved_on))
check("the project knows what has been earned",
      project.ssc_amount_earned == 15000.0, project.ssc_amount_earned)
check("and how far along it is, as a division",
      round(project.ssc_percent_complete, 4)
      == round(15000.0 / 59400.0 * 100, 4), project.ssc_percent_complete)

# --- the second measurement, which must see the first ------------------------
february = Period.create({'project_id': project.id,
                          'date_from': date(2026, 2, 1),
                          'date_to': date(2026, 2, 28)})
check("the second measurement of a project is number two",
      february.sequence_no == 2, february.sequence_no)
february.action_generate_lines()
feb_gf = february.line_ids.filtered(
    lambda line: line.boq_line_id == wall and line.zone_id == ground)
check("it sees what January already claimed",
      feb_gf.quantity_previous == 300.0, feb_gf.quantity_previous)
check("and what that was worth", feb_gf.amount_previous == 15000.0,
      feb_gf.amount_previous)

feb_gf.quantity = 200.0
check("to date is what was claimed before plus this period",
      feb_gf.quantity_cumulative == 500.0, feb_gf.quantity_cumulative)
check("the zone is finished, so the percentage says a hundred",
      feb_gf.percent_complete == 100.0, feb_gf.percent_complete)
check("and nothing is left", feb_gf.quantity_remaining == 0.0,
      feb_gf.quantity_remaining)
check("the sheet shows what came before it as well",
      february.amount_previous == 15000.0, february.amount_previous)
check("and its own cumulative", february.amount_cumulative == 25000.0,
      february.amount_cumulative)

# --- over-measurement --------------------------------------------------------
feb_gf.quantity = 300.0
check("claiming more in total than the bill allows is flagged",
      feb_gf.is_over_measured is True, feb_gf.is_over_measured)
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        february.action_submit()
    check("and a sheet carrying one cannot be submitted", False,
          "it was allowed")
except UserError:
    check("and a sheet carrying one cannot be submitted", True)
feb_gf.quantity = 200.0
check("correcting it clears the flag", feb_gf.is_over_measured is False,
      feb_gf.is_over_measured)

feb_f1 = february.line_ids.filtered(
    lambda line: line.boq_line_id == wall and line.zone_id == first)
feb_f1.quantity = 100.0
february.line_ids.filtered(
    lambda line: line.boq_line_id == cable).quantity = 400.0
february.action_submit()
february.action_approve()

# --- what must not be allowed ------------------------------------------------
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        january.action_reset_to_draft()
    check("an approved sheet with later ones on top cannot be reopened", False,
          "it was allowed")
except UserError:
    check("an approved sheet with later ones on top cannot be reopened", True)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        PLine.create({'period_id': february.id, 'boq_line_id': wall.id,
                      'zone_id': ground.id, 'quantity': 5.0})
    check("an item cannot be measured twice in one zone on one sheet", False,
          "it was allowed")
except UniqueViolation:
    check("an item cannot be measured twice in one zone on one sheet", True)

other = Project.create({'name': "Another Job", 'ssc_is_construction': True})
stray = Zone.create({'project_id': other.id, 'name': "Elsewhere"})
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        PLine.create({'period_id': february.id, 'boq_line_id': cable.id,
                      'zone_id': stray.id, 'quantity': 5.0})
    check("work cannot be measured in another job's zone", False,
          "it was allowed")
except ValidationError:
    check("work cannot be measured in another job's zone", True)

empty = Period.create({'project_id': other.id, 'date_from': date(2026, 1, 1),
                       'date_to': date(2026, 1, 31)})
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        empty.action_submit()
    check("an empty sheet cannot be submitted", False, "it was allowed")
except UserError:
    check("an empty sheet cannot be submitted", True)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        Period.create({'project_id': project.id,
                       'date_from': date(2026, 3, 31),
                       'date_to': date(2026, 3, 1)})
    check("a measurement cannot end before it starts", False, "it was allowed")
except Exception:
    check("a measurement cannot end before it starts", True)

# --- earned value on the programme -------------------------------------------
check("the blockwork activity has earned what was measured against it",
      block_act.amount_earned == 30000.0, block_act.amount_earned)
check("the electrical activity too", elec_act.amount_earned == 4800.0,
      elec_act.amount_earned)
check("an activity's completion is earned over planned",
      round(block_act.percent_complete, 4)
      == round(30000.0 / 45000.0 * 100, 4), block_act.percent_complete)
check("the programme totals what has been earned",
      programme.amount_earned == 34800.0, programme.amount_earned)

planned_at_end = block_act._planned_to(date(2026, 4, 30))
planned_before = block_act._planned_to(date(2025, 12, 31))
planned_half = block_act._planned_to(date(2026, 2, 28))
check("planned value is nought before an activity starts",
      planned_before == 0.0, planned_before)
check("and all of it once the activity should have finished",
      planned_at_end == 45000.0, planned_at_end)
check("and the money run out evenly in between",
      round(planned_half, 2) == round(45000.0 * 59 / 120, 2), planned_half)

# --- who may do what ---------------------------------------------------------
engineer_group = env.ref('ssc_project.group_project_engineer')     # noqa: F821
user = env['res.users'].create({                                   # noqa: F821
    'name': "Site Engineer", 'login': 'site.engineer.progress',
    'group_ids': [(6, 0, [env.ref('base.group_user').id,           # noqa: F821
                          engineer_group.id])],
})
march = Period.with_user(user).create({
    'project_id': project.id, 'date_from': date(2026, 3, 1),
    'date_to': date(2026, 3, 31)})
check("a site engineer can raise and fill a measurement", bool(march),
      march.name)
march.action_generate_lines()
march.line_ids[0].quantity = 10.0
march.action_submit()
check("and submit it", march.state == 'submitted', march.state)
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db',             # noqa: F821
                                         'odoo.addons.base.models.ir_rule'):
        march.with_user(user).action_approve()
    check("but cannot approve it", False, "it was allowed")
except Exception:
    check("but cannot approve it", True)
as_manager = Period.browse(march.id)
as_manager.action_approve()
check("while a manager can", as_manager.state == "approved", as_manager.state)

# --- the screens -------------------------------------------------------------
for xmlid in ('ssc_progress.view_ssc_progress_period_form',
              'ssc_progress.view_ssc_progress_period_list',
              'ssc_progress.view_ssc_progress_period_search',
              'ssc_progress.view_ssc_progress_line_form',
              'ssc_progress.view_ssc_progress_line_list',
              'ssc_progress.view_ssc_progress_line_search',
              'ssc_progress.view_ssc_progress_line_graph',
              'ssc_progress.view_ssc_progress_line_pivot'):
    view = env.ref(xmlid)                                          # noqa: F821
    try:
        env[view.model].get_view(view.id, view.type)               # noqa: F821
        check("view opens: %s" % xmlid.split('.')[-1], True)
    except Exception as error:
        check("view opens: %s" % xmlid.split('.')[-1], False, str(error)[:70])

for xmlid, model, kind in (
        ('ssc_planning.view_ssc_programme_form', 'ssc.programme', 'form'),
        ('ssc_planning.view_ssc_programme_activity_form',
         'ssc.programme.activity', 'form'),
        ('ssc_planning.view_ssc_programme_activity_list',
         'ssc.programme.activity', 'list'),
        ('project.edit_project', 'project.project', 'form')):
    try:
        env[model].get_view(env.ref(xmlid).id, kind)               # noqa: F821
        check("still opens with progress on it: %s" % xmlid.split('.')[-1], True)
    except Exception as error:
        check("still opens with progress on it: %s" % xmlid.split('.')[-1],
              False, str(error)[:70])

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
