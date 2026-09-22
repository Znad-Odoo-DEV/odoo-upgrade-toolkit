"""Put ssc_project through what a real job does to it, and roll it all back."""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tools import mute_logger
from psycopg2.errors import UniqueViolation

Zone = env['ssc.project.zone']                                    # noqa: F821
Work = env['ssc.work.type']                                       # noqa: F821
Project = env['project.project']                                  # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-58s %s" % (label, detail))


# --- the seeded trades -------------------------------------------------------
tops = Work.search([('parent_id', '=', False)])
check("disciplines seeded", len(tops) >= 11, "%s tops" % len(tops))
check("trades seeded", Work.search_count([]) >= 45,
      "%s work types" % Work.search_count([]))

ceiling = env.ref('ssc_project.work_fin_ceiling')                 # noqa: F821
check("a trade inherits its discipline",
      ceiling.discipline == 'finishes', ceiling.discipline)
check("full name reads as a path",
      ceiling.complete_name == 'Finishes / Suspended and False Ceilings',
      ceiling.complete_name)
check("display name carries the code",
      ceiling.display_name == '[FIN-FC] Finishes / Suspended and False Ceilings',
      ceiling.display_name)

duct = env.ref('ssc_project.work_mec_ducting')                    # noqa: F821
check("MEP is worked out, not typed", duct.is_mep is True, str(duct.is_mep))
check("builders work is not MEP",
      env.ref('ssc_project.work_arc_block').is_mep is False)      # noqa: F821

# a discipline corrected at the top carries down
env.ref('ssc_project.work_finishes').discipline = 'architectural'  # noqa: F821
check("correcting a discipline carries down to its trades",
      ceiling.discipline == 'architectural', ceiling.discipline)
env.ref('ssc_project.work_finishes').discipline = 'finishes'       # noqa: F821

# --- a project, and its zones ------------------------------------------------
project = Project.create({
    'name': "Al Rayyan Residences",
    'ssc_is_construction': True,
    'ssc_code': 'SSC-2026-017',
    'ssc_date_start': date(2026, 3, 1),
    'ssc_duration_days': 540,
})
check("completion is worked out from start plus duration",
      str(project.ssc_date_completion) == '2027-08-23',
      str(project.ssc_date_completion))

project.ssc_eot_days = 60
check("an extension of time moves completion",
      str(project.ssc_date_completion) == '2027-10-22',
      str(project.ssc_date_completion))

block_a = Zone.create({'project_id': project.id, 'name': "Block A",
                       'code': 'BA', 'kind': 'block'})
ground = Zone.create({'project_id': project.id, 'name': "Ground Floor",
                      'code': 'BA-GF', 'kind': 'floor',
                      'parent_id': block_a.id, 'area_sqm': 1200})
first = Zone.create({'project_id': project.id, 'name': "First Floor",
                     'code': 'BA-F1', 'kind': 'floor',
                     'parent_id': block_a.id, 'area_sqm': 950})
flat = Zone.create({'project_id': project.id, 'name': "Flat 101",
                    'code': 'BA-F1-101', 'kind': 'unit',
                    'parent_id': first.id, 'area_sqm': 140})

check("a zone reads as its whole path",
      flat.complete_name == 'Block A / First Floor / Flat 101',
      flat.complete_name)
check("a parent with no area of its own totals its children",
      block_a.area_total == 2150, block_a.area_total)
check("a parent with its own area keeps it",
      first.area_total == 950, first.area_total)
check("the project totals only its top zones",
      project.ssc_zone_area == 2150, project.ssc_zone_area)
check("the project counts every zone", project.ssc_zone_count == 4,
      project.ssc_zone_count)

ground.area_sqm = 1300
check("changing a floor moves the block and the project",
      block_a.area_total == 2250 and project.ssc_zone_area == 2250,
      "%s / %s" % (block_a.area_total, project.ssc_zone_area))

# --- what must not be allowed ------------------------------------------------
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):          # noqa: F821
        block_a.parent_id = flat
    check("a zone cannot contain itself", False, "it was allowed")
except (ValidationError, UserError):
    check("a zone cannot contain itself", True)

other = Project.create({'name': "Another Job", 'ssc_is_construction': True})
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):          # noqa: F821
        Zone.create({'project_id': other.id, 'name': "Stray",
                     'parent_id': block_a.id})
    check("a zone cannot sit inside another project", False, "it was allowed")
except (ValidationError, UserError):
    check("a zone cannot sit inside another project", True)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):          # noqa: F821
        Zone.create({'project_id': project.id, 'name': "Duplicate",
                     'code': 'BA-GF'})
    check("two zones of a project cannot share a code", False, "it was allowed")
except UniqueViolation:
    check("two zones of a project cannot share a code", True)

zone_in_other = Zone.create({'project_id': other.id, 'name': "Ground",
                             'code': 'BA-GF'})
check("the same code on a different project is fine", bool(zone_in_other))

# --- security ----------------------------------------------------------------
reader = env.ref('ssc_project.group_project_reader')              # noqa: F821
engineer = env.ref('ssc_project.group_project_engineer')          # noqa: F821
manager = env.ref('ssc_project.group_project_manager')            # noqa: F821
check("engineer implies reader", reader in engineer.implied_ids)
check("manager implies engineer", engineer in manager.implied_ids)

user = env['res.users'].create({                                  # noqa: F821
    'name': "Site Engineer", 'login': 'site.engineer.test',
    'group_ids': [(6, 0, [env.ref('base.group_user').id,          # noqa: F821
                          engineer.id])],
})
as_engineer = Zone.with_user(user)
try:
    made = as_engineer.create({'project_id': project.id, 'name': "Roof",
                               'code': 'BA-RF'})
    check("an engineer can record a zone", bool(made))
except Exception as error:
    check("an engineer can record a zone", False, str(error)[:60])
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db',            # noqa: F821
                                         'odoo.addons.base.models.ir_rule'):
        as_engineer.browse(flat.id).unlink()
    check("an engineer cannot delete a zone", False, "it was allowed")
except Exception:
    check("an engineer cannot delete a zone", True)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db',            # noqa: F821
                                         'odoo.addons.base.models.ir_rule'):
        Work.with_user(user).create({'name': "Invented Trade"})
    check("an engineer cannot invent a trade", False, "it was allowed")
except Exception:
    check("an engineer cannot invent a trade", True)

# --- the screens open --------------------------------------------------------
for xmlid in ('ssc_project.view_ssc_project_zone_form',
              'ssc_project.view_ssc_project_zone_list',
              'ssc_project.view_ssc_project_zone_search',
              'ssc_project.view_ssc_work_type_form',
              'ssc_project.view_ssc_work_type_list',
              'ssc_project.view_ssc_work_type_search',
              'ssc_project.view_ssc_construction_project_list'):
    view = env.ref(xmlid)                                          # noqa: F821
    try:
        env[view.model].get_view(view.id, view.type)               # noqa: F821
        check("view opens: %s" % xmlid.split('.')[-1], True)
    except Exception as error:
        check("view opens: %s" % xmlid.split('.')[-1], False, str(error)[:70])

try:
    env['project.project'].get_view(                               # noqa: F821
        env.ref('project.edit_project').id, 'form')                # noqa: F821
    check("the project form still opens with our page on it", True)
except Exception as error:
    check("the project form still opens with our page on it", False,
          str(error)[:70])

menu = env.ref('ssc_project.menu_ssc_progress_root')               # noqa: F821
check("the application menu exists", bool(menu), menu.name)
check("it has its six sections", len(menu.child_id) == 6,
      "%s children" % len(menu.child_id))

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
