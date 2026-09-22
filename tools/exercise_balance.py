"""The balance to order says nothing until somebody says what the project needs."""
Request = env['ssc.request']                                      # noqa: F821
Line = env['ssc.request.material.line']                           # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
Product = env['product.product']                                  # noqa: F821
Project = env['project.project']                                  # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-62s %s" % (label, detail))


mr_type = Type.search([('code', '=', 'MR')], limit=1)
check("the MR request type is seeded", bool(mr_type), mr_type.display_name)

project = Project.create({'name': "Al Khan G+15"})
cement = Product.create({'name': "Cement 50kg", 'is_storable': True})
request = Request.create({
    'request_type_id': mr_type.id,
    'description': "Blockwork materials",
    'project_id': project.id,
})

# --- nobody has said what the project needs -----------------------------------
line = Line.create({'request_id': request.id, 'product_id': cement.id,
                    'quantity': 500.0})
check("with no project quantity, the balance is nought - not minus five hundred",
      line.balance_to_order == 0.0, line.balance_to_order)
check("and it says so, so the screen can hide it",
      line.has_balance is False, line.has_balance)

# --- somebody has --------------------------------------------------------------
line.quantity_project = 2000.0
check("given a project quantity, the balance is what is left",
      line.balance_to_order == 1500.0, line.balance_to_order)
check("and it says the balance is known", line.has_balance is True,
      line.has_balance)

# --- and it takes earlier requests off it --------------------------------------
earlier = Request.create({
    'request_type_id': mr_type.id, 'description': "Earlier",
    'project_id': project.id,
})
Line.create({'request_id': earlier.id, 'product_id': cement.id,
             'quantity': 300.0})
earlier.action_submit()
line.invalidate_recordset(['quantity_previous', 'balance_to_order'])
check("an earlier submitted request is taken off the balance",
      line.quantity_previous == 300.0 and line.balance_to_order == 1200.0,
      "%s previous, %s left" % (line.quantity_previous, line.balance_to_order))

# --- a rejected one is not -----------------------------------------------------
earlier.rejection_reason = "Ordered on another request"
earlier.action_reject()
line.invalidate_recordset(['quantity_previous', 'balance_to_order'])
check("a rejected one is not", line.quantity_previous == 0.0
      and line.balance_to_order == 1500.0,
      "%s previous, %s left" % (line.quantity_previous, line.balance_to_order))

# --- clearing it puts the balance back to silence -------------------------------
line.quantity_project = 0.0
check("clearing the project quantity silences the balance again",
      line.balance_to_order == 0.0 and line.has_balance is False,
      line.balance_to_order)

# --- the screen -----------------------------------------------------------------
try:
    view = env.ref('ssc_requests.view_ssc_request_form')           # noqa: F821
    env['ssc.request'].get_view(view.id, 'form')                   # noqa: F821
    check("the request form still opens", True)
except Exception as error:
    check("the request form still opens", False, str(error)[:70])

print()
print("PASS  %s" % len(ok))
for line_out in ok:
    print("   ok   %s" % line_out)
if bad:
    print()
    print("FAIL  %s" % len(bad))
    for line_out in bad:
        print("   XX   %s" % line_out)
else:
    print()
    print("nothing failed")

env.cr.rollback()                                                  # noqa: F821
print("rolled back")
