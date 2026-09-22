"""A request that reaches a reviewer tells them so."""
Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
User = env['res.users']                                           # noqa: F821
Activity = env['mail.activity']                                   # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-66s %s" % (label, detail))


def groups(*refs):
    return [(6, 0, [env.ref(ref).id for ref in refs])]            # noqa: F821


BASE = 'base.group_user'
USER = 'ssc_requests.group_request_user'
PE = 'ssc_requests.group_request_pe_review'
HR = 'ssc_requests.group_request_hr_review'
APPROVE = 'ssc_requests.group_request_approver'

storekeeper = User.create({'name': "Store Keeper", 'login': 'act.store',
                           'group_ids': groups(BASE, USER)})
manager = User.create({'name': "Gogul the Project Manager",
                       'login': 'act.pm',
                       'group_ids': groups(BASE, USER, PE, APPROVE)})
hr_one = User.create({'name': "HR One", 'login': 'act.hr1',
                      'group_ids': groups(BASE, USER, HR)})
hr_two = User.create({'name': "HR Two", 'login': 'act.hr2',
                      'group_ids': groups(BASE, USER, HR)})
approver = User.create({'name': "Mohammad the Approver", 'login': 'act.appr',
                        'group_ids': groups(BASE, USER, APPROVE)})

project = env['project.project'].create({                         # noqa: F821
    'name': "Arjan Townhouses",
    'user_id': manager.id,
    'ssc_request_approver_id': approver.id,
})


def open_todos(record):
    return Activity.search([('res_model', '=', 'ssc.request'),
                            ('res_id', '=', record.id)])


def a_request(code, **values):
    kind = Type.search([('code', '=', code)], limit=1)
    return Request.with_user(storekeeper).create(dict(
        {'request_type_id': kind.id, 'project_id': project.id,
         'description': "Cement for the raft"}, **values))


# --- project review goes to the project's manager ---------------------------
material = a_request('MR')
check("a draft raises nothing", not open_todos(material), len(open_todos(material)))

material.with_user(storekeeper).action_submit()
todos = open_todos(material)
check("submitting raises a task for somebody", bool(todos), len(todos))
check("and it is the project's own manager, not a name in a rule",
      todos.user_id == manager, todos.user_id.name)
check("the task says which step it is waiting for",
      "Project Review" in (todos.summary or ''), todos.summary)
check("and the manager is following the record now",
      manager.partner_id in material.message_partner_ids, "following")

# --- acting on it closes the task and opens the next ------------------------
material.with_user(manager).action_pe_review()
after = open_todos(material)
check("acting closes the reviewer's task",
      manager not in after.mapped('user_id'), "closed")

if material.state == 'hr_review':
    check("HR review raises one for each of the HR team",
          after.user_id == (hr_one | hr_two),
          ", ".join(after.mapped('user_id.name')))
    material.with_user(hr_one).action_hr_review()
    after = open_todos(material)

check("the approver's task is raised when it reaches them",
      material.state != 'to_approve' or after.user_id == approver,
      "%s -> %s" % (material.state, ", ".join(after.mapped('user_id.name'))))

material.with_user(approver).action_approve()
check("approving leaves no task open at all", not open_todos(material),
      len(open_todos(material)))

# --- a request nobody can handle says so instead of going quiet -------------
orphan_project = env['project.project'].create(                   # noqa: F821
    {'name': "No manager here", 'user_id': False})
orphan = a_request('MR', project_id=orphan_project.id)
orphan.with_user(storekeeper).action_submit()
check("with no project manager, no task is raised",
      not open_todos(orphan), len(open_todos(orphan)))
check("and the chatter says why, rather than the request waiting for ever",
      any("Nobody is set to handle" in (m.body or '')
          for m in orphan.message_ids),
      "said so" if any("Nobody is set to handle" in (m.body or '')
                       for m in orphan.message_ids) else "went quiet")

# --- rejecting closes the task too ------------------------------------------
rejected = a_request('MR')
rejected.with_user(storekeeper).action_submit()
check("a submitted request has a task waiting", bool(open_todos(rejected)),
      len(open_todos(rejected)))
rejected.rejection_reason = "The store already holds it."
rejected.with_user(manager).action_reject()
check("rejecting closes it - nobody is sent to a dead record",
      not open_todos(rejected), len(open_todos(rejected)))

# --- and the screens still open ---------------------------------------------
try:
    Request.get_view(env.ref('ssc_requests.view_ssc_request_form').id, 'form')  # noqa: F821
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
