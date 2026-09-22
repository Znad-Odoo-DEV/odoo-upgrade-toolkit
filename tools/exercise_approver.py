"""Who a request is assigned to, and who ends up signing it."""
Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
Project = env['project.project']                                  # noqa: F821
User = env['res.users']                                           # noqa: F821
Company = env['res.company']                                      # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-64s %s" % (label, detail))


def make_user(name, login):
    return User.create({
        'name': name, 'login': login,
        'group_ids': [(6, 0, [
            env.ref('base.group_user').id,                        # noqa: F821
            env.ref('ssc_requests.group_request_approver').id,    # noqa: F821
            env.ref('ssc_requests.group_request_pe_review').id,   # noqa: F821
            env.ref('ssc_requests.group_request_hr_review').id])],  # noqa: F821
    })


gogul = make_user("Gogul", 'gogul.test')
haleme = make_user("Haleme", 'haleme.test')
fallback = make_user("Company Fallback", 'fallback.test')

company = env.company                                             # noqa: F821
company.ssc_request_approver_id = fallback
arjan = Project.create({'name': "Arjan Villas",
                        'ssc_request_approver_id': gogul.id})
khan = Project.create({'name': "Al Khan G+15",
                       'ssc_request_approver_id': haleme.id})
nameless = Project.create({'name': "A project nobody assigned"})

sc_type = Type.search([('code', '=', 'SC')], limit=1) \
    or Type.search([('numbering', '!=', 'per_project')], limit=1)
mr_type = Type.search([('code', '=', 'MR')], limit=1)

# --- the project decides ------------------------------------------------------
one = Request.create({'request_type_id': mr_type.id, 'project_id': arjan.id,
                      'description': "Blockwork"})
check("a request takes its approver from its project",
      one.approver_expected_id == gogul, one.approver_expected_id.name)

two = Request.create({'request_type_id': mr_type.id, 'project_id': khan.id,
                      'description': "Cable"})
check("a different project, a different approver",
      two.approver_expected_id == haleme, two.approver_expected_id.name)

# --- the company catches what the project drops -------------------------------
three = Request.create({'request_type_id': mr_type.id,
                        'project_id': nameless.id,
                        'description': "Something"})
check("a project that says nothing falls back to the company",
      three.approver_expected_id == fallback,
      three.approver_expected_id.name)

four = Request.create({'request_type_id': sc_type.id,
                       'description': "No project at all"})
check("and so does a request with no project",
      four.approver_expected_id == fallback, four.approver_expected_id.name)

# --- it follows the project when the project changes --------------------------
one.project_id = khan
check("moving a request to another project moves its approver",
      one.approver_expected_id == haleme, one.approver_expected_id.name)

# --- and a person can override it on one request ------------------------------
one.approver_expected_id = gogul
check("somebody can override it on one request",
      one.approver_expected_id == gogul, one.approver_expected_id.name)
check("without touching the project", khan.ssc_request_approver_id == haleme,
      khan.ssc_request_approver_id.name)

# --- assigned to one, signed by another ---------------------------------------
two.action_submit()
while two.state != 'to_approve':
    if two.state == 'pe_review':
        two.with_user(gogul).action_pe_review()
    elif two.state == 'hr_review':
        two.with_user(gogul).action_hr_review()
    else:
        break
check("it reaches the approval step", two.state == 'to_approve', two.state)

before = len(two.message_ids)
two.with_user(gogul).action_approve()
check("anybody in the approver group can still approve it",
      two.state == 'approved', two.state)
check("and who actually signed is recorded",
      two.approver_id == gogul, two.approver_id.name)
check("beside who it was assigned to",
      two.approver_expected_id == haleme, two.approver_expected_id.name)
notes = "\n".join(two.message_ids.mapped('body'))
check("and the chatter says the two were different",
      'Haleme' in notes and 'Gogul' in notes,
      "a note naming both" if 'Haleme' in notes else "no note")

# --- the same person signing leaves no such note ------------------------------
five = Request.create({'request_type_id': mr_type.id, 'project_id': arjan.id,
                       'description': "Signed by the right person"})
five.action_submit()
while five.state not in ('to_approve', 'approved'):
    if five.state == 'pe_review':
        five.with_user(gogul).action_pe_review()
    elif five.state == 'hr_review':
        five.with_user(gogul).action_hr_review()
    else:
        break
five.with_user(gogul).action_approve()
notes = "\n".join(five.message_ids.mapped('body'))
check("when the assigned person signs, nothing is remarked on",
      'was assigned to' not in notes, "quiet" if 'was assigned' not in notes
      else "it said something")

# --- the screens --------------------------------------------------------------
for xmlid, model, kind in (
        ('ssc_requests.view_ssc_request_form', 'ssc.request', 'form'),
        ('ssc_requests.view_ssc_request_search', 'ssc.request', 'search'),
        ('project.edit_project', 'project.project', 'form'),
        ('base.view_company_form', 'res.company', 'form')):
    try:
        env[model].get_view(env.ref(xmlid).id, kind)               # noqa: F821
        check("view opens: %s" % xmlid.split('.')[-1], True)
    except Exception as error:
        check("view opens: %s" % xmlid.split('.')[-1], False, str(error)[:70])

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
