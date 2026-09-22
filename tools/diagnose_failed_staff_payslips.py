"""Why did 338 staff payslips not come across? Ask each one and print the answer.

    odoo-bin shell --no-http --shell-interface=python < tools/diagnose_failed_staff_payslips.py

Reads only - every attempt is made inside a savepoint that is rolled back, so
nothing is created here whatever the outcome.

Seven crossed and three hundred and thirty-eight did not, and most of them will
not be in the log: when the employee does not resolve the mirror gets no values
back and moves on without raising, which is right for an automation firing on
somebody's save and useless for finding out what is wrong with three hundred of
them.

So each row is asked the questions the mirror asks, in order, and the answer is
printed instead of becoming a skip: does it name an employee, does that employee
resolve to an ssc.employee, and if it does, what does creating the payslip say.
"""
SOURCE = 'x_staff_payslips'

cr = env.cr                                                      # noqa: F821
Slip = env['ssc.payslip'].sudo().with_context(active_test=False)  # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821
Resolver = env['ssc.attachment'].sudo()                          # noqa: F821
Emp = env['ssc.employee'].sudo().with_context(active_test=False)  # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def g(record, name):
    if not record or name not in record._fields:
        return False
    return record[name]


mirrored = set(Slip.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
missing = Source.search([], order='id').filtered(lambda r: r.id not in mirrored)

title("1. where each one stops")

reasons = {}
samples = {}
for record in missing:
    studio_emp = g(record, 'x_studio_employee')
    if not studio_emp:
        reason = 'names no employee'
    else:
        employee = Resolver._resolve_studio_employee(studio_emp)
        if not employee:
            reason = 'employee does not resolve to an ssc.employee'
        else:
            try:
                with cr.savepoint():
                    vals = Slip._studio_staff_payslip_vals(record)
                    if not vals:
                        raise ValueError('_no_vals_')
                    Slip.create(dict(vals, studio_ref_id=record.id))
                    raise ValueError('_rollback_')
            except ValueError as exc:
                reason = ('the mirror declines it' if str(exc) == '_no_vals_'
                          else 'would come across now')
            except Exception as exc:
                reason = '%s: %s' % (type(exc).__name__,
                                     str(exc).strip().splitlines()[0][:70])
    reasons[reason] = reasons.get(reason, 0) + 1
    samples.setdefault(reason, []).append(record)

for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
    print("\n  %s row(s)  -  %s" % (count, reason))
    for record in samples[reason][:6]:
        employee = g(record, 'x_studio_employee')
        print("      %-8s %-34s %s %s"
              % (record.id,
                 (employee.display_name or '')[:34] if employee else '(none)',
                 g(record, 'x_studio_mon') or '-', g(record, 'x_studio_yea') or '-'))


title("2. the employees that will not resolve")

unresolved = {}
for record in missing:
    studio_emp = g(record, 'x_studio_employee')
    if not studio_emp or Resolver._resolve_studio_employee(studio_emp):
        continue
    unresolved.setdefault(studio_emp, []).append(record)

print("  %s distinct employee(s)" % len(unresolved))
for studio_emp, records in sorted(unresolved.items(),
                                  key=lambda kv: -len(kv[1]))[:15]:
    code = g(studio_emp, 'x_studio_employee_id')
    badge = g(studio_emp, 'x_studio_attendance_id')
    name = g(studio_emp, 'x_name')
    by_name = Emp.search([('name', '=', name)], limit=1) if name else Emp.browse()
    by_code = Emp.search([('employee_code', '=', code)], limit=1) if code else Emp.browse()
    print("\n  %-36s %s payslip(s)" % (str(name or '-')[:36], len(records)))
    print("      model            %s (%s)" % (studio_emp._name, studio_emp.id))
    print("      employee code    %-20s ssc.employee by code: %s"
          % (code or '-', by_code.id or 'none'))
    print("      attendance id    %s" % (badge or '-'))
    print("      ssc.employee by name                       %s" % (by_name.id or 'none'))


title("what to read")
print("""  "would come across now" means the import will take it on its next run.

  "employee does not resolve" is the whole of it if the count matches, and
  section 2 says why: the resolver looks for an ssc.employee by code, then by
  badge, then by name, and these are the values it was looking with.""")
