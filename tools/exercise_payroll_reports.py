"""The advance page and the resignation letter print what is on the request."""
from datetime import date

Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
User = env['res.users']                                           # noqa: F821
Employee = env['hr.employee']                                     # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-64s %s" % (label, detail))


def rendered(report, record):
    html = report._render_qweb_html(report.report_name, record.ids)[0]
    return html.decode() if isinstance(html, bytes) else html


approver = User.create({
    'name': "Mohammad Adnan Salma", 'login': 'rep.approver',
    'group_ids': [(6, 0, [
        env.ref('base.group_user').id,                            # noqa: F821
        env.ref('ssc_requests.group_request_user').id,            # noqa: F821
        env.ref('ssc_requests.group_request_pe_review').id,       # noqa: F821
        env.ref('ssc_requests.group_request_hr_review').id,       # noqa: F821
        env.ref('ssc_requests.group_request_approver').id])],
})
employee = Employee.create({'name': "Ragesh Peethambaran"})

# ============================================================== the advance ===
asr = Type.search([('code', '=', 'ASR')], limit=1)
advance = Request.create({
    'request_type_id': asr.id,
    'employee_id': employee.id,
    'description': "Advance against salary",
    'amount': 2500.0,
    'advance_reason': "School fees",
    'supporting_notes': "Agreed with the project manager.",
    'repayment_method': 'salary',
    'installment_ids': [
        (0, 0, {'name': "1 of 5", 'due_date': date(2025, 10, 1), 'amount': 500.0}),
        (0, 0, {'name': "2 of 5", 'due_date': date(2025, 11, 1), 'amount': 500.0}),
        (0, 0, {'name': "3 of 5", 'due_date': date(2025, 12, 1), 'amount': 500.0}),
        (0, 0, {'name': "4 of 5", 'due_date': date(2026, 1, 1), 'amount': 500.0}),
        (0, 0, {'name': "5 of 5", 'due_date': date(2026, 2, 1), 'amount': 500.0}),
    ],
})

# --- the three prose columns Studio typed are read off the schedule ----------
check("the repayment summary is composed, not typed",
      "5 installment(s)" in (advance.repayment_summary or ''),
      advance.repayment_summary)
check("it names the month it starts",
      "October 2025" in (advance.repayment_summary or ''), "October 2025")
check("and the month it ends",
      "February 2026" in (advance.repayment_summary or ''), "February 2026")
check("received in full by is the last installment's date",
      advance.repaid_in_full_by == date(2026, 2, 1), advance.repaid_in_full_by)
check("the amount is spelled without anybody typing it",
      "Thousand" in (advance.amount_in_words or ''), advance.amount_in_words)

# --- and they follow the schedule when it changes ----------------------------
advance.installment_ids[-1].due_date = date(2026, 4, 1)
check("moving an installment moves the date the page prints",
      advance.repaid_in_full_by == date(2026, 4, 1), advance.repaid_in_full_by)
advance.installment_ids[-1].due_date = date(2026, 2, 1)

report = env.ref('ssc_requests_payroll.action_report_request_advance')  # noqa: F821
html = rendered(report, advance)
check("the advance page renders", bool(html), "%s characters" % len(html))
for what, text in (("the heading it should have had all along",
                    "Advance Against Salary"),
                   ("the employee", "Ragesh Peethambaran"),
                   ("the reason", "School fees"),
                   ("the supporting notes", "Agreed with the project manager"),
                   ("the amount", "2,500.00"),
                   ("the amount in words", "Thousand"),
                   ("the schedule's first row", "1 of 5"),
                   ("the schedule's last row", "5 of 5")):
    check("the advance page carries %s" % what, text in html,
          text if text in html else "MISSING - a blank goes out")
check("and it no longer calls itself a material request",
      "Material Request" not in html,
      "corrected" if "Material Request" not in html else "still says MR")

# --- an advance with no schedule says so rather than printing a blank --------
bare = Request.create({'request_type_id': asr.id, 'employee_id': employee.id,
                       'description': "No schedule yet", 'amount': 800.0})
html_bare = rendered(report, bare)
check("an advance with no schedule says so on the page",
      "No repayment schedule" in html_bare,
      "said so" if "No repayment schedule" in html_bare else "printed a blank")

# ========================================================= the resignation ===
res = Type.search([('code', '=', 'RES')], limit=1)
leaving = Request.create({
    'request_type_id': res.id,
    'employee_id': employee.id,
    'description': "Resignation",
    'last_day_of_duty': date(2026, 9, 30),
    'end_of_service_date': date(2026, 9, 30),
    # A resignation now has to say how somebody is leaving and give a month.
    # This one is far enough out; the rule itself is exercised in
    # exercise_notice_period.py.
    'leaving_reason': 'resign',
    'resignation_reason': "Family",
})
leaving.action_submit()

letter = env.ref('ssc_requests_payroll.action_report_request_resignation')  # noqa: F821
html_letter = rendered(letter, leaving)
check("the letter renders", bool(html_letter), "%s characters" % len(html_letter))
for what, text in (("its title", "Notice of Resigning"),
                   ("the employee's name", "Ragesh Peethambaran"),
                   ("the company", leaving.company_id.name),
                   ("the last day", "09/30/2026")):
    check("the letter carries %s" % what, text in html_letter,
          text if text in html_letter else "MISSING")
check("and it is dated, which 1,098 of Studio's were not",
      "Date:" in html_letter and str(leaving.date_request.year) in html_letter,
      "dated")

# ================================================= one field, not two ========
check("amount_in_words is declared once, in the base module",
      Request._fields['amount_in_words'].compute == '_compute_amount_in_words',
      "one field")
spc = Type.search([('code', '=', 'SPC')], limit=1)
if spc:
    certificate = Request.create({'request_type_id': spc.id,
                                  'description': "Payment certificate",
                                  'amount': 100.0})
    check("a certificate still spells its own number, not the amount asked for",
          certificate._amount_to_spell() == certificate.certificate_net,
          "%s vs amount %s" % (certificate._amount_to_spell(), certificate.amount))

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
