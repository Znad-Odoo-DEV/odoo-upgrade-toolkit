"""Carry the Studio "To Pay" payslips into ssc.payslip before x_to_pay is deleted.

    cd ~/src/user
    odoo-bin shell --no-http --shell-interface=python < tools/import_to_pay_payslips.py
    SSC_WRITE=1 ...   import. Without it, the plan only.

x_to_pay holds the payslips of January to July 2026 - 1,591 on production on
2026-09-05 - and nothing native holds them: hr.payslip starts in August, and
ssc.payslip, which mirrors x_all_payslips, never mirrored these. Deleting the
model would delete seven months of payslips the business can still be asked
about. So they cross first, through the bridge that already exists.

The bridge is ssc.payslip._sync_from_studio, written for x_all_payslips. x_to_pay
carries 22 of the 25 fields it reads under the same names; the employee link is
the one that differs (x_studio_for_employee rather than x_studio_employee), and
the three it lacks (net amount, salary attachments, staff flag) the bridge reads
as empty. So each record is handed over wearing the name the bridge expects,
and everything else passes straight through: same values, same resolution of
employee, batch and attendance sheet by their Studio references, same savepoint
per record.

Two things decided here rather than by the bridge:

  * a Studio payslip whose employee and month already have a native payslip is
    NOT imported - it is listed. 63 of them on production. Two payslips for one
    person and month would be worse than one.
  * the Studio id goes into studio_ref_id, as the bridge always did. x_to_pay
    ids and x_all_payslips ids do not overlap on this database (the probe found
    none of the 1,591 claimed), so nothing already mirrored is overwritten; the
    plan checks that again and refuses if it is no longer true.

This must run BEFORE tools/drop_studio_models.py takes the attendance models:
the bridge resolves the attendance sheet through x_studio_attendance_sheet, a
column on x_to_pay that points at x_attendance_per_month and goes with it.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'
CHUNK = 200

env = env(context=dict(env.context, active_test=False))          # noqa: F821
cr = env.cr
Slip = env['ssc.payslip'].sudo()
ToPay = env.get('x_to_pay')


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


if ToPay is None:
    print("  x_to_pay is not in this database. Nothing to import.")
    raise SystemExit()

ALIAS = {'x_studio_employee': 'x_studio_for_employee'}


class WearingTheBridgeNames:
    """An x_to_pay record answering to the field names the bridge reads.

    studio_get looks the name up in ``_fields`` and then reads it with
    ``record[name]``; both go through here, and the alias is applied to both.
    Everything else - id, truthiness - is the record's own.
    """

    def __init__(self, record):
        self._record = record
        self._fields = dict(record._fields)
        for wanted, actual in ALIAS.items():
            if actual in record._fields:
                self._fields[wanted] = record._fields[actual]

    def __getitem__(self, name):
        return self._record[ALIAS.get(name, name)]

    def __getattr__(self, name):
        return getattr(self._record, ALIAS.get(name, name))

    def __bool__(self):
        return bool(self._record)


# --- 1. the plan -------------------------------------------------------------

title("1. what would cross")

records = ToPay.sudo().search([], order='id')
print("  %s x_to_pay record(s)" % len(records))

for wanted, actual in ALIAS.items():
    print("  %-24s read as %-24s %s" % (wanted, actual,
                                        'present' if actual in ToPay._fields else 'MISSING'))
for name in ('x_studio_net_amount', 'x_studio_salary_attachments', 'x_studio_staff_1',
             'x_studio_projectsss_sum'):
    print("  %-40s %s" % (name, 'present' if name in ToPay._fields else 'absent - read as empty'))

cr.execute("SELECT studio_ref_id FROM ssc_payslip WHERE studio_ref_id IS NOT NULL")
taken = {row[0] for row in cr.fetchall()}
collisions = [r.id for r in records if r.id in taken]
if collisions:
    print("\n  !! %s x_to_pay id(s) already appear in ssc_payslip.studio_ref_id: %s"
          % (len(collisions), collisions[:10]))
    print("  Importing would write over those mirrors. Refusing.")
    cr.rollback()
    raise SystemExit()
print("  no x_to_pay id collides with an existing studio_ref_id")

native = {}
cr.execute("SELECT employee_id, month, year, id FROM ssc_payslip WHERE employee_id IS NOT NULL")
for employee_id, month, year, slip_id in cr.fetchall():
    native.setdefault((employee_id, month or None, str(year) if year else None), []).append(slip_id)

plan, no_employee, duplicate, bad_month = [], [], [], []
by_month = {}
for record in records:
    src = WearingTheBridgeNames(record)
    employee = Slip._resolve_studio_employee(src)
    if not employee:
        no_employee.append(record)
        continue
    month = record.x_studio_month if 'x_studio_month' in ToPay._fields else False
    year = record.x_studio_year if 'x_studio_year' in ToPay._fields else False
    if month not in dict(Slip._fields['month'].selection):
        bad_month.append((record, month))
        month = False
    if native.get((employee.id, month or None, str(year) if year else None)):
        duplicate.append((record, employee, month, year))
        continue
    plan.append(record)
    by_month[(year, month)] = by_month.get((year, month), 0) + 1

print("\n  %s to import" % len(plan))
for (year, month), count in sorted(by_month.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
    print("      %-6s %-4s %s" % (year, month, count))

if bad_month:
    print("\n  %s with a month the native selection does not know (imported without a month):"
          % len(bad_month))
    for record, month in bad_month[:10]:
        print("      id=%-7s %-50s month=%r" % (record.id, (record.x_name or '')[:50], month))

print("\n  %s left out: employee and month already have a native payslip" % len(duplicate))
for record, employee, month, year in duplicate[:15]:
    print("      id=%-7s %-44s -> ssc.employee %s  %s %s"
          % (record.id, (record.x_name or '')[:44], employee.id, month, year))
if len(duplicate) > 15:
    print("      ... and %s more" % (len(duplicate) - 15))

print("\n  %s with no employee the bridge can resolve - NOT imported, would be lost:"
      % len(no_employee))
for record in no_employee[:20]:
    emp = record.x_studio_for_employee if 'x_studio_for_employee' in ToPay._fields else False
    print("      id=%-7s %-50s employee=%s" % (record.id, (record.x_name or '')[:50],
                                                (emp.display_name if emp else '-')))
if len(no_employee) > 20:
    print("      ... and %s more" % (len(no_employee) - 20))

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 2. import ----------------------------------------------------------------

title("2. importing, %s at a time" % CHUNK)
done = 0
for start in range(0, len(plan), CHUNK):
    chunk = plan[start:start + CHUNK]
    Slip._sync_from_studio([WearingTheBridgeNames(r) for r in chunk])
    cr.commit()
    done += len(chunk)
    print("  %s / %s handed to the bridge" % (done, len(plan)))

cr.execute("SELECT count(*) FROM ssc_payslip WHERE studio_ref_id = ANY(%s)",
           ([r.id for r in plan],))
landed = cr.fetchone()[0]
print("\n  %s of %s now have an ssc.payslip carrying their Studio id" % (landed, len(plan)))
if landed < len(plan):
    print("  The bridge logs each failure at ERROR level in the Odoo log (grep 'payslip mirror failed').")
    cr.execute("SELECT id FROM x_to_pay WHERE id = ANY(%s) AND id NOT IN "
               "(SELECT studio_ref_id FROM ssc_payslip WHERE studio_ref_id IS NOT NULL)",
               ([r.id for r in plan],))
    missing = [row[0] for row in cr.fetchall()]
    print("  not landed: %s%s" % (missing[:30], ' ...' if len(missing) > 30 else ''))

title("summary")
print("""  Re-run tools/probe_studio_payroll_mirror.py: x_to_pay should now read
  'unclaimed' only for the duplicates and the unresolved listed above.""")
