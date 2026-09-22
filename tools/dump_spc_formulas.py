"""The arithmetic Studio used for a payment certificate, read rather than inferred.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/dump_spc_formulas.py

    SSC_OUT=~/spc_formulas.md

Reads only.

Two guesses about why our certificates differ have now failed. The first said
our quantity was the whole contract rather than this period's - it was not,
because the error goes both ways. The second said each sector claim carried a
copy of the line's quantity - it did not, because the ratio is four whether a
line has one sector or eighteen.

And the run that killed the second guess showed something that makes both
guesses beside the point. On SPC0003, Studio's own line says 47 at 4,000,
which is 188,000. Studio's x_studio_total_amount on that certificate says
56,400. So Studio's total is not the sum of its lines, and comparing it with
our sum of lines was comparing two different measures. There is a
"Progressive % on this invoice" on these records, filled on 26 of them.

Inferring a third time would be a worse idea than the first two. These are
computed fields, and a computed field on a Studio model carries its code in
ir.model.fields.compute - the arithmetic is written down and can simply be
read.

So this prints, for every money field on the certificate: whether it is
stored or computed, what it depends on, and the code itself, in full. Plus
any server action or automation rule whose body names it, because Studio
splits one calculation across four places and the compute code is only one of
them.

What comes out of this is the office's own definition of a payment
certificate. That is what our model has to agree with - and where it already
does, the difference was never a fault.
"""
import os

OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/spc_formulas.md')

STUDIO = 'x_all_requests'

# what the certificate's money is made of, in the order the page reads
WANTED = [
    'x_studio_total_amount',
    'x_studio_sub_total_amount',
    'x_studio_net_payable_amount',
    'x_studio_vat_5',
    'x_studio_vat',
    'x_studio_retention_1',
    'x_studio_ret_perc',
    'x_studio_retention',
    'x_studio_retention_deduction',
    'x_studio_advance',
    'x_studio_advance_perc',
    'x_studio_advance_value',
    'x_studio_advance_recovery',
    'x_studio_advance_deduction',
    'x_studio_progressive_',
    'x_studio_progressive_on_this_invoice',
    'x_studio_payable_invoice',
    'x_studio_contract_value',
    'x_studio_penalty_amount',
    'x_studio_has_penalty',
    'x_studio_total_sum_in_words_1',
    'x_studio_prog_pay',
    'x_studio_open_quotation',
]

IrField = env['ir.model.fields'].sudo()                          # noqa: F821

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say()
    say(rule * 96)
    say(text)
    say(rule * 96)


title("how Studio worked out a payment certificate")
say("  Read from ir.model.fields, not worked out from the numbers.")

fields = IrField.search([('model', '=', STUDIO), ('name', 'in', WANTED)])
by_name = {field.name: field for field in fields}

# ---------------------------------------------------------- the short version
title("stored or computed", '-')
say("      %-42s %-10s %s" % ("field", "type", "how it gets its value"))
say()
for name in WANTED:
    field = by_name.get(name)
    if not field:
        say("      %-42s %s" % (name, "not on this database"))
        continue
    if field.compute:
        how = "COMPUTED%s" % (", stored" if field.store else "")
    elif field.related:
        how = "related: %s" % field.related
    else:
        how = "typed by somebody"
    say("      %-42s %-10s %s" % (name[:42], field.ttype, how))

# ------------------------------------------------------------ the code itself
title("the code, in full", '-')
for name in WANTED:
    field = by_name.get(name)
    if not field or not (field.compute or field.related):
        continue
    say()
    say("  %s   (%s)" % (name, field.field_description))
    if field.depends:
        say("      depends on: %s" % field.depends)
    if field.related:
        say("      related:    %s" % field.related)
    if field.compute:
        say("      code:")
        for line in (field.compute or '').split('\n'):
            say("          %s" % line)

# ------------------------------------- and the other three places logic hides
title("server actions and automations that name any of these", '-')
say("  A Studio model keeps its arithmetic in four places and compute code is")
say("  only one of them. A total that is written by a server action on save")
say("  looks like a typed column from every screen there is.")

Action = env['ir.actions.server'].sudo()                          # noqa: F821
Automation = env.get('base.automation')                           # noqa: F821

for action in Action.search([('model_id.model', '=', STUDIO)]):
    body = action.code or ''
    hits = [name for name in WANTED if name in body]
    if not hits:
        continue
    say()
    say("  ---- server action: %s" % action.name)
    say("       touches: %s" % ", ".join(hits))
    say()
    for line in body.split('\n'):
        say("          %s" % line)

if Automation is not None:
    for rule in Automation.sudo().search([('model_id.model', '=', STUDIO)]):
        bodies = []
        for child in rule.action_server_ids:
            bodies.append((child.name, child.code or ''))
        for child_name, body in bodies:
            hits = [name for name in WANTED if name in body]
            if not hits:
                continue
            say()
            say("  ---- automation: %s   ->   %s" % (rule.name, child_name))
            say("       on %s, touches: %s" % (rule.trigger, ", ".join(hits)))
            say()
            for line in body.split('\n'):
                say("          %s" % line)

title("what to compare it with")
say("""  Ours, for the same certificate, is in
  addons/ssc_requests_subcontract/models/ssc_request_certificate.py:

      gross      = sum of the lines
      subtotal   = gross - retention - advance recovery - penalty
      VAT        = subtotal x the contract's VAT percentage
      net        = subtotal + VAT

  Where the code above says the same thing, our totals differing is an import
  fault. Where it says something else - a progressive percentage applied to
  the lines, a retention computed on a running total rather than this
  certificate - then the model is what has to change, and no amount of
  reimporting will make the numbers agree.
""")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
