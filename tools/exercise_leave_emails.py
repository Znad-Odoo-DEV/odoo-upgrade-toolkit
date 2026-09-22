"""The four leave approval emails: which one goes, and what it says."""
from datetime import date

Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
Employee = env['hr.employee']                                     # noqa: F821
User = env['res.users']                                           # noqa: F821
Mail = env['mail.mail']                                           # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-62s %s" % (label, detail))


reviewer = User.create({
    'name': "Reviewer", 'login': 'mailer.test',
    'group_ids': [(6, 0, [
        env.ref('base.group_user').id,                            # noqa: F821
        env.ref('ssc_requests.group_request_pe_review').id,       # noqa: F821
        env.ref('ssc_requests.group_request_hr_review').id,       # noqa: F821
        env.ref('ssc_requests.group_request_approver').id])],     # noqa: F821
})

employee = Employee.create({'name': "Rashid Al Mansoori"})
alr = Type.search([('code', '=', 'ALR')], limit=1)


def a_leave(approval_type):
    record = Request.create({
        'request_type_id': alr.id, 'employee_id': employee.id,
        'description': "Annual leave",
        'approval_type': approval_type,
        'is_paid_leave': True,
        'leave_type': 'overseas',
        'first_day_of_leave': date(2026, 9, 1),
        'last_day_of_leave': date(2026, 9, 30),
        'airport_destination': "Kochi",
        'city_country': "Kochi, India",
        'leave_allowance_amount': 6500.0,
        'leave_salaries_count': 2,
        'ticket_amount': 1450.0,
    })
    record.action_submit()
    while record.state in ('pe_review', 'hr_review'):
        if record.state == 'pe_review':
            record.with_user(reviewer).action_pe_review()
        else:
            record.with_user(reviewer).action_hr_review()
    return record


def mails_for(record):
    return Mail.search([('model', '=', 'ssc.request'),
                        ('res_id', '=', record.id)])


# --- the four templates exist -------------------------------------------------
for key, ref in Request.APPROVAL_TEMPLATES.items():
    template = env.ref(ref, raise_if_not_found=False)             # noqa: F821
    check("the template for %-14s is there" % key, bool(template),
          template.name if template else ref)

# --- each choice sends its own ------------------------------------------------
expected = {
    'ticket': "as per attached quote",
    'reimbursement': "Reimbursement amount for Air",
    'revise': "try to get a better price",
    'none': "Not Approved",
}
for choice, phrase in expected.items():
    record = a_leave(choice)
    record.with_user(reviewer).action_approve()
    mails = mails_for(record)
    check("%-14s sends exactly one email" % choice, len(mails) == 1,
          "%s mail(s)" % len(mails))
    body = mails.body_html or ''
    check("%-14s says the right thing about the ticket" % choice,
          phrase in body,
          phrase if phrase in body else "the phrase is not in the body")

# --- and the shared part is filled in, not left as placeholder text -----------
record = a_leave('ticket')
record.with_user(reviewer).action_approve()
body = mails_for(record).body_html or ''
for what, value in (("the employee's name", "Rashid Al Mansoori"),
                    ("the destination", "Kochi"),
                    ("the leave allowance", "6,500.00"),
                    ("the number of leave salaries", "(2 leave salary)"),
                    ("the ticket amount", "1,450.00")):
    check("the body carries %s" % what, value in body,
          value if value in body else "MISSING - a blank goes out instead")
import re as _re
print("   the money reads:  %s"
      % " | ".join(_re.findall(r'[\d,]+\.\d\d[^<]{0,6}', body)[:3]))
check("and no placeholder text survived",
      'Employee Name</t>' not in body and 'Total Amount</t>' not in body,
      "clean")
check("the subject is the request number",
      mails_for(record).subject == record.name,
      mails_for(record).subject)

# --- it is sent once ----------------------------------------------------------
# An approved request cannot go back to draft - that is the model's own rule
# and a good one. So the second send is provoked the way a script or a repair
# would: by calling the producer again on an approved record.
before = len(mails_for(record))
record._on_approved()
check("running the approval again sends accounts no second instruction",
      len(mails_for(record)) == before, len(mails_for(record)))
check("because the record remembers that it went",
      record.approval_email_sent is True, record.approval_email_sent)

# --- nothing is guessed --------------------------------------------------------
silent = a_leave(False)
silent.with_user(reviewer).action_approve()
check("with nobody saying what was approved, no email is guessed at",
      not mails_for(silent), len(mails_for(silent)))
check("and the request is still approved", silent.state == 'approved',
      silent.state)

# --- another kind of request sends none of them --------------------------------
mr = Type.search([('code', '=', 'MR')], limit=1)
project = env['project.project'].create({'name': "A job"})        # noqa: F821
material = Request.create({'request_type_id': mr.id,
                           'project_id': project.id,
                           'description': "Cement"})
material.action_submit()
while material.state in ('pe_review', 'hr_review'):
    if material.state == 'pe_review':
        material.with_user(reviewer).action_pe_review()
    else:
        material.with_user(reviewer).action_hr_review()
material.with_user(reviewer).action_approve()
check("a material request sends no leave email", not mails_for(material),
      len(mails_for(material)))

print()
print("PASS  %s" % len(ok))
for line in ok:
    print("   ok   %s" % line)
if bad:
    print()
    print("FAIL  %s" % len(bad))
    for line in bad:
        print("   XX   %s" % line)
else:
    print()
    print("nothing failed")

env.cr.rollback()                                                  # noqa: F821
print("rolled back")
