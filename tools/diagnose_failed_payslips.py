"""Why did 385 payslips not come across? Ask each one and print what it says.

    odoo-bin shell --no-http --shell-interface=python < tools/diagnose_failed_payslips.py

Reads only - every attempt is made inside a savepoint that is rolled back, so
nothing is created here whatever the outcome.

_sync_from_studio catches per record and logs, which is right for an automation
firing on somebody's save and useless for finding out what is wrong with three
hundred and eighty-five of them. This does what the mirror does, one row at a
time, and keeps the exception instead of writing it to a file nobody will read.

The errors are grouped, because three hundred failures are rarely three hundred
problems: it is usually two, and the value of the grouping is that it says which
two.
"""
SOURCE = 'x_all_payslips'
TARGET = 'ssc.payslip'
LIMIT = 400

cr = env.cr                                                      # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821
Target = env[TARGET].sudo().with_context(active_test=False)      # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


mirrored = set(Target.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
missing = Source.search([], order='id').filtered(lambda r: r.id not in mirrored)

title("1. what is missing")

no_employee = missing.filtered(lambda r: not r.x_studio_employee)
real = missing - no_employee
print("  %s row(s) with no mirror" % len(missing))
print("      %s name no employee - the mirror skips those by design" % len(no_employee))
print("      %s name one and still did not come across" % len(real))

months = {}
for record in real:
    key = '%s %s' % (record.x_studio_month, record.x_studio_year)
    months[key] = months.get(key, 0) + 1
print("\n  by month:")
for month, count in sorted(months.items(), key=lambda kv: -kv[1]):
    print("      %-14s %s" % (month, count))


title("2. asking each one")

Slip = Target.with_context(tracking_disable=True, mail_create_nolog=True,
                           mail_create_nosubscribe=True)
errors, no_vals = {}, []
for record in real[:LIMIT]:
    try:
        with cr.savepoint():
            vals = Slip._studio_payslip_vals(record)
            if not vals:
                no_vals.append(record)
                raise ValueError('_rollback_')
            slip = Slip.create(dict(vals, studio_ref_id=record.id))
            Slip._sync_payslip_attachments(slip, record)
            Slip._sync_payslip_projects(slip, record)
            # Everything worked. Undo it anyway: this reads, it does not import.
            raise ValueError('_rollback_')
    except ValueError as exc:
        if str(exc) != '_rollback_':
            errors.setdefault(str(exc).strip().splitlines()[0][:90], []).append(record)
    except Exception as exc:
        line = '%s: %s' % (type(exc).__name__,
                           str(exc).strip().splitlines()[0][:80])
        errors.setdefault(line, []).append(record)

worked = len(real[:LIMIT]) - len(no_vals) - sum(len(v) for v in errors.values())
print("  %s tried" % len(real[:LIMIT]))
print("      %s would have worked just now" % worked)
print("      %s produced no values - the mirror declines them" % len(no_vals))
print("      %s raised" % sum(len(v) for v in errors.values()))

if errors:
    title("3. what they raised")
    for message, records in sorted(errors.items(), key=lambda kv: -len(kv[1])):
        print("\n  %s row(s)" % len(records))
        print("      %s" % message)
        for record in records[:5]:
            employee = record.x_studio_employee
            print("        %-8s %-30s %s %s"
                  % (record.id, (employee.display_name or '')[:30] if employee else '-',
                     record.x_studio_month, record.x_studio_year))

if no_vals:
    title("4. the ones the mirror declines")
    print("  _studio_payslip_vals returned nothing for these. Read that method to")
    print("  see what it requires; usually a missing employee, batch or amount.")
    for record in no_vals[:12]:
        employee = record.x_studio_employee
        batch = record.x_studio_batch if 'x_studio_batch' in record._fields else False
        print("      %-8s %-28s %s %s  batch=%s"
              % (record.id, (employee.display_name or '')[:28] if employee else '-',
                 record.x_studio_month, record.x_studio_year,
                 batch.display_name[:20] if batch else '-'))
    if len(no_vals) > 12:
        print("      ... and %s more" % (len(no_vals) - 12))

cr.rollback()

title("nothing was created")
print("""  Every attempt above was rolled back. If a large number "would have worked
  just now", the failure was transient - a lock, or an order of operations
  during the import - and running the importer again brings them across.""")
