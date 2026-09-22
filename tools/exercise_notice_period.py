"""A month's notice, or the resignation does not go."""
from datetime import date, timedelta

Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
Employee = env['hr.employee']                                     # noqa: F821
UserError = odoo.exceptions.UserError                             # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-66s %s" % (label, detail))


today = date.today()
res = Type.search([('code', '=', 'RES')], limit=1)
alr = Type.search([('code', '=', 'ALR')], limit=1)

employee = Employee.create({'name': "Leaving Soon",
                            'visa_expire': today + timedelta(days=45)})


def a_resignation(**values):
    return Request.create(dict(
        {'request_type_id': res.id, 'employee_id': employee.id,
         'description': "Notice of resigning"}, **values))


def refuses(record):
    try:
        record.action_submit()
        return None
    except UserError as error:
        return str(error)


# --- a resignation measured to its end of service ---------------------------
good = a_resignation(leaving_reason='resign',
                     end_of_service_date=today + timedelta(days=40))
check("forty days is measured as forty", good.notice_days == 40,
      good.notice_days)
check("and it is not short notice", not good.notice_is_short,
      good.notice_is_short)
check("it is measured to the end of service date",
      good.notice_deadline == today + timedelta(days=40), good.notice_deadline)
check("so it submits", refuses(good) is None, good.state)

short = a_resignation(leaving_reason='resign',
                      end_of_service_date=today + timedelta(days=10))
check("ten days is short notice", short.notice_is_short, short.notice_days)
message = refuses(short)
check("and it is refused at submission", message is not None, "refused")
check("the message says how many days were given",
      message and "10 day(s)" in message, (message or '')[:70])
check("and the date it was measured to",
      message and str(today + timedelta(days=10)) in message, "named")
check("the request is still a draft, not half submitted",
      short.state == 'draft', short.state)

# --- exactly thirty is enough -----------------------------------------------
exact = a_resignation(leaving_reason='resign',
                      end_of_service_date=today + timedelta(days=30))
check("thirty days exactly is enough", not exact.notice_is_short,
      exact.notice_days)

# --- a non-renewal is measured to the visa ----------------------------------
renewal = a_resignation(leaving_reason='no_renew')
check("a non-renewal measures to the employee's visa expiry",
      renewal.notice_deadline == today + timedelta(days=45),
      renewal.notice_deadline)
check("forty-five days is enough", not renewal.notice_is_short,
      renewal.notice_days)

soon = Employee.create({'name': "Visa Ending",
                        'visa_expire': today + timedelta(days=5)})
renewal_short = a_resignation(leaving_reason='no_renew', employee_id=soon.id)
check("a visa five days out is short notice", renewal_short.notice_is_short,
      renewal_short.notice_days)
check("and refused", refuses(renewal_short) is not None, "refused")

# --- no date at all is short notice, not silence ----------------------------
undated = a_resignation(leaving_reason='resign')
check("no date to measure to reads as short notice, not as adequate",
      undated.notice_is_short, "short")
message = refuses(undated)
check("and the message says which date is missing",
      message and "end of service" in message.lower(), (message or '')[:70])

nameless = a_resignation()
message = refuses(nameless)
check("not saying how somebody is leaving is refused first",
      message and "resignation or a non-renewal" in message,
      (message or '')[:70])

# --- and none of this touches any other kind of request ---------------------
leave = Request.create({'request_type_id': alr.id, 'employee_id': employee.id,
                        'description': "Annual leave"})
check("a leave request is never short notice", not leave.notice_is_short,
      leave.notice_is_short)
check("and submits without a word about it", refuses(leave) is None,
      leave.state)

# --- the banner is on the form, not in the database -------------------------
check("no HTML is stored for the warning",
      'notice_html' not in Request._fields
      and Request._fields['notice_days'].type == 'integer',
      "the database holds the number")

try:
    Request.get_view(
        env.ref('ssc_requests.view_ssc_request_form').id, 'form')  # noqa: F821
    check("the request form still opens", True, "")
except Exception as error:
    check("the request form still opens", False, str(error)[:60])

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
