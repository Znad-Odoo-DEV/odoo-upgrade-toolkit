"""Bring the Studio payslips across, in chunks, so a dropped shell costs a chunk.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/import_studio_payslips.py

Four and a half thousand payslips, each one linking a batch, its attachments and
its project lines, is more work than an Odoo.sh shell will hold open: the last
attempt lost its connection after the first step and the commit went with it.
So this runs in chunks and commits each one. A run that dies has still done
everything before the chunk it died in, and starting again picks up from there -
the mirror finds what is already here by studio_ref_id and writes rather than
creates.

The batches go first, because a payslip's mirror links to its batch and a batch
that is not there yet leaves the link empty.

It is safe to run twice, and it is meant to be: the honest way to move four
thousand records through a connection that drops is to accept that it drops.

Checked before it starts, and the reason it can be run at all: our side holds
189 payslips, all of them AUG-2026, and the Studio master holds eighteen months
ending at JUN-2026. Not one pair of them is the same employee in the same month,
so nothing here is duplicated.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'
CHUNK = int(os.environ.get('SSC_CHUNK') or 200)

SOURCE = 'x_all_payslips'
TARGET = 'ssc.payslip'

cr = env.cr                                                      # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821
Target = env[TARGET].sudo().with_context(active_test=False)      # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def already_here():
    return set(Target.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))


# --- 0. the guard -------------------------------------------------------------

title("0. before anything is created")

rows = Source.search([], order='id')
done = already_here()
todo = rows.filtered(lambda r: r.id not in done)

print("  %s row(s) on the Studio side" % len(rows))
print("  %s already mirrored" % (len(rows) - len(todo)))
print("  %s to bring across" % len(todo))
print("  %s payslip(s) on our side in total" % Target.search_count([]))

# The one thing that must not happen: creating a second payslip for a person and
# a month that already has one. Checked here rather than assumed, every run.
existing = {}
for slip in Target.search([]):
    hr = slip.employee_id.hr_employee_id if slip.employee_id else False
    existing[(hr.id if hr else 0, str(slip.month or ''), str(slip.year or ''))] = slip

clashes = []
for record in todo:
    employee = record.x_studio_employee
    key = (employee.id if employee else 0,
           str(record.x_studio_month or ''), str(record.x_studio_year or ''))
    if key[0] and key in existing:
        clashes.append((record, existing[key]))

if clashes:
    print("\n  STOPPED. %s Studio row(s) name an employee and month we already"
          " have a payslip for:" % len(clashes))
    for record, slip in clashes[:12]:
        print("      studio %-8s ours %-8s %-30s %s %s"
              % (record.id, slip.id, (record.x_studio_employee.display_name or '')[:30],
                 record.x_studio_month, record.x_studio_year))
    raise SystemExit(
        "\nImporting these would make a second copy. Nothing was changed.")

print("  no Studio row names an employee and month we already hold")

no_employee = todo.filtered(lambda r: not r.x_studio_employee)
if no_employee:
    print("  %s row(s) name no employee - the mirror skips those" % len(no_employee))

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing imported. Run again with SSC_WRITE=1.")
    print("  SSC_CHUNK=200 is the commit size.")
    cr.rollback()
    raise SystemExit()


# --- 1. batches first ---------------------------------------------------------

title("1. salary batches")

Batch = env.get('ssc.salary.batch')                              # noqa: F821
Batches = env.get('x_salary_batches')                            # noqa: F821
if Batch is not None and Batches is not None:
    source_batches = Batches.sudo().with_context(active_test=False).search([])
    before = Batch.sudo().with_context(active_test=False).search_count(
        [('studio_ref_id', '!=', False)])
    try:
        Batch.sudo()._sync_from_studio(source_batches)
        cr.commit()
    except Exception as exc:
        cr.rollback()
        print("  FAILED: %s" % str(exc).strip().splitlines()[0][:70])
    after = Batch.sudo().with_context(active_test=False).search_count(
        [('studio_ref_id', '!=', False)])
    print("  %s of %s batch(es) mirrored (%+d)"
          % (after, len(source_batches), after - before))
    print("  A payslip links to its batch, so this had to happen first.")


# --- 2. the payslips, a chunk at a time --------------------------------------

title("2. payslips")

imported = 0
for start in range(0, len(todo), CHUNK):
    chunk = todo[start:start + CHUNK]
    try:
        Target._sync_from_studio(chunk)
        cr.commit()
        imported += len(chunk)
        print("  %s / %s" % (imported, len(todo)))
    except Exception as exc:
        cr.rollback()
        print("  chunk starting at %s FAILED: %s"
              % (chunk[0].id, str(exc).strip().splitlines()[0][:60]))
        print("  Run again: everything before this chunk is committed.")
        break


# --- 3. what came across ------------------------------------------------------

title("3. after")

done = already_here()
missing = rows.filtered(lambda r: r.id not in done)
print("  %s of %s Studio row(s) now have a mirror" % (len(rows) - len(missing), len(rows)))
print("  %s payslip(s) on our side in total" % Target.search_count([]))
if missing:
    print("\n  %s still without one:" % len(missing))
    for record in missing[:12]:
        employee = record.x_studio_employee
        print("      %-8s %-30s %s %s"
              % (record.id, (employee.display_name or '')[:30] if employee else '(no employee)',
                 record.x_studio_month, record.x_studio_year))
    if len(missing) > 12:
        print("      ... and %s more" % (len(missing) - 12))

title("next")
print("""  Compare the money before deleting anything. A payslip that exists on both
  sides and disagrees about the net amount is worse than one that never came
  across, because nothing will tell you it is wrong.""")
