"""The twenty-two attachments that will not come across, and why each one won't.

    odoo-bin shell --no-http --shell-interface=python < tools/diagnose_failed_attachments.py

Reads only. The import declines a record for three quite different reasons and
reports none of them: the employee does not resolve, the type is one of the
three retired on purpose, or the type resolves to a retired one under another
name. Two of those are correct behaviour and one is a fault, and 22 missing
looks identical either way.

So each one is asked the same questions the import asks, in the same order, and
the answer is printed instead of being turned into a skip.

These are money on somebody's payslip - fines, advance deductions, overtime
compensation, a day deducted for a holiday - so the ones that turn out to be a
fault matter, and the ones that turn out to be deliberate are worth being able
to say so about.
"""
SOURCE = 'x_attachments_list'

cr = env.cr                                                      # noqa: F821
Attachment = env['ssc.attachment'].sudo()                        # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def _get(record, name):
    if not record or name not in record._fields:
        return False
    return record[name]


mirrored = set(Attachment.with_context(active_test=False)
               .search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
missing = Source.search([], order='id').filtered(lambda r: r.id not in mirrored)

title("1. asking each one what the import would ask")

retired_types = Attachment._retired_types()
reasons = {}
for record in missing:
    studio_emp = _get(record, 'x_studio_employee')
    employee = Attachment._resolve_studio_employee(studio_emp)
    studio_type = _get(record, 'x_studio_type')
    type_name = _get(studio_type, 'x_name')

    if not studio_emp:
        reason = 'names no employee at all'
    elif not employee:
        reason = 'employee does not resolve to an ssc.employee'
    elif type_name in Attachment._RETIRED_STUDIO_TYPES:
        reason = 'type is retired by name: %s' % type_name
    else:
        is_deduction = (
            (_get(record, 'x_studio_factor') or 0) < 0
            or bool(_get(record, 'x_studio_advance_link'))
            or bool(_get(record, 'x_studio_fine_link'))
        )
        att_type = Attachment._resolve_studio_type(studio_type, is_deduction)
        if att_type in retired_types:
            reason = "type '%s' resolves to a retired one" % (type_name or '-')
        else:
            reason = 'would come across now'
    reasons.setdefault(reason, []).append((record, employee, type_name))

for reason, items in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
    print("\n  %s row(s)  -  %s" % (len(items), reason))
    for record, employee, type_name in items[:10]:
        who = employee.name if employee else (
            (_get(record, 'x_studio_employee').display_name or '-')
            if _get(record, 'x_studio_employee') else '(none)')
        print("      %-8s %-30s %-24s %s %s"
              % (record.id, str(_get(record, 'x_name') or '')[:30],
                 str(who)[:24], _get(record, 'x_studio_month_1') or '',
                 _get(record, 'x_studio_year') or ''))
    if len(items) > 10:
        print("      ... and %s more" % (len(items) - 10))


title("2. the money on them")

total = 0.0
for reason, items in reasons.items():
    amount = sum(abs(_get(r, 'x_studio_value') or 0) for r, _e, _t in items)
    total += amount
    print("  %-52s %s" % (reason[:52], round(amount, 2)))
print("\n  %s in total across %s row(s)" % (round(total, 2), len(missing)))


title("what to do")
print("""  "would come across now" means the import will take it on its next run and
  nothing needs deciding.

  "type is retired" is the module doing what it was told: phone bill, sick leave
  and medical bill reimbursements are not carried. If one of these is money that
  was actually paid, that decision is the thing to revisit, not the import.

  "employee does not resolve" is a fault, and the employee named above is the
  place to start: they exist on hr.employee and not on ssc.employee, or under a
  different name on each.""")
