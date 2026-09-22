"""Bring the staff payslips across, and check first that they are not here twice.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/import_staff_payslips.py

x_staff_payslips is the second payroll master and nothing had ever mirrored it:
345 rows, engineer and office staff, paid by the month rather than by the punch.

Two things were established before the bridge was written, and both are checked
again here because a check that only ran once is a check that ran on a different
database:

 * its ids do not collide with the ones already in studio_ref_id. That column
   was written from x_all_payslips, and an integer says nothing about which
   model it came from.
 * no employee and month it holds already has a payslip here, which would make
   this a duplication rather than a migration.

What the figures mean was settled by arithmetic and not by their names. On
test_2 that mapping lived in the module (ssc.payslip._studio_staff_payslip_vals
and its two companions); main never carried it, and a module change for a
one-off import is not worth a build, so the same three functions live here,
copied from test_2's ssc_payslip.py as of 2026-09-05 and reading only fields
main's ssc.payslip already has.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'
CHUNK = int(os.environ.get('SSC_CHUNK') or 100)

SOURCE = 'x_staff_payslips'

cr = env.cr                                                      # noqa: F821
Slip = env['ssc.payslip'].sudo().with_context(active_test=False)  # noqa: F821
Source = env.get(SOURCE)                                         # noqa: F821

if Source is None:
    raise SystemExit("%s is not in this database." % SOURCE)
Source = Source.sudo().with_context(active_test=False)


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def g(record, name):
    if not record or name not in record._fields:
        return False
    return record[name]


title("0. before anything is created")

rows = Source.search([], order='id')
done = set(Slip.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
todo = rows.filtered(lambda r: r.id not in done)

print("  %s staff payslip(s) on the Studio side" % len(rows))
print("  %s already mirrored" % (len(rows) - len(todo)))
print("  %s to bring across" % len(todo))
print("  %s payslip(s) here in total" % Slip.search_count([]))

# The reference is shared with the labour payslips. Checked every run.
theirs = set(rows.ids)
labour = set(Slip.search([('studio_ref_id', '!=', False),
                          ('is_staff', '=', False)]).mapped('studio_ref_id'))
collide = sorted(theirs & labour)
if collide:
    print("\n  STOPPED. %s id(s) are already used as a reference by a labour "
          "payslip: %s" % (len(collide), collide[:12]))
    raise SystemExit(
        "\nTwo payslips cannot answer to one reference. Nothing was changed.")
print("  no id here is already a labour payslip's reference")

# And the same person in the same month.
ours = {}
for slip in Slip.search([]):
    hr = slip.employee_id.hr_employee_id if slip.employee_id else False
    ours[(hr.id if hr else 0, str(slip.month or ''), str(slip.year or ''))] = slip

Resolver = env['ssc.attachment'].sudo()                          # noqa: F821
Attachment = env['ssc.attachment'].sudo()                        # noqa: F821
StaffSheet = env['ssc.staff.attendance'].sudo()                  # noqa: F821
Batch = env['ssc.salary.batch'].sudo()                           # noqa: F821
MONTH_CODES = [code for code, _label in Slip._fields['month'].selection]


def staff_vals(src):
    """test_2's ssc.payslip._studio_staff_payslip_vals, verbatim in substance."""
    employee = Resolver._resolve_studio_employee(g(src, 'x_studio_employee'))
    if not employee:
        return None
    month = g(src, 'x_studio_mon')
    if month not in MONTH_CODES:
        month = False
    year = g(src, 'x_studio_yea') or False
    batch = False
    bl = g(src, 'x_studio_batch')
    if bl:
        batch = Batch.search([('studio_ref_id', '=', bl.id)], limit=1)
    # ssc.staff.attendance was never mirrored and has no reference column. Its
    # identity is the company, the month and the year; ours says 'JUL' and its
    # says '7', so the month is translated, and where more than one sheet
    # answers the link is left empty rather than guessed.
    sheet = False
    company = employee.company_id
    if month and year and company:
        try:
            number = str(MONTH_CODES.index(month) + 1)
            year_number = int(str(year).strip())
        except (ValueError, TypeError):
            number = year_number = None
        if number and year_number:
            found = StaffSheet.search([('company_id', '=', company.id),
                                       ('month', '=', number), ('year', '=', year_number)])
            sheet = found if len(found) == 1 else False
    return {
        'employee_id': employee.id,
        'batch_id': batch.id if batch else False,
        'staff_attendance_id': sheet.id if sheet else False,
        'month': month,
        'year': year,
        'days': g(src, 'x_studio_days') or 0,
        'is_staff': True,
        'is_cash': False,
        'designation': g(src, 'x_studio_designation') or g(src, 'x_studio_position') or False,
        'basic_salary': g(src, 'x_studio_basic_salary') or 0.0,
        'house_allowance': g(src, 'x_studio_housing_allowance') or 0.0,
        'transport_allowance': g(src, 'x_studio_travelling_allownce') or 0.0,
        'other_allowance': g(src, 'x_studio_other_allowances') or 0.0,
        'gross_salary': g(src, 'x_studio_total_gross_salary') or 0.0,
        'total_attendance': g(src, 'x_studio_total_attended_days_this_month') or 0.0,
        # Staff are paid by the month, not by the punch: no overtime.
        'overtime_reg': 0.0,
        'overtime_off': 0.0,
        'studio_total_salary': g(src, 'x_studio_total_salary_of_this_month') or 0.0,
        'studio_overtime_salary': 0.0,
        'studio_salary_adjustment': g(src, 'x_studio_salary_adjusments') or 0.0,
        'studio_net_amount': g(src, 'x_studio_value') or 0.0,
    }


def sync_attachments(slip, src):
    """test_2's _sync_staff_attachments: the shared-list links are the rows the
    attachment bridge already made, linked; the payslip's own lines are made."""
    if not slip.month:
        return
    existing = {a.name: a for a in slip.attachment_ids}
    for line in (g(src, 'x_studio_salary_attachments') or []):
        mirror = Attachment.search([('studio_ref_id', '=', line.id)], limit=1)
        if mirror and not mirror.payslip_id:
            mirror.write({'payslip_id': slip.id, 'state': 'attached'})
    own = list(g(src, 'x_studio_staff_attach') or []) + list(g(src, 'x_studio_attachments') or [])
    for line in own:
        name = g(line, 'x_name') or 'Attachment'
        if name in existing:
            continue
        value = g(line, 'x_studio_value') or g(line, 'x_studio_amount') or 0.0
        studio_type = g(line, 'x_studio_type_of_attachment') or g(line, 'x_studio_type')
        is_deduction = (
            value < 0
            or (g(line, 'x_studio_factor') or 0) < 0
            or bool(g(line, 'x_studio_advance_link'))
            or bool(g(line, 'x_studio_fine_link'))
        )
        Attachment.create({
            'name': name,
            'employee_id': slip.employee_id.id,
            'type_id': Attachment._resolve_studio_type(studio_type, is_deduction).id,
            'month': slip.month,
            'year': slip.year or False,
            'value': value,
            'payslip_id': slip.id,
            'state': 'attached',
        })


def sync_chunk(studio_records):
    """test_2's _sync_staff_from_studio: one savepoint per record, and the
    failures returned rather than only logged."""
    Mirror = Slip.with_context(tracking_disable=True, mail_create_nolog=True,
                               mail_create_nosubscribe=True)
    failures = []
    for src in studio_records:
        try:
            with cr.savepoint():
                vals = staff_vals(src)
                if not vals:
                    continue
                mirror = Mirror.search([('studio_ref_id', '=', src.id)], limit=1)
                if mirror:
                    mirror.write(vals)
                else:
                    mirror = Mirror.create(dict(vals, studio_ref_id=src.id))
                sync_attachments(mirror, src)
        except Exception as exc:                                # noqa: BLE001
            failures.append((src.id, " ".join(str(exc).split())[:120]))
    return failures
clashes, unresolved = [], []
for record in todo:
    employee = Resolver._resolve_studio_employee(g(record, 'x_studio_employee'))
    if not employee:
        unresolved.append(record)
        continue
    hr = employee.hr_employee_id
    key = (hr.id if hr else 0, str(g(record, 'x_studio_mon') or ''),
           str(g(record, 'x_studio_yea') or ''))
    if key[0] and key in ours:
        clashes.append((record, ours[key]))

# The same person and month in both Studio masters. Two quite different things
# wear that shape, and they are separated here rather than treated alike:
#
#  * ours holds nothing and theirs holds a salary. That is an empty labour
#    record shadowing a real staff one - the payroll was recorded on the staff
#    master and a placeholder was left on the other. The figures go onto the
#    payslip that is already here; one person, one month, one payslip, and the
#    record with the numbers wins over the record with the zeros.
#
#  * both hold a salary and they differ. That is a disagreement between two
#    masters about what somebody was paid, the same shape as the 131 x_to_pay
#    rows, and only the bank statements settle it. Left alone and printed.
#  * theirs holds nothing and ours holds a salary. The mirror image of the
#    first, and not a disagreement about anything: an empty duplicate row on
#    the Studio side of a month already recorded here in full. There is no
#    figure to carry, so nothing is done and nothing is asked.
merges, disputes, empty_source = [], [], []
for record, slip in clashes:
    theirs = g(record, 'x_studio_value') or 0.0
    mine = slip.net_amount or 0.0
    if abs(mine) < 0.01 and abs(theirs) >= 0.01:
        merges.append((record, slip, theirs, mine))
    elif abs(theirs) < 0.01:
        empty_source.append((record, slip, theirs, mine))
    else:
        disputes.append((record, slip, theirs, mine))

if merges:
    print("\n  %s empty payslip(s) here will take the staff figures instead of"
          " a second copy being made:" % len(merges))
    print("      %-8s %-8s %-28s %-10s %-12s %s"
          % ('studio', 'ours', 'employee', 'period', 'staff net', 'ours net'))
    for record, slip, theirs, mine in merges:
        employee = Resolver._resolve_studio_employee(g(record, 'x_studio_employee'))
        print("      %-8s %-8s %-28s %-10s %-12s %s"
              % (record.id, slip.id,
                 (employee.name or '')[:28] if employee else '-',
                 '%s %s' % (g(record, 'x_studio_mon') or '-',
                            g(record, 'x_studio_yea') or '-'),
                 round(theirs, 2), round(mine, 2)))

if empty_source:
    print("")
    print("  %s are empty on the Studio side and already recorded here in full"
          " - nothing to carry:" % len(empty_source))
    for record, slip, _theirs, mine in empty_source:
        employee = Resolver._resolve_studio_employee(g(record, 'x_studio_employee'))
        print("      %-8s %-8s %-28s %s %-8s ours %s"
              % (record.id, slip.id,
                 (employee.name or '')[:28] if employee else '-',
                 g(record, 'x_studio_mon') or '-', g(record, 'x_studio_yea') or '-',
                 round(mine, 2)))

if disputes:
    print("\n  %s hold a salary on both sides and disagree:" % len(disputes))
    for record, slip, theirs, mine in disputes:
        employee = Resolver._resolve_studio_employee(g(record, 'x_studio_employee'))
        print("      %-8s %-8s %-28s staff %-12s ours %s"
              % (record.id, slip.id,
                 (employee.name or '')[:28] if employee else '-',
                 round(theirs, 2), round(mine, 2)))
    print("      Two masters disagreeing about a payment. The bank settles it.")

handled = {record.id for record, _s, _t, _m in merges + disputes + empty_source}
todo = todo.filtered(lambda r: r.id not in handled)
if clashes:
    print("\n  %s left to bring across as new payslips" % len(todo))
else:
    print("  no employee and month here already has a payslip")

if unresolved:
    print("\n  %s name an employee that does not resolve - the mirror skips those:"
          % len(unresolved))
    for record in unresolved[:8]:
        employee = g(record, 'x_studio_employee')
        print("      %-8s %s" % (record.id,
                                 (employee.display_name or '-')[:44] if employee
                                 else '(no employee)'))

no_month = todo.filtered(lambda r: not g(r, 'x_studio_mon'))
if no_month:
    print("\n  %s have no month - they come across, but their attachments "
          "cannot" % len(no_month))

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing imported. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


title("1. merging into the empty payslips")

merged = 0
for record, slip, _theirs, _mine in merges:
    try:
        with cr.savepoint():
            vals = staff_vals(record)
            if not vals:
                continue
            # The reference moves with the figures: this payslip mirrors the
            # staff row now, and saying otherwise would leave a number pointing
            # at a record that does not describe it.
            slip.write(dict(vals, studio_ref_id=record.id))
            sync_attachments(slip, record)
        merged += 1
        print("  > %-8s took the figures from studio %s" % (slip.id, record.id))
    except Exception as exc:
        print("  ! %-8s %s" % (slip.id, str(exc).strip().splitlines()[0][:70]))
cr.commit()
print("  %s merged" % merged)


title("2. importing")

# The mirror handles each row in its own savepoint and hands back the ones that
# raised. Counting a chunk as imported because the call returned is what let
# this print 333 / 333 over a table that gained nothing: every row had failed,
# every failure was logged, and the log was the one thing nobody was reading.
imported, refused = 0, []
for start in range(0, len(todo), CHUNK):
    chunk = todo[start:start + CHUNK]
    try:
        failed = sync_chunk(chunk)
        cr.commit()
        refused += failed or []
        imported += len(chunk) - len(failed or [])
        print("  %s / %s%s" % (imported, len(todo),
                               '   %s refused' % len(refused) if refused else ''))
    except Exception as exc:
        cr.rollback()
        print("  chunk at %s FAILED: %s"
              % (chunk[0].id, str(exc).strip().splitlines()[0][:70]))
        print("  Run again: everything before this chunk is committed.")
        break

if refused:
    print("")
    print("  %s row(s) the mirror could not build, and what each said:"
          % len(refused))
    seen = {}
    for ref_id, message in refused:
        seen.setdefault(message[:90], []).append(ref_id)
    for message, ids in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        print("      %4s row(s)  %s" % (len(ids), message))
        print("                  %s" % (sorted(ids)[:10],))


title("3. after")

done = set(Slip.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
missing = rows.filtered(lambda r: r.id not in done)
staff = Slip.search_count([('is_staff', '=', True), ('studio_ref_id', '!=', False)])
print("  %s of %s now have a mirror" % (len(rows) - len(missing), len(rows)))
print("  %s payslip(s) here are marked staff and carry a reference" % staff)
if missing:
    print("\n  %s still without one:" % len(missing))
    for record in missing[:12]:
        employee = g(record, 'x_studio_employee')
        print("      %-8s %-34s %s %s"
              % (record.id,
                 (employee.display_name or '')[:34] if employee else '(no employee)',
                 g(record, 'x_studio_mon') or '-', g(record, 'x_studio_yea') or '-'))


title("next")
print("""  Compare the money before deleting anything:

      odoo-bin shell --no-http < tools/compare_staff_payslip_money.py""")
