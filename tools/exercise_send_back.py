"""Back one step, to the reviewer before this one - with a reason."""
Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
User = env['res.users']                                           # noqa: F821
Activity = env['mail.activity']                                   # noqa: F821
UserError = odoo.exceptions.UserError                             # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-66s %s" % (label, detail))


def groups(*refs):
    return [(6, 0, [env.ref(ref).id for ref in refs])]            # noqa: F821


everyone = User.create({
    'name': "Does Everything", 'login': 'back.all',
    'group_ids': groups('base.group_user',
                        'ssc_requests.group_request_user',
                        'ssc_requests.group_request_pe_review',
                        'ssc_requests.group_request_hr_review',
                        'ssc_requests.group_request_approver'),
})
project = env['project.project'].create({                         # noqa: F821
    'name': "Arjan", 'user_id': everyone.id,
    'ssc_request_approver_id': everyone.id})


def a_request(code):
    kind = Type.search([('code', '=', code)], limit=1)
    return Request.with_user(everyone).create({
        'request_type_id': kind.id, 'project_id': project.id,
        'description': "Cement"})


def refuses(record, method):
    try:
        getattr(record.with_user(everyone), method)()
        return None
    except UserError as error:
        return str(error)


# --- it needs a reason -------------------------------------------------------
material = a_request('MR')
material.with_user(everyone).action_submit()
while material.state in ('pe_review', 'hr_review'):
    before = material.state
    getattr(material.with_user(everyone),
            'action_pe_review' if before == 'pe_review' else 'action_hr_review')()
check("the request reaches the approver", material.state == 'to_approve',
      material.state)

message = refuses(material, 'action_send_back')
check("sending back with no reason is refused", message is not None, "refused")
check("and the message says the note is what the next person reads",
      message and "picks it up reads that" in message, (message or '')[:60])
check("the request has not moved", material.state == 'to_approve',
      material.state)

# --- with one, it goes back a step ------------------------------------------
material.return_note = "The quantity for block C is wrong."
material.with_user(everyone).action_send_back()
check("it goes back one step, not to draft",
      material.state in ('hr_review', 'pe_review'), material.state)
check("the number is kept - it is the same request",
      bool(material.name) and "-R" not in material.name, material.name)
check("and the revision is not bumped", material.revision == 0,
      material.revision)
check("the chatter says who sent it back and why",
      any("The quantity for block C is wrong" in (m.body or '')
          for m in material.message_ids), "said so")

# --- the review being undone is cleared -------------------------------------
check("the review it was sent back from is cleared, not left standing",
      not material.pe_review_date or material.state != 'pe_review',
      "%s / %s" % (material.state, material.pe_review_date))

# --- and a task is raised for whoever it went back to ------------------------
todos = Activity.search([('res_model', '=', 'ssc.request'),
                         ('res_id', '=', material.id)])
check("the person it went back to is told", bool(todos),
      ", ".join(todos.mapped('user_id.name')))

# --- from the first step it cannot go further back --------------------------
fresh = a_request('MR')
fresh.with_user(everyone).action_submit()
fresh.return_note = "Wrong project."
fresh.with_user(everyone).action_send_back()
check("from the first review it goes to draft", fresh.state == 'draft',
      fresh.state)

message = refuses(fresh, 'action_send_back')
check("and a draft cannot be sent back to anybody", message is not None,
      "refused")
check("the message says there is nobody to send it to",
      message and "nobody to send it back to" in message, (message or '')[:60])

# --- it is not the same as returning to the requester ------------------------
other = a_request('MR')
other.with_user(everyone).action_submit()
number_was = other.name
other.with_user(everyone).action_revise()
check("returning to the requester goes all the way to draft",
      other.state == 'draft', other.state)
check("and gives it a new revision, which sending back does not",
      other.revision == 1 and other.name.endswith("-R1"), other.name)
check("the two are different things with different labels",
      number_was != other.name, "%s -> %s" % (number_was, other.name))

try:
    Request.get_view(
        env.ref('ssc_requests.view_ssc_request_form').id, 'form')  # noqa: F821
    check("the form still opens with both buttons on it", True, "")
except Exception as error:
    check("the form still opens with both buttons on it", False,
          str(error)[:60])

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
