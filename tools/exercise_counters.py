"""How many of each kind are waiting, and where."""
Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
Project = env['project.project']                                  # noqa: F821
User = env['res.users']                                           # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-60s %s" % (label, detail))


everyone = User.create({
    'name': "Reviewer", 'login': 'counter.test',
    'group_ids': [(6, 0, [
        env.ref('base.group_user').id,                            # noqa: F821
        env.ref('ssc_requests.group_request_pe_review').id,       # noqa: F821
        env.ref('ssc_requests.group_request_hr_review').id,       # noqa: F821
        env.ref('ssc_requests.group_request_approver').id])],     # noqa: F821
})

project = Project.create({'name': "Al Khan G+15"})
mr = Type.search([('code', '=', 'MR')], limit=1)
alr = Type.search([('code', '=', 'ALR')], limit=1)
check("MR goes past the project engineer", mr.needs_pe_review is True)
check("ALR goes past HR", alr.needs_hr_review is True)

check("nothing is waiting to start with", mr.pending_count == 0,
      mr.pending_count)


def raise_one(request_type, description):
    values = {'request_type_id': request_type.id, 'description': description}
    if request_type.numbering == 'per_project':
        values['project_id'] = project.id
    record = Request.create(values)
    record.action_submit()
    return record


# --- three material requests, all at the project engineer ---------------------
first = raise_one(mr, "Blockwork")
second = raise_one(mr, "Cable")
third = raise_one(mr, "Sand")
mr.invalidate_recordset()
check("three submitted material requests are three at the project engineer",
      mr.pending_pe_count == 3, mr.pending_pe_count)
check("and none anywhere else",
      mr.pending_hr_count == 0 and mr.pending_approval_count == 0,
      "%s at HR, %s to approve" % (mr.pending_hr_count,
                                   mr.pending_approval_count))
check("and three waiting in all", mr.pending_count == 3, mr.pending_count)

# --- one moves on --------------------------------------------------------------
first.with_user(everyone).action_pe_review()
mr.invalidate_recordset()
check("passing the project review moves the number, it does not add one",
      mr.pending_pe_count == 2 and mr.pending_approval_count == 1,
      "%s at P.E, %s to approve" % (mr.pending_pe_count,
                                    mr.pending_approval_count))
check("and the total is still three", mr.pending_count == 3, mr.pending_count)

# --- one leaves ----------------------------------------------------------------
first.with_user(everyone).action_approve()
mr.invalidate_recordset()
check("an approved request is not waiting for anybody",
      mr.pending_count == 2, mr.pending_count)

second.rejection_reason = "Ordered already"
second.with_user(everyone).action_reject()
mr.invalidate_recordset()
check("nor is a rejected one", mr.pending_count == 1, mr.pending_count)

third.action_cancel()
mr.invalidate_recordset()
check("nor a cancelled one", mr.pending_count == 0, mr.pending_count)

# --- a type with an HR step ----------------------------------------------------
leave = raise_one(alr, "Annual leave")
alr.invalidate_recordset()
at_first = (alr.pending_pe_count, alr.pending_hr_count,
            alr.pending_approval_count)
check("a leave request starts wherever its type says",
      sum(at_first) == 1, "P.E %s, HR %s, approve %s" % at_first)

while leave.state in ('pe_review', 'hr_review'):
    if leave.state == 'pe_review':
        leave.with_user(everyone).action_pe_review()
    else:
        leave.with_user(everyone).action_hr_review()
alr.invalidate_recordset()
check("and reaches approval through HR without being counted twice",
      alr.pending_count == 1 and alr.pending_approval_count == 1,
      "%s waiting, %s to approve" % (alr.pending_count,
                                     alr.pending_approval_count))

# --- one type does not count another's -----------------------------------------
mr.invalidate_recordset()
check("a leave request is not counted against material requests",
      mr.pending_count == 0, mr.pending_count)

# --- the numbers open the requests behind them ----------------------------------
action = alr.action_open_pending()
found = Request.search(action['domain'])
check("the counter opens the requests it counted",
      leave in found, "%s request(s)" % len(found))

action = alr.with_context(pending_states=['pe_review']).action_open_pending()
check("and one step of it opens only that step",
      len(Request.search(action['domain'])) == alr.pending_pe_count,
      len(Request.search(action['domain'])))

# --- every type at once is one query, not one each ------------------------------
types = Type.search([])
types.invalidate_recordset()
counted = sum(types.mapped('pending_count'))
check("counting every type at once agrees with counting them apart",
      counted == sum(Type.browse(t.id).pending_count for t in types),
      counted)

# --- the screens ----------------------------------------------------------------
for xmlid, kind in (
        ('ssc_requests.view_ssc_request_type_kanban', 'kanban'),
        ('ssc_requests.view_ssc_request_type_list', 'list'),
        ('ssc_requests.view_ssc_request_type_form', 'form')):
    try:
        Type.get_view(env.ref(xmlid).id, kind)                    # noqa: F821
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
