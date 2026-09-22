"""Call an order off a subcontract, approve the LPO, check the purchase order."""
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import mute_logger

Order = env['ssc.subcontract.order']                              # noqa: F821
Contract = env['ssc.subcontract']                                 # noqa: F821
Item = env['ssc.subcontract.item']                                # noqa: F821
Project = env['project.project']                                  # noqa: F821
Partner = env['res.partner']                                      # noqa: F821
Analytic = env['account.analytic.account']                        # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-62s %s" % (label, detail))


plan = env['account.analytic.plan'].search([], limit=1) \
    or env['account.analytic.plan'].create({'name': "Projects"})  # noqa: F821
account = Analytic.create({'name': "Al Khan", 'plan_id': plan.id})
project = Project.create({'name': "Al Khan G+15", 'ssc_is_construction': True,
                          'account_id': account.id})
mason = Partner.create({'name': "Gulf Masonry LLC"})
contract = Contract.create({
    'partner_id': mason.id, 'project_id': project.id,
    'description': "Blockwork to Block A"})
wall = Item.create({'contract_id': contract.id, 'name': "200mm blockwork",
                    'unit': 'sqm', 'quantity': 900.0, 'unit_price': 36.0})
cable = Item.create({'contract_id': contract.id, 'name': "Sundries",
                     'unit': 'ls', 'quantity': 1.0, 'unit_price': 5000.0})

# --- the order ---------------------------------------------------------------
order = Order.create({'contract_id': contract.id, 'project_id': project.id,
                      'description': "First call-off",
                      'quotation_ref': 'QT-118'})
check("an order is numbered by the sequence",
      order.name.startswith('SCO/'), order.name)
check("it reads the subcontractor off the contract, not typed again",
      order.partner_id == mason, order.partner_id.display_name)
check("it shows the contract's items without copying them",
      len(order.contract_item_ids) == 2, len(order.contract_item_ids))
check("it starts as a draft", order.state == 'draft', order.state)
check("and the contract counts it", contract.order_count == 1,
      contract.order_count)

try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        order.action_approve_lpo()
    check("an order cannot be approved before it is sent", False,
          "it was allowed")
except UserError:
    check("an order cannot be approved before it is sent", True)

order.action_send_for_lpo()
check("sending it moves it on", order.state == 'to_approve', order.state)

# --- the purchase order ------------------------------------------------------
order.action_approve_lpo()
check("approving makes the purchase order", bool(order.purchase_order_id),
      order.purchase_order_id.name)
purchase = order.purchase_order_id
check("it is with the subcontractor", purchase.partner_id == mason)
check("it carries the quotation reference",
      purchase.partner_ref == 'QT-118', purchase.partner_ref)
check("one line per contract item", len(purchase.order_line) == 2,
      len(purchase.order_line))
check("at the contract's own rates",
      sorted(purchase.order_line.mapped('price_unit')) == [36.0, 5000.0],
      sorted(purchase.order_line.mapped('price_unit')))
check("and its quantities",
      sorted(purchase.order_line.mapped('product_qty')) == [1.0, 900.0],
      sorted(purchase.order_line.mapped('product_qty')))
check("the purchase order is worth the contract",
      purchase.amount_untaxed == 37400.0, purchase.amount_untaxed)
check("and the order says so", order.amount_purchased == 37400.0,
      order.amount_purchased)
check("every line is costed to the project's analytic account",
      all(line.analytic_distribution == {str(account.id): 100.0}
          for line in purchase.order_line),
      purchase.order_line[0].analytic_distribution)

order.action_reset_to_draft()
order.action_send_for_lpo()
order.action_approve_lpo()
check("approving again does not make a second purchase order",
      order.purchase_order_id == purchase,
      order.purchase_order_id.name)
check("and there is still only one on the database",
      env['purchase.order'].search_count(                          # noqa: F821
          [('partner_id', '=', mason.id)]) == 1)

# --- what must not be allowed ------------------------------------------------
other = Project.create({'name': "Another Job", 'ssc_is_construction': True})
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        Order.create({'contract_id': contract.id, 'project_id': other.id,
                      'description': "Wrong job"})
    check("an order cannot be on a different job from its contract", False,
          "it was allowed")
except ValidationError:
    check("an order cannot be on a different job from its contract", True)

bare = Order.create({'project_id': project.id, 'partner_id': mason.id,
                     'description': "No contract behind it"})
check("an order with no contract can still be recorded", bool(bare),
      bare.name)
bare.action_send_for_lpo()
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db'):           # noqa: F821
        bare.action_approve_lpo()
    check("but it cannot make a purchase order out of nothing", False,
          "it was allowed")
except UserError:
    check("but it cannot make a purchase order out of nothing", True)

# --- the certificate knows its order -----------------------------------------
Request = env['ssc.request']                                       # noqa: F821
spc_type = env['ssc.request.type'].search([('code', '=', 'SPC')], limit=1)  # noqa: F821
if spc_type:
    certificate = Request.create({
        'request_type_id': spc_type.id,
        'description': "Certificate 1",
        'contract_id': contract.id,
        'subcontract_order_id': order.id,
    })
    check("a certificate says which order it claims against",
          certificate.subcontract_order_id == order)
    check("and the order counts it", order.certificate_count == 1,
          order.certificate_count)
    other_contract = Contract.create({'partner_id': mason.id,
                                      'project_id': other.id,
                                      'description': "Elsewhere"})
    try:
        with env.cr.savepoint(), mute_logger('odoo.sql_db'):       # noqa: F821
            certificate.contract_id = other_contract
        check("a certificate cannot claim an order of another contract",
              False, "it was allowed")
    except ValidationError:
        check("a certificate cannot claim an order of another contract", True)
else:
    check("the SPC request type is seeded", False, "not found")

# --- who may do what ---------------------------------------------------------
user = env['res.users'].create({                                   # noqa: F821
    'name': "Buyer", 'login': 'buyer.test',
    'group_ids': [(6, 0, [
        env.ref('base.group_user').id,                             # noqa: F821
        env.ref('ssc_subcontract.group_subcontract_user').id])],   # noqa: F821
})
try:
    made = Order.with_user(user).create({'project_id': project.id,
                                         'description': "Raised by a buyer"})
    check("a subcontract user can raise an order", bool(made))
except Exception as error:
    check("a subcontract user can raise an order", False, str(error)[:60])
try:
    with env.cr.savepoint(), mute_logger('odoo.sql_db',             # noqa: F821
                                         'odoo.addons.base.models.ir_rule'):
        Order.with_user(user).browse(order.id).unlink()
    check("but cannot delete one", False, "it was allowed")
except Exception:
    check("but cannot delete one", True)

# --- the screens -------------------------------------------------------------
for xmlid in ('ssc_subcontract_order.view_ssc_subcontract_order_form',
              'ssc_subcontract_order.view_ssc_subcontract_order_list',
              'ssc_subcontract_order.view_ssc_subcontract_order_search'):
    view = env.ref(xmlid)                                          # noqa: F821
    try:
        env[view.model].get_view(view.id, view.type)               # noqa: F821
        check("view opens: %s" % xmlid.split('.')[-1], True)
    except Exception as error:
        check("view opens: %s" % xmlid.split('.')[-1], False, str(error)[:70])

for xmlid, model, kind in (
        ('ssc_subcontract.view_ssc_subcontract_form', 'ssc.subcontract', 'form'),
        ('ssc_requests.view_ssc_request_form', 'ssc.request', 'form'),
        ('purchase.purchase_order_form', 'purchase.order', 'form')):
    try:
        env[model].get_view(env.ref(xmlid).id, kind)               # noqa: F821
        check("still opens: %s" % xmlid.split('.')[-1], True)
    except Exception as error:
        check("still opens: %s" % xmlid.split('.')[-1], False, str(error)[:70])

menu = env.ref('ssc_project.menu_ssc_procurement_root')            # noqa: F821
check("the orders menu sits under the application",
      'Orders' in menu.child_id.mapped('name'),
      ", ".join(menu.child_id.mapped('name')))

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
