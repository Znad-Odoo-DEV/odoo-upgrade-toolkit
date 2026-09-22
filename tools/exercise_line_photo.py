"""The attendance line shows the employee's photo, on the form and in the list.

    odoo-bin shell -d DB < tools/exercise_line_photo.py

The photo lives on hr.employee and nowhere else. The line reads it through a
related field, so a new photo on the employee is the new photo on every one
of their lines, and a line of somebody with no photo shows Odoo's placeholder
rather than an error. The two archs are read the way the browser gets them.

Rolled back at the end.
"""
import base64
from datetime import date

from lxml import etree

Employee = env['hr.employee'].sudo()                               # noqa: F821
Day = env['ssc.attendance'].sudo()                                 # noqa: F821
Line = env['ssc.attendance.line'].sudo()                           # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-70s %s" % (label, detail))


# A one-pixel PNG is a real image as far as the field is concerned.
PIXEL = base64.b64encode(base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='))

with_photo = Employee.create({'name': "Photo test: with", 'company_id': env.company.id,  # noqa: F821
                              'barcode': 'PHWITH', 'image_1920': PIXEL})
without = Employee.create({'name': "Photo test: without", 'company_id': env.company.id,  # noqa: F821
                           'barcode': 'PHNONE'})
day = Day.create({'name': "photo test", 'date': date(2026, 9, 30)})
line_with = day.line_ids.filtered(lambda l: l.employee_id == with_photo)
line_without = day.line_ids.filtered(lambda l: l.employee_id == without)

check("the line carries the employee's photo", bool(line_with.employee_avatar),
      "%s byte(s)" % len(line_with.employee_avatar or b''))
check("and it is the employee's own image_128",
      line_with.employee_avatar == with_photo.image_128, "same bytes")
# Odoo gives every employee a placeholder image when nobody uploaded one, so
# "no photo" is still an image - the line must show whatever the employee
# record shows, never an error.
check("a line of somebody who uploaded no photo shows the employee's placeholder",
      line_without.employee_avatar == without.image_128,
      "%s byte(s), same as the employee" % len(line_without.employee_avatar or b''))

with_photo.image_1920 = False
line_with.invalidate_recordset()
check("removing the photo on the employee removes it from the line - not stored",
      not line_with.employee_avatar, "related, not copied")

# --- the archs, as the browser gets them ------------------------------------
form_id = env.ref('ssc_attendance.view_ssc_attendance_line_form').id           # noqa: F821
form = etree.fromstring(Line.get_view(form_id, 'form')['arch'])
avatar = form.find('.//field[@name="employee_avatar"]')
check("the form shows the photo", avatar is not None, "employee_avatar on the form")
check("as an avatar, top right of the sheet",
      avatar is not None and avatar.get('widget') == 'image'
      and 'oe_avatar' in (avatar.get('class') or ''), avatar.get('class') if avatar is not None else '')

list_id = env.ref('ssc_attendance.view_ssc_attendance_line_list').id           # noqa: F821
listing = etree.fromstring(Line.get_view(list_id, 'list')['arch'])
employee_col = listing.find('.//field[@name="employee_id"]')
check("the list shows the avatar beside the name",
      employee_col is not None and employee_col.get('widget') == 'many2one_avatar_employee',
      employee_col.get('widget') if employee_col is not None else 'no column')

print()
print("PASS  %s" % len(ok))
for row in ok:
    print("   ok   %s" % row)
if bad:
    print()
    print("FAIL  %s" % len(bad))
    for row in bad:
        print("   XX   %s" % row)
else:
    print()
    print("nothing failed")

env.cr.rollback()                                                  # noqa: F821
print("rolled back")
