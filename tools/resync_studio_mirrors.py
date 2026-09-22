"""Run each Studio mirror again, one at a time, and say out loud what fails.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/resync_studio_mirrors.py

The install ran every migration step inside one try. Something in the middle of
it raised, and the steps behind it never ran: attendance sheets and salary
batches half imported, no payslips at all, and no automation for either. The log
said "master-data migration failed" and nothing else, which is how a database
ends up with four and a half thousand payslips that exist in one place only.

This runs the same steps with a try each, prints the traceback where there is
one, and counts the rows on both sides before and after so the result is a
number rather than an assurance. Every step is create-or-update keyed on
studio_ref_id, so running it twice creates nothing twice.

The payslips are the reason it exists. They are also the largest step by a long
way, and the one whose figures matter most, so they are counted separately and
the money is compared afterwards.
"""
import os
import traceback

DRY_RUN = os.environ.get('SSC_WRITE') != '1'
ONLY = os.environ.get('SSC_ONLY') or ''

MIRRORS = [
    ('x_employeeslist', 'ssc.employee'),
    ('x_advance_salaries', 'ssc.advance'),
    ('x_staff_loan', 'ssc.staff.loan'),
    ('x_leave_expenses', 'ssc.leave.expense'),
    ('x_fines_deductions', 'ssc.fine'),
    ('x_end_of_service', 'ssc.end.of.service'),
    ('x_on_hold_amounts', 'ssc.on.hold'),
    ('x_attendance_per_month', 'ssc.attendance.sheet'),
    ('x_salary_batches', 'ssc.salary.batch'),
    ('x_all_payslips', 'ssc.payslip'),
    ('x_attachments_list', 'ssc.attachment'),
]

cr = env.cr                                                      # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def coverage():
    """How many Studio rows have a mirror, per pair."""
    result = {}
    for source_name, target_name in MIRRORS:
        Source = env.get(source_name)                            # noqa: F821
        Target = env.get(target_name)                            # noqa: F821
        if Source is None or Target is None or 'studio_ref_id' not in Target._fields:
            continue
        rows = Source.sudo().with_context(active_test=False).search([])
        mirrored = set(Target.sudo().with_context(active_test=False)
                       .search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
        result[source_name] = (len(rows), len(set(rows.ids) & mirrored))
    return result


from odoo.addons.ssc_payroll import hooks                        # noqa: E402

STEPS = [
    ('employees', hooks.resync_studio_employees, hooks.ensure_studio_employee_automation),
    ('advances', hooks.resync_studio_advances, hooks.ensure_studio_advance_automation),
    ('loans', hooks.resync_studio_loans, hooks.ensure_studio_loan_automation),
    ('leaves', hooks.resync_studio_leaves, hooks.ensure_studio_leave_automation),
    ('fines', hooks.resync_studio_fines, hooks.ensure_studio_fine_automation),
    ('end of service', hooks.resync_studio_eos, hooks.ensure_studio_eos_automation),
    ('on hold', hooks.resync_studio_holds, hooks.ensure_studio_hold_automation),
    ('attendance sheets', hooks.resync_studio_sheets, hooks.ensure_studio_sheet_automation),
    # batches before payslips: the payslip mirror links to its batch
    ('salary batches', hooks.resync_studio_batches, hooks.ensure_studio_batch_automation),
    ('payslips', hooks.resync_studio_payslips, hooks.ensure_studio_payslip_automation),
]


title("1. before")

before = coverage()
for source_name, (rows, mirrored) in before.items():
    gap = rows - mirrored
    print("  %-24s %5s row(s)  %5s mirrored  %s"
          % (source_name, rows, mirrored, '' if not gap else '%s missing' % gap))

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing synced. Run again with SSC_WRITE=1.")
    print("  SSC_ONLY=payslips runs one step by itself.")
    cr.rollback()
    raise SystemExit()


# --- run ----------------------------------------------------------------------

title("2. running")

failed = []
for label, resync, ensure in STEPS:
    if ONLY and ONLY.lower() not in label.lower():
        continue
    print("\n  --- %s" % label)
    for fn in (resync, ensure):
        try:
            fn(env)                                              # noqa: F821
            cr.commit()
            print("      %s ok" % fn.__name__)
        except Exception:
            cr.rollback()
            failed.append((label, fn.__name__))
            print("      %s FAILED" % fn.__name__)
            for line in traceback.format_exc().strip().splitlines()[-6:]:
                print("        %s" % line)

if not ONLY or 'attach' in ONLY.lower():
    print("\n  --- attachments")
    try:
        env['ssc.attachment']._cron_sync_studio_attachments()    # noqa: F821
        cr.commit()
        print("      ok")
    except Exception:
        cr.rollback()
        failed.append(('attachments', '_cron_sync_studio_attachments'))
        print("      FAILED")
        for line in traceback.format_exc().strip().splitlines()[-6:]:
            print("        %s" % line)


# --- after --------------------------------------------------------------------

title("3. after")

after = coverage()
for source_name, (rows, mirrored) in after.items():
    was = before.get(source_name, (0, 0))[1]
    gain = mirrored - was
    gap = rows - mirrored
    print("  %-24s %5s row(s)  %5s mirrored  %-12s %s"
          % (source_name, rows, mirrored,
             '+%s' % gain if gain else '',
             '' if not gap else '%s STILL MISSING' % gap))

title("summary")
if failed:
    print("  %s step(s) failed:" % len(failed))
    for label, name in failed:
        print("      %-20s %s" % (label, name))
    print("\n  The others ran. A failure here is a data problem in one model, not")
    print("  a reason the rest should not have happened.")
else:
    print("  every step ran")
print("""
  Next, before deleting anything: compare the money. A payslip that exists on
  both sides and disagrees about the net amount is worse than one that is
  missing, because nothing will tell you.""")
