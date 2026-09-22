"""Is every Studio row copied into our model? Ten mirrors, one answer each.

    odoo-bin shell --no-http --shell-interface=python < tools/audit_studio_mirrors.py

Reads only. ssc_payroll keeps a live bridge from ten Studio models: an
automation fires on every create and write, and the record is copied onto ours
with studio_ref_id naming the row it came from. It has worked for months, which
is exactly the reason to check it rather than trust it - an automation that was
switched off for an afternoon, or a record created before the bridge existed,
leaves a gap that nothing complains about.

The gap matters now because the Studio models are going. A row with no mirror is
a row that disappears with the model, and the native module will not have it: not
missing a field, missing the record.

So, for each pair: how many rows on the Studio side, how many of them are named
by a mirror, and which are not. The missing ones are listed with enough of
themselves to be recognised, because "eleven rows are missing" is not something
anybody can act on.
"""
# Studio model -> our model. The list ssc_payroll's hooks actually install.
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
Automation = env.get('base.automation')                          # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def label(record):
    """Something a person can recognise a row by."""
    for name in ('x_name', 'display_name', 'name'):
        if name in record._fields:
            value = record[name]
            if value:
                return str(value)[:44]
    return 'id %s' % record.id


title("1. the bridges")

if Automation is not None:
    rules = Automation.sudo().search([('name', 'like', 'SSC Payroll: mirror')])
    for rule in rules.sorted('name'):
        print("  %-6s %-52s %s" % (rule.id, (rule.name or '')[:52],
                                   'on' if rule.active else 'OFF'))
    print("\n  %s bridge(s), %s switched off"
          % (len(rules), len(rules.filtered(lambda r: not r.active))))


title("2. coverage")

gaps = {}
for source_name, target_name in MIRRORS:
    Source = env.get(source_name)                                # noqa: F821
    Target = env.get(target_name)                                # noqa: F821
    if Source is None:
        print("  %-24s -> %-24s source is not in this database" % (source_name, target_name))
        continue
    if Target is None or 'studio_ref_id' not in Target._fields:
        print("  %-24s -> %-24s target has no studio_ref_id" % (source_name, target_name))
        continue
    Source = Source.sudo().with_context(active_test=False)
    Target = Target.sudo().with_context(active_test=False)

    rows = Source.search([])
    mirrored = set(Target.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
    missing = rows.filtered(lambda r: r.id not in mirrored)
    orphan = mirrored - set(rows.ids)

    flag = 'ok' if not missing else '%s MISSING' % len(missing)
    print("  %-24s -> %-22s %5s row(s)  %5s mirrored  %s"
          % (source_name, target_name, len(rows), len(rows) - len(missing), flag))
    if orphan:
        print("      %s mirror(s) name a Studio row that is no longer there"
              % len(orphan))
    if missing:
        gaps[(source_name, target_name)] = missing


if not gaps:
    title("nothing is missing")
    print("  Every Studio row named above has a record on our side.")
else:
    title("3. the rows with no mirror")
    for (source_name, target_name), missing in gaps.items():
        print("\n  %s -> %s   %s row(s)" % (source_name, target_name, len(missing)))
        for record in missing[:15]:
            active = record.x_active if 'x_active' in record._fields else True
            print("      %-8s %-46s %s"
                  % (record.id, label(record), '' if active else '(archived)'))
        if len(missing) > 15:
            print("      ... and %s more" % (len(missing) - 15))


title("what to do with a gap")
print("""  A missing row is not necessarily a fault: a Studio record that was never
  valid - no employee, no amount - is skipped by the bridge on purpose, and the
  ones listed above will usually turn out to be those.

  What matters is that each one is looked at before its model is deleted, and
  that the looking happens now rather than the week after. Run the module's own
  sync to close a real gap; the bridges are idempotent and safe to re-run.""")
