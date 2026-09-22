"""The advance confirmation: carried from a template that lives only on the database."""
from datetime import date

Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
User = env['res.users']                                           # noqa: F821
Employee = env['hr.employee']                                     # noqa: F821
Mail = env['mail.mail']                                           # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-64s %s" % (label, detail))


def groups(*refs):
    return [(6, 0, [env.ref(ref).id for ref in refs])]            # noqa: F821


# The approver is deliberately NOT in HR. The advance email prints a passport
# number, which is behind hr.group_hr_user, and a template renders the record
# it is about - so this is the arrangement that raised an AccessError the
# first time a project manager approved a leave.
approver = User.create({
    'name': "A Project Manager", 'login': 'adv.pm',
    'group_ids': groups('base.group_user',
                        'ssc_requests.group_request_user',
                        'ssc_requests.group_request_pe_review',
                        'ssc_requests.group_request_hr_review',
                        'ssc_requests.group_request_approver'),
})
check("the approver is not in HR", not approver.has_group('hr.group_hr_user'),
      "not HR")

employee = Employee.create({
    'name': "Ragesh Peethambaran",
    'passport_id': "P1234567",
})

asr = Type.search([('code', '=', 'ASR')], limit=1)


def an_advance(**values):
    record = Request.create(dict({
        'request_type_id': asr.id, 'employee_id': employee.id,
        'description': "Advance against salary",
        'amount': 2500.0,
        'advance_reason': "School fees",
        'repayment_method': 'salary',
        'installment_ids': [
            (0, 0, {'name': "1 of 5", 'due_date': date(2026, 10, 1),
                    'amount': 500.0}),
            (0, 0, {'name': "5 of 5", 'due_date': date(2027, 2, 1),
                    'amount': 2000.0}),
        ],
    }, **values))
    record.action_submit()
    while record.state in ('pe_review', 'hr_review'):
        if record.state == 'pe_review':
            record.with_user(approver).action_pe_review()
        else:
            record.with_user(approver).action_hr_review()
    return record


def mails_for(record):
    return Mail.search([('model', '=', 'ssc.request'),
                        ('res_id', '=', record.id)])


advance = an_advance()
advance.with_user(approver).action_approve()

mails = mails_for(advance)
check("approving an advance sends exactly one email", len(mails) == 1,
      "%s mail(s)" % len(mails))
check("and it did not raise on the passport the approver cannot read",
      advance.state == 'approved', advance.state)

body = mails.body_html or ''
for what, text in (("the employee", "Ragesh Peethambaran"),
                   ("the passport, which is why it is sent as the system",
                    "P1234567"),
                   ("the amount", "2,500.00"),
                   ("the reason", "School fees"),
                   ("the installment count", "2 Installments"),
                   ("the repayment summary", "installment(s)"),
                   ("the date it is repaid by", "2027-02-01"),
                   ("and who signs it", "Mohammad Adnan Salma")):
    check("the advance email carries %s" % what, text in body,
          text if text in body else "MISSING - it goes to accounts like this")

check("no placeholder text survived",
      'Employee Name</t>' not in body and 'Amount</t>' not in body, "clean")
check("the subject is the request number", mails.subject == advance.name,
      mails.subject)

# --- it goes once ------------------------------------------------------------
before = len(mails_for(advance))
advance._on_approved()
check("running the approval again sends accounts no second instruction",
      len(mails_for(advance)) == before, len(mails_for(advance)))

# --- and a leave request is untouched by any of this -------------------------
alr = Type.search([('code', '=', 'ALR')], limit=1)
leave = Request.create({'request_type_id': alr.id, 'employee_id': employee.id,
                        'description': "Annual leave"})
check("an advance email is not sent for a leave request",
      leave._send_advance_email() is False, "not sent")

# --- the personal address is carried, and visible ----------------------------
template = env.ref(                                               # noqa: F821
    'ssc_requests_payroll.mail_template_advance_approved')
check("the CC still carries what Studio's did, personal address and all",
      'basselaroud@yahoo.com' in (template.email_cc or ''),
      "carried, and flagged in the file for somebody to decide on")

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
