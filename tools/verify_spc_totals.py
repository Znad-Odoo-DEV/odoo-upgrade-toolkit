"""Does Studio's stored total still equal what its own formula would give?

    odoo-bin shell --no-http --shell-interface=python \
        < tools/verify_spc_totals.py

    SSC_OUT=~/spc_totals.md

Reads only.

Three inferences from the numbers, three wrong. So this checks one thing and
states it, and everything it prints is a count rather than a conclusion.

Studio's formula for the certificate total is:

    for item in record.x_studio_spc_item:
        total += item.x_studio_amount

which is the sum of the lines - the same definition as ours. But on SPC0003
Studio's own line reads 47 at 4,000 and the stored total reads 56,400, and the
line model was found to carry only x_studio_quantity and x_studio_unit_price
among its numeric columns. If x_studio_amount is not a field there, the
formula has been reading nothing for as long as that has been true, and every
stored total is frozen at whatever it was when the field last existed.

That is worth knowing exactly, because it decides what "Studio's number" even
means. A stale stored total is not the figure the subcontractor was paid; it
is the figure some earlier version of the sheet produced. If it is stale, our
computed totals may be the correct ones and the whole reconciliation reverses.

So, in order:

  ONE   is x_studio_amount a field on the line model at all, and what is it -
        typed, computed, related?

  TWO   for every certificate, the stored total against the sum of its lines
        by each available definition: sum of x_studio_amount if it exists, and
        sum of quantity x unit_price.

  THREE how many contracts are on progressive payment and how many
        certificates suppress retention and recovery for an advance payment -
        the two mechanisms in Studio's arithmetic that our model has no
        equivalent for.
"""
import os

OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/spc_totals.md')

STUDIO = 'x_all_requests'

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say()
    say(rule * 96)
    say(text)
    say(rule * 96)


def finish():
    with open(OUT, 'w', encoding='utf-8') as handle:
        handle.write("\n".join(report))
    print("\nwritten to %s" % OUT)
    raise SystemExit


def g(record, name, default=None):
    try:
        return record[name]
    except Exception:
        return default


IrField = env['ir.model.fields'].sudo()                          # noqa: F821

title("is the stored total still what the formula would produce?")

if STUDIO not in env:                                            # noqa: F821
    say("  %s is not here." % STUDIO)
    finish()

Studio = env[STUDIO].sudo()                                      # noqa: F821
item_field = IrField.search([('model', '=', STUDIO),
                             ('name', '=', 'x_studio_spc_item')], limit=1)
LineModel = item_field.relation if item_field else None
if not LineModel or LineModel not in env:                        # noqa: F821
    say("  x_studio_spc_item does not resolve.")
    finish()

# ================================================================= ONE =======
title("ONE - what x_studio_amount is on %s" % LineModel, '-')

amount_field = IrField.search([('model', '=', LineModel),
                               ('name', '=', 'x_studio_amount')], limit=1)
if not amount_field:
    say("      x_studio_amount IS NOT A FIELD ON THIS MODEL.")
    say()
    say("      Studio's total formula reads item.x_studio_amount in a loop.")
    say("      Reading a field that is not there raises, and a stored compute")
    say("      that raises does not update - so every x_studio_total_amount on")
    say("      this database is the last value that computed successfully,")
    say("      however long ago that was.")
else:
    say("      x_studio_amount   %s" % amount_field.ttype)
    if amount_field.compute:
        say("      computed%s, depends on: %s"
            % (", stored" if amount_field.store else "",
               amount_field.depends or "(nothing declared)"))
        say("      code:")
        for line in (amount_field.compute or '').split('\n'):
            say("          %s" % line)
    elif amount_field.related:
        say("      related: %s" % amount_field.related)
    else:
        say("      typed by somebody")

say()
say("      every field on the line model, so nothing is assumed:")
for field in IrField.search([('model', '=', LineModel)], order='name'):
    if field.name in ('create_uid', 'create_date', 'write_uid', 'write_date',
                      'display_name', 'id'):
        continue
    how = "computed" if field.compute else (
        "related %s" % field.related if field.related else "typed")
    say("          %-42s %-10s %s" % (field.name[:42], field.ttype, how))

# ================================================================= TWO =======
title("TWO - the stored total against the lines it is meant to be", '-')

Lines = env[LineModel].sudo()                                    # noqa: F821
rows = Studio.with_context(active_test=False).search(
    [('x_studio_type_of_request_1', '=', 'SPC')])

has_amount = bool(amount_field)
agree_amount = differ_amount = 0
agree_qxp = differ_qxp = 0
examples = []

for row in rows:
    stored = g(row, 'x_studio_total_amount', 0.0) or 0.0
    items = g(row, 'x_studio_spc_item')
    if items is None:
        continue
    by_amount = 0.0
    by_qxp = 0.0
    for item in items:
        if has_amount:
            by_amount += g(item, 'x_studio_amount', 0.0) or 0.0
        quantity = g(item, 'x_studio_quantity', 0.0) or 0.0
        price = g(item, 'x_studio_unit_price', 0.0) or 0.0
        by_qxp += quantity * price
    if has_amount:
        if abs(stored - by_amount) < 0.01:
            agree_amount += 1
        else:
            differ_amount += 1
    if abs(stored - by_qxp) < 0.01:
        agree_qxp += 1
    else:
        differ_qxp += 1
        if len(examples) < 20:
            examples.append((row, stored, by_amount if has_amount else None,
                             by_qxp))

say("      %s certificate(s) looked at" % len(rows))
say()
if has_amount:
    say("      stored total equals the sum of x_studio_amount on  %s" % agree_amount)
    say("      differs on                                          %s" % differ_amount)
say("      stored total equals sum of quantity x unit price on %s" % agree_qxp)
say("      differs on                                          %s" % differ_qxp)

if examples:
    say()
    say("      %-30s %14s %14s %14s"
        % ("certificate", "stored", "sum(amount)", "sum(qty x price)"))
    for row, stored, by_amount, by_qxp in examples:
        say("      %-30s %14.2f %14s %14.2f"
            % ((g(row, 'x_name') or '')[:30], stored,
               "%.2f" % by_amount if by_amount is not None else "n/a", by_qxp))

say()
say("      A stored total that matches neither definition is a frozen number.")
say("      One that matches quantity x price is live and our sum of lines")
say("      should agree with it.")

# =============================================================== THREE =======
title("THREE - the two mechanisms our model does not have", '-')

prog = sum(1 for row in rows if g(row, 'x_studio_prog_pay', False))
openq = sum(1 for row in rows if g(row, 'x_studio_open_quotation', False))
no_retention = sum(1 for row in rows
                   if not g(row, 'x_studio_retention_deduction', True))
no_recovery = sum(1 for row in rows
                  if not g(row, 'x_studio_advance_deduction', True))
payable = sum(1 for row in rows if g(row, 'x_studio_payable_invoice', 0))

say()
say("      %4s of %s certificate(s) are on a progressive-payment contract"
    % (prog, len(rows)))
say("      %4s carry a payable-invoice figure" % payable)
say("      %4s are open quotation" % openq)
say("      %4s suppress retention (a line whose work done is 'Advance Payment')"
    % no_retention)
say("      %4s suppress advance recovery, by the same rule" % no_recovery)
say()
say("""      Ours computes the sub total from the certificate's own gross, always.
      Studio computes it from payable_invoice when the contract is on
      progressive payment - a figure derived from the contract value and a
      progressive percentage. If that count is large, our model is missing a
      mechanism and no import can supply it. If it is small, those
      certificates are a handful to be looked at by hand.""")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
