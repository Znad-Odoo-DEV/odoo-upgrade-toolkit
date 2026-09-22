"""Why our certificates say a different number, tested one claim at a time.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/diagnose_spc_gap.py

    SSC_OUT=~/spc_diagnosis.md

Reads only. Changes nothing, proposes nothing.

The reconciliation found 74 of 206 certificates whose net payable differs from
the figure Studio holds, the worst by 5.3 million. The differences are not
scattered - they have shapes - and a shape suggests a cause. This tests four
guesses about those causes, so that a fix is applied to something that was
demonstrated rather than to something that sounded right.

Each section prints the evidence for and against. A guess that fails here is
worth more than one that passes, because it stops a repair being made to a
part that was never broken.

    ONE     our gross is the whole contract, not this period's work
            Studio's total is per certificate; ours sums the lines. If the
            import put the agreed quantity on the line instead of the quantity
            done this month, every certificate reads as the whole job.

    TWO     retention is a hundred times too small
            ours = gross x 0.001 on the three that were checked by hand.
            x_studio_ret_perc holds 0.1 meaning a tenth; our contract field is
            a percentage, where a tenth is written 10.

    THREE   advance recovery is zero on all 25 that should have one
            ours reads has_advance and advance_recovery_percent off the
            CONTRACT. Studio held the advance on the CERTIFICATE. If the
            contracts were never told, the recovery is nothing everywhere.

    FOUR    penalty is zero on all 9 that had one
            has_penalty and certificate_penalty are typed on the request and
            nothing carried them.
"""
import os

OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/spc_diagnosis.md')

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


def verdict(text):
    say()
    say("      ---> %s" % text)


def finish():
    with open(OUT, 'w', encoding='utf-8') as handle:
        handle.write("\n".join(report))
    print("\nwritten to %s" % OUT)
    raise SystemExit


title("why the certificates disagree")

if STUDIO not in env or 'ssc.request' not in env:                # noqa: F821
    say("  Both sides have to be here.")
    finish()

Studio = env[STUDIO].sudo()                                      # noqa: F821
Request = env['ssc.request'].sudo()                              # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821

ours = Request.with_context(active_test=False).search(
    [('type_code', '=', 'SPC')])
studio_by_id = {row.id: row for row in
                Studio.with_context(active_test=False).search(
                    [('x_studio_type_of_request_1', '=', 'SPC')])}
paired = [(rec, studio_by_id[rec.studio_ref_id]) for rec in ours
          if rec.studio_ref_id in studio_by_id]
say("  %s pair(s) to look at" % len(paired))


def g(record, name, default=None):
    try:
        return record[name]
    except Exception:
        return default


# =============================================================== ONE =========
title("ONE - is our gross the whole contract rather than this period?", '-')

Line = ours.mapped('certificate_line_ids')
say("  %s line(s) on our side" % len(Line))
if Line:
    fields_here = Line._fields
    say()
    say("  what a line holds, and whether the three quantities differ:")
    same_as_agreed = both = 0
    for line in Line:
        agreed = g(line, 'quantity_agreed', None)
        if agreed is None:
            continue
        both += 1
        if abs((line.quantity or 0.0) - (agreed or 0.0)) < 0.0001:
            same_as_agreed += 1
    if both:
        say("      %s of %s lines have quantity equal to quantity_agreed"
            % (same_as_agreed, both))
        say("      %s carry a quantity different from the agreed one"
            % (both - same_as_agreed))
    before = sum(1 for line in Line if g(line, 'quantity_certified_before', 0))
    say("      %s of %s lines say anything was certified before this one"
        % (before, len(Line)))
    say("      ('quantity_agreed' in the model: %s, "
        "'quantity_certified_before': %s)"
        % ('quantity_agreed' in fields_here,
           'quantity_certified_before' in fields_here))

# and the Studio line model, to see what its quantity meant
spc_item = IrField.search([('model', '=', STUDIO),
                           ('name', '=', 'x_studio_spc_item')], limit=1)
if spc_item and spc_item.relation in env:                        # noqa: F821
    say()
    say("  Studio's line model is %s" % spc_item.relation)
    their_lines = env[spc_item.relation].sudo().with_context(     # noqa: F821
        active_test=False).search([])
    say("      %s line(s)" % len(their_lines))
    numeric = IrField.search([('model', '=', spc_item.relation),
                              ('ttype', 'in', ('float', 'monetary'))])
    for field in numeric:
        filled = sum(1 for row in their_lines if g(row, field.name, 0))
        if not filled:
            continue
        samples = [str(g(row, field.name))[:12] for row in their_lines[:3]]
        say("      %-42s %4s filled   e.g. %s"
            % (field.name[:42], filled, " | ".join(samples)))

worse = sum(1 for rec, row in paired
            if (rec.certificate_gross or 0) > (g(row, 'x_studio_total_amount', 0) or 0) + 0.01)
smaller = sum(1 for rec, row in paired
              if (rec.certificate_gross or 0) + 0.01 < (g(row, 'x_studio_total_amount', 0) or 0))
say()
say("      ours is LARGER than Studio's on  %s" % worse)
say("      ours is SMALLER than Studio's on %s" % smaller)
verdict("if ours is larger nearly every time, this is the direction of a "
        "quantity that was never reduced to this period")

# =============================================================== TWO =========
title("TWO - is retention a hundred times too small?", '-')

exact = off_by_hundred = other = 0
for rec, _row in paired:
    gross = rec.certificate_gross or 0.0
    held = rec.certificate_retention or 0.0
    if not gross or not held:
        continue
    ratio = held / gross
    if abs(ratio - 0.001) < 0.00005:
        off_by_hundred += 1
    elif abs(ratio - 0.1) < 0.005:
        exact += 1
    else:
        other += 1
say("      %s certificate(s) hold exactly a thousandth of the gross" % off_by_hundred)
say("      %s hold a tenth, which is what 10%% means" % exact)
say("      %s hold something else" % other)

Contract = env.get('ssc.subcontract')                            # noqa: F821
if Contract is not None:
    contracts = Contract.sudo().search([('retention_percent', '!=', 0)])
    values = {}
    for contract in contracts:
        values[contract.retention_percent] = \
            values.get(contract.retention_percent, 0) + 1
    say()
    say("      what our contracts hold in retention_percent:")
    for value in sorted(values, key=lambda v: -values[v])[:10]:
        say("          %-12s on %s contract(s)" % (value, values[value]))
    say()
    say("      what Studio held in x_studio_ret_perc on the certificates:")
    theirs = {}
    for _rec, row in paired:
        value = g(row, 'x_studio_ret_perc', 0)
        if value:
            theirs[value] = theirs.get(value, 0) + 1
    for value in sorted(theirs, key=lambda v: -theirs[v])[:10]:
        say("          %-12s on %s certificate(s)" % (value, theirs[value]))
verdict("a field meaning 'percent' holding 0.1 is a tenth of a percent, and "
        "the office means a tenth")

# ============================================================= THREE =========
title("THREE - why is advance recovery zero?", '-')

if Contract is not None:
    total = Contract.sudo().search_count([])
    with_advance = Contract.sudo().search_count([('has_advance', '=', True)])
    say("      %s of %s contract(s) say they carry an advance"
        % (with_advance, total))
    recoveries = Contract.sudo().search(
        [('advance_recovery_percent', '!=', 0)])
    say("      %s contract(s) have an advance recovery percentage"
        % len(recoveries))
else:
    say("      ssc.subcontract is not on this database")

their_advance = sum(1 for _rec, row in paired if g(row, 'x_studio_advance', False))
their_perc = {}
for _rec, row in paired:
    value = g(row, 'x_studio_advance_perc', 0)
    if value:
        their_perc[value] = their_perc.get(value, 0) + 1
say()
say("      %s certificate(s) in Studio are ticked as having an advance"
    % their_advance)
say("      the percentages Studio held on them:")
for value in sorted(their_perc, key=lambda v: -their_perc[v])[:10]:
    say("          %-12s on %s certificate(s)" % (value, their_perc[value]))
verdict("ours reads the advance off the contract; Studio held it on the "
        "certificate - so the question is which of the two is the truth about "
        "this business, not merely where to copy it")

# ============================================================== FOUR =========
title("FOUR - the penalties", '-')
theirs_penalty = [(rec, g(row, 'x_studio_penalty_amount', 0),
                   g(row, 'x_studio_penalty_reason', ''))
                  for rec, row in paired if g(row, 'x_studio_penalty_amount', 0)]
say("      %s certificate(s) carried a penalty in Studio" % len(theirs_penalty))
ours_penalty = sum(1 for rec, _row in paired if rec.certificate_penalty)
ours_flag = sum(1 for rec, _row in paired if rec.has_penalty)
say("      %s have an amount on our side, %s have the box ticked"
    % (ours_penalty, ours_flag))
say()
for rec, amount, reason in theirs_penalty:
    say("          %-30s %12.2f   %s"
        % ((rec.name or '')[:30], amount, (reason or '')[:40]))

title("what is worth saying about all of this")
say("""  Nothing here is a fault in the certificate model. Every one of these is
  the import putting a number in a field that means something else, or not
  putting it anywhere at all - and the model then computing correctly from
  what it was given.

  Which is why the page was not drawn first. A certificate printing 6,070,761
  where the subcontractor was paid 750,214 is not a formatting problem.
""")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
