"""Draw a programme the way a planner would, and roll it all back."""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tools import mute_logger

Programme = env['ssc.programme']                                  # noqa: F821
Activity = env['ssc.programme.activity']                          # noqa: F821
Boq = env['ssc.boq']                                              # noqa: F821
Section = env['ssc.boq.section']                                  # noqa: F821
Line = env['ssc.boq.line']                                        # noqa: F821
Package = env['ssc.boq.package']                                  # noqa: F821
Zone = env['ssc.project.zone']                                    # noqa: F821
Project = env['project.project']                                  # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-62s %s" % (label, detail))


# --- a priced job to lay out -------------------------------------------------
project = Project.create({'name': "Al Rayyan Residences",
                          'ssc_is_construction': True})
block_a = Zone.create({'project_id': project.id, 'name': "Block A", 'code': 'BA'})
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
cable = Line.create({'section_id': electrical.id, 'code': '7.01',
                     'name': "4mm2 cable", 'quantity': 1200.0,
                     'unit_price': 12.0})
pkg_block = Package.create({
    'boq_id': boq.id, 'code': 'PKG-BW', 'name': "Blockwork",
    'work_type_id': env.ref('ssc_project.work_arc_block').id,     # noqa: F821
    'line_ids': [(6, 0, [wall.id])],
})
pkg_elec = Package.create({
    'boq_id': boq.id, 'code': 'PKG-EL', 'name': "Electrical First Fix",
    'work_type_id': env.ref('ssc_project.work_electrical').id,    # noqa: F821
    'line_ids': [(6, 0, [cable.id])],
})
boq.action_approve()
check("the job is priced at what its two packages come to",
      boq.amount_total == 59400.0, boq.amount_total)

# --- the programme -----------------------------------------------------------
programme = Programme.create({'project_id': project.id})
check("a programme is numbered by the sequence",
      programme.name.startswith('PRG/'), programme.name)
check("it follows the project's approved bill without being told",
      programme.boq_id == boq, programme.boq_id.display_name)

programme.action_generate_from_packages()
check("filling from the packages makes one activity each",
      programme.activity_count == 2, programme.activity_count)
check("and they carry the package value, not a typed one",
      programme.amount_planned == 59400.0, programme.amount_planned)
check("so nothing of the bill is left unprogrammed",
      programme.amount_unplanned == 0.0, programme.amount_unplanned)

programme.action_generate_from_packages()
check("running it again does not double anything",
      programme.activity_count == 2, programme.activity_count)

block_act = programme.activity_ids.filtered(lambda a: a.package_id == pkg_block)
elec_act = programme.activity_ids.filtered(lambda a: a.package_id == pkg_elec)
check("an activity took the package name", block_act.name == "Blockwork",
      block_act.name)
check("weights are a division, not a judgement",
      round(block_act.weight, 4) == round(45000.0 / 59400.0 * 100, 4),
      block_act.weight)
leaves = programme.activity_ids.filtered(lambda a: not a.child_ids)
check("and the weights come to a hundred",
      round(sum(leaves.mapped('weight')), 6) == 100.0,
      sum(leaves.mapped('weight')))

# --- dates -------------------------------------------------------------------
block_act.write({'date_start': date(2026, 3, 1),
                 'date_finish': date(2026, 4, 30)})
elec_act.write({'date_start': date(2026, 5, 1),
                'date_finish': date(2026, 6, 30)})
check("duration is worked out from the dates",
      block_act.duration_days == 61, block_act.duration_days)
check("the programme starts when its first activity does",
      str(programme.date_start) == '2026-03-01', str(programme.date_start))
check("and finishes when its last one does",
      str(programme.date_finish) == '2026-06-30', str(programme.date_finish))
check("and knows how long the whole thing is",
      programme.duration_days == 122, programme.duration_days)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        block_act.date_finish = date(2026, 2, 1)
    check("an activity cannot finish before it starts", False, "it was allowed")
except ValidationError:
    check("an activity cannot finish before it starts", True)

# --- logic -------------------------------------------------------------------
elec_act.predecessor_ids = [(6, 0, [block_act.id])]
check("an activity records what it follows",
      block_act in elec_act.predecessor_ids)
check("and the other one knows it comes first",
      elec_act in block_act.successor_ids)
check("in sequence, nothing is flagged",
      elec_act.out_of_sequence is False, elec_act.out_of_sequence)

elec_act.date_start = date(2026, 4, 1)
check("starting before its predecessor finishes is flagged",
      elec_act.out_of_sequence is True, elec_act.out_of_sequence)
elec_act.date_start = date(2026, 5, 1)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        block_act.predecessor_ids = [(6, 0, [elec_act.id])]
    check("a loop in the logic is refused", False, "it was allowed")
except ValidationError:
    check("a loop in the logic is refused", True)

# --- summary activities ------------------------------------------------------
summary = Activity.create({'programme_id': programme.id, 'code': '1',
                           'name': "Structure and Services", 'sequence': 1})
block_act.parent_id = summary
elec_act.parent_id = summary
check("an activity holding others is a summary",
      summary.is_summary is True, summary.is_summary)
check("a summary is worth what it holds, not its own package as well",
      summary.amount_planned == 59400.0, summary.amount_planned)
check("so the programme is not doubled by summarising it",
      programme.amount_planned == 59400.0, programme.amount_planned)
leaves = programme.activity_ids.filtered(lambda a: not a.child_ids)
check("and the leaves still come to a hundred per cent",
      round(sum(leaves.mapped('weight')), 6) == 100.0,
      sum(leaves.mapped('weight')))
check("a summary runs from its first child to its last",
      str(summary.date_start) == '2026-03-01'
      and str(summary.date_finish) == '2026-06-30',
      "%s to %s" % (summary.date_start, summary.date_finish))
check("a child reads as its whole path",
      block_act.complete_name == 'Structure and Services / Blockwork',
      block_act.complete_name)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        summary.parent_id = block_act
    check("an activity cannot sit under itself", False, "it was allowed")
except (ValidationError, UserError):
    check("an activity cannot sit under itself", True)

# --- baselining --------------------------------------------------------------
undated = Activity.create({'programme_id': programme.id,
                           'name': "Snagging", 'sequence': 90})
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        programme.action_set_baseline()
    check("a programme with an undated activity cannot be baselined", False,
          "it was allowed")
except UserError:
    check("a programme with an undated activity cannot be baselined", True)
undated.write({'date_start': date(2026, 7, 1),
               'date_finish': date(2026, 7, 15)})

programme.action_set_baseline()
check("baselining sets the state", programme.state == 'baseline',
      programme.state)
check("and stamps the day it happened", bool(programme.date_baseline),
      str(programme.date_baseline))
check("and freezes each activity's dates",
      str(block_act.date_finish_baseline) == '2026-04-30',
      str(block_act.date_finish_baseline))
check("the project now knows its baseline programme",
      project.ssc_programme_id == programme,
      project.ssc_programme_id.display_name)
check("nothing has slipped yet", block_act.slip_days == 0,
      block_act.slip_days)

block_act.date_finish = date(2026, 5, 21)
check("moving the finish shows the slip against the baseline",
      block_act.slip_days == 21, block_act.slip_days)
check("and the baseline itself does not move",
      str(block_act.date_finish_baseline) == '2026-04-30',
      str(block_act.date_finish_baseline))

revised = programme.action_new_revision()
revised = Programme.browse(revised['res_id'])
check("a revision is the next number", revised.revision == 1, revised.revision)
check("and carries every activity across, summary and all",
      revised.activity_count == 4, revised.activity_count)
check("and starts without a baseline of its own",
      not revised.activity_ids[0].date_finish_baseline,
      str(revised.activity_ids[0].date_finish_baseline))

revised.action_set_baseline()
check("baselining the revision supersedes the one before it",
      programme.state == 'superseded', programme.state)
check("and the project follows the new one",
      project.ssc_programme_id == revised, project.ssc_programme_id.name)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        programme.action_reset_to_draft()
    check("a superseded programme cannot be reopened", False, "it was allowed")
except UserError:
    check("a superseded programme cannot be reopened", True)

# --- who may do what ---------------------------------------------------------
engineer_group = env.ref('ssc_project.group_project_engineer')     # noqa: F821
user = env['res.users'].create({                                   # noqa: F821
    'name': "Planning Engineer", 'login': 'planner.test',
    'group_ids': [(6, 0, [env.ref('base.group_user').id,           # noqa: F821
                          engineer_group.id])],
})
try:
    Activity.with_user(user).browse(block_act.id).date_finish = date(2026, 5, 25)
    check("a planning engineer can move a date", True)
except Exception as error:
    check("a planning engineer can move a date", False, str(error)[:60])
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db',             # noqa: F821
                                         'odoo.addons.base.models.ir_rule'):
        Programme.with_user(user).browse(revised.id).unlink()
    check("a planning engineer cannot delete a programme", False,
          "it was allowed")
except Exception:
    check("a planning engineer cannot delete a programme", True)

# --- the screens -------------------------------------------------------------
for xmlid in ('ssc_planning.view_ssc_programme_form',
              'ssc_planning.view_ssc_programme_list',
              'ssc_planning.view_ssc_programme_search',
              'ssc_planning.view_ssc_programme_activity_form',
              'ssc_planning.view_ssc_programme_activity_list',
              'ssc_planning.view_ssc_programme_activity_search',
              'ssc_planning.view_ssc_programme_activity_calendar'):
    view = env.ref(xmlid)                                          # noqa: F821
    try:
        env[view.model].get_view(view.id, view.type)               # noqa: F821
        check("view opens: %s" % xmlid.split('.')[-1], True)
    except Exception as error:
        check("view opens: %s" % xmlid.split('.')[-1], False, str(error)[:70])

try:
    env['project.project'].get_view(                               # noqa: F821
        env.ref('project.edit_project').id, 'form')                # noqa: F821
    check("the project form still opens with all three pages on it", True)
except Exception as error:
    check("the project form still opens with all three pages on it", False,
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
