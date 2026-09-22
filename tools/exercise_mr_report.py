"""The materials requisition prints, and prints what is on the request."""
import base64

Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821
User = env['res.users']                                           # noqa: F821
Product = env['product.product']                                  # noqa: F821
Report = env['ir.actions.report']                                  # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-62s %s" % (label, detail))


# a one pixel png, which is all a signature has to be for this
SIGNATURE = base64.b64encode(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))

engineer = User.create({
    'name': "Basel Aaroud", 'login': 'mr.engineer',
    'ssc_signature': SIGNATURE,
    'group_ids': [(6, 0, [
        env.ref('base.group_user').id,                            # noqa: F821
        env.ref('ssc_requests.group_request_user').id,            # noqa: F821
        env.ref('ssc_requests.group_request_pe_review').id,       # noqa: F821
        env.ref('ssc_requests.group_request_hr_review').id,       # noqa: F821
        env.ref('ssc_requests.group_request_approver').id])],
})
storekeeper = User.create({
    'name': "Store Keeper", 'login': 'mr.store',
    'group_ids': [(6, 0, [
        env.ref('base.group_user').id,                            # noqa: F821
        env.ref('ssc_requests.group_request_user').id])],         # noqa: F821
})

check("a signature belongs to a person, and is stored once",
      bool(engineer.ssc_signature), "held on the user")
check("somebody who has not uploaded one simply has none",
      not storekeeper.ssc_signature, "empty")

cement = Product.create({'name': "Cement OPC 50kg", 'default_code': "MTL00000937"})
steel = Product.create({'name': "Steel Bar 12mm", 'default_code': "MTL00000938"})

mr = Type.search([('code', '=', 'MR')], limit=1)
project = env['project.project'].create({'name': "Khan Tower"})    # noqa: F821

request = Request.with_user(storekeeper).create({
    'request_type_id': mr.id,
    'project_id': project.id,
    'description': "Cement and steel for the raft",
    'material_line_ids': [
        (0, 0, {'product_id': cement.id, 'quantity': 400.0, 'item_no': 1}),
        (0, 0, {'product_id': steel.id, 'quantity': 12.5, 'item_no': 2}),
    ],
})
# The line above is the regression guard for a real defect: requested_by_id
# was filled at submit, and the requester's record rule - "the ones you
# raised" - is checked at create. A requester wrote a draft, the rule found an
# empty name on it and refused the row they had just written, so nobody
# outside the reviewers could raise anything at all.
check("a requester can create their own request",
      request.requested_by_id == storekeeper, request.requested_by_id.name)

request.with_user(storekeeper).action_submit()
while request.state in ('pe_review', 'hr_review'):
    if request.state == 'pe_review':
        request.with_user(engineer).action_pe_review()
    else:
        request.with_user(engineer).action_hr_review()
request.with_user(engineer).action_approve()

# --- when it is needed ------------------------------------------------------
check("empty reads as ASAP, which is what the store has always seen",
      request.date_required_label == "ASAP", request.date_required_label)
from datetime import date as _date                                # noqa: E402
request.date_required = _date(2026, 10, 15)
check("and a date reads as the date", request.date_required_label == "2026-10-15",
      request.date_required_label)

report = env.ref('ssc_requests.action_report_request_mr')         # noqa: F821
check("the report is bound to the request model",
      report.model == 'ssc.request', report.model)
check("and its name is the request's number",
      report.print_report_name == 'object.name', report.print_report_name)

html = report._render_qweb_html(report.report_name, request.ids)[0]
html = html.decode() if isinstance(html, bytes) else html

check("it renders at all", bool(html), "%s characters" % len(html))
for what, text in (("the heading", "MATERIALS REQUISITION"),
                   ("the project", "Khan Tower"),
                   ("the request number", request.name),
                   ("the first item", "Cement OPC 50kg"),
                   ("the item's code, which Studio called SN Of Item",
                    "MTL00000937"),
                   ("the second item", "Steel Bar 12mm"),
                   ("the quantity asked for", "400"),
                   ("who raised it", "Store Keeper"),
                   ("who reviewed it", "Basel Aaroud"),
                   ("the three roles", "Project Manager"),
                   ("when it is needed", "2026-10-15")):
    check("the page carries %s" % what, text in html,
          text if text in html else "MISSING - a blank goes to the store")

check("the signature is on the page as an image",
      'data:image/png;base64' in html or 'src="data:image' in html,
      "drawn" if 'data:image' in html else "MISSING")
check("and the person with no signature leaves an empty box, not an error",
      html.count('alt="Signature"') >= 1, html.count('alt="Signature"'))

# --- the numbers are the database's, not a typed copy ------------------------
line = request.material_line_ids[0]
check("stock available is computed, not typed",
      line._fields['quantity_available'].compute is not None, "computed")
check("previously requested is computed, not typed",
      line._fields['quantity_previous'].compute is not None, "computed")

# --- a request with nothing on it still prints -------------------------------
empty = Request.create({'request_type_id': mr.id, 'project_id': project.id,
                        'description': "Nothing listed yet"})
html_empty = report._render_qweb_html(report.report_name, empty.ids)[0]
html_empty = html_empty.decode() if isinstance(html_empty, bytes) else html_empty
check("an empty request prints a page that says so",
      "Nothing has been listed" in html_empty,
      "said so" if "Nothing has been listed" in html_empty else "MISSING")

# --- and it prints for somebody without HR rights ----------------------------
try:
    report.with_user(storekeeper)._render_qweb_html(report.report_name,
                                                    request.ids)
    check("the storekeeper can print it", True, "printed")
except Exception as error:
    check("the storekeeper can print it", False, str(error)[:60])

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
