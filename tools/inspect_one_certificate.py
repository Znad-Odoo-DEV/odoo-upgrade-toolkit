"""One certificate, both sides, every row. No summaries and no guessing.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/inspect_one_certificate.py

    SSC_NAME=SSC/ARJ-672/SPC0003    which one (matched on either side's name)
    SSC_OUT=~/one_certificate.md

Reads only.

Four inferences from aggregate numbers, three of them wrong. So this one looks
at a single record and prints everything on it, on both sides, and draws no
conclusion at all.

SPC0003 is the default because its arithmetic is the clearest statement of
what is left:

    ours                              752,000
    Studio, quantity x unit price     188,000
    Studio, stored total               56,400

The stored total is frozen - x_studio_amount is not a field on their line
model, so the formula that maintains it has been reading nothing. The live
figure is 188,000, and ours is exactly four times it. That factor of four is
the whole remaining fault in the gross, and every other difference - the
retention, the advance recovery, the VAT, the net - is that same four carried
through the arithmetic.

Our line quantity is sum(claim_ids.quantity). Studio's line quantity is also
computed, and their line carries x_studio_sectors_1. So both sides split a
line across sectors, and the answer is in how those two sets of sector rows
differ. Printed here, in full, side by side.
"""
import os

NAME = os.environ.get('SSC_NAME') or 'SSC/ARJ-672/SPC0003'
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/one_certificate.md')

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
# An empty recordset is falsy, and env[model] IS an empty recordset. Writing
# `if Studio` below meant the Studio half of this tool never ran and the page
# said "not found" about a record the reconciliation had already paired.
STUDIO_HERE = STUDIO in env                                      # noqa: F821
Studio = env[STUDIO].sudo() if STUDIO_HERE else None             # noqa: F821
Request = env['ssc.request'].sudo()                              # noqa: F821

title("everything about %s" % NAME)

ours = Request.with_context(active_test=False).search(
    [('type_code', '=', 'SPC'), ('name', '=', NAME)], limit=1)
if not ours:
    ours = Request.with_context(active_test=False).search(
        [('type_code', '=', 'SPC'), ('name', 'like', NAME)], limit=1)
if not ours:
    say("  no certificate of ours is called that")
    finish()

theirs = (Studio.browse(ours.studio_ref_id).exists()
          if STUDIO_HERE and ours.studio_ref_id else None)

say("  ours    %s   (id %s)" % (ours.name, ours.id))
say("  Studio  %s   (id %s)"
    % (g(theirs, 'x_name', '(none)') if theirs else "(not found)",
       ours.studio_ref_id))

# ------------------------------------------------------------- the money side
title("the money on each side", '-')
pairs = [
    ('certificate_gross', 'x_studio_total_amount', "work done / total"),
    ('certificate_retention', 'x_studio_retention_1', "retention"),
    ('certificate_advance_recovery', 'x_studio_advance_recovery', "recovery"),
    ('certificate_penalty', 'x_studio_penalty_amount', "penalty"),
    ('certificate_subtotal', 'x_studio_sub_total_amount', "sub total"),
    ('certificate_vat', 'x_studio_vat_5', "VAT"),
    ('certificate_net', 'x_studio_net_payable_amount', "net payable"),
]
say("      %-22s %16s %16s" % ("", "ours", "Studio (stored)"))
for mine, yours, label in pairs:
    say("      %-22s %16.2f %16.2f"
        % (label, g(ours, mine, 0.0) or 0.0,
           (g(theirs, yours, 0.0) or 0.0) if theirs else 0.0))

if theirs:
    live = 0.0
    for item in g(theirs, 'x_studio_spc_item') or []:
        live += (g(item, 'x_studio_quantity', 0.0) or 0.0) * \
                (g(item, 'x_studio_unit_price', 0.0) or 0.0)
    say()
    say("      %-22s %16s %16.2f"
        % ("Studio, live q x price", "", live))
    gross = g(ours, 'certificate_gross', 0.0) or 0.0
    if live:
        say("      %-22s %16s %16.3f"
            % ("ours / live", "", gross / live))

# ------------------------------------------------------------------ our lines
title("our lines, and the sector claims under each", '-')
for line in ours.certificate_line_ids:
    say()
    say("      line %-6s %-44s" % (line.line_no or line.id,
                                   (line.name or '')[:44]))
    say("          quantity %-12s unit price %-12s amount %s"
        % (line.quantity, line.unit_price, line.amount))
    say("          studio_ref_id %s" % line.studio_ref_id)
    if not line.claim_ids:
        say("          no sector claims - which is why the quantity is zero")
        continue
    say("          %-30s %12s %12s %12s"
        % ("sector", "quantity", "agreed", "before"))
    for claim in line.claim_ids:
        sector = g(claim, 'sector_id')
        say("          %-30s %12s %12s %12s"
            % ((sector.display_name if sector else '(none)')[:30],
               g(claim, 'quantity', ''), g(claim, 'quantity_agreed', ''),
               g(claim, 'quantity_certified_before', '')))
    say("          the claims add up to %s"
        % sum(line.claim_ids.mapped('quantity')))

# --------------------------------------------------------------- their lines
if theirs:
    title("Studio's lines, and the sector rows under each", '-')
    items = g(theirs, 'x_studio_spc_item') or []
    if not items:
        say("      none")
    for item in items:
        say()
        say("      line %-6s %-44s"
            % (g(item, 'x_studio_sl_no', item.id),
               (g(item, 'x_name') or '')[:44]))
        say("          quantity %-12s unit price %-12s"
            % (g(item, 'x_studio_quantity', ''),
               g(item, 'x_studio_unit_price', '')))
        say("          id %s   work done: %s" % (
            item.id, (g(item, 'x_studio_work_done').display_name
                      if g(item, 'x_studio_work_done') else '')))
        sectors = g(item, 'x_studio_sectors_1') or []
        if not sectors:
            say("          no sector rows")
            continue
        say("          %s sector row(s):" % len(sectors))
        numeric = IrField.search([('model', '=', sectors._name),
                                  ('ttype', 'in', ('float', 'monetary',
                                                   'integer'))])
        say("          %-30s %s"
            % ("sector", "  ".join(f.name[:16] for f in numeric)))
        for sector in sectors:
            values = "  ".join("%-16s" % (g(sector, f.name, '') or 0)
                               for f in numeric)
            say("          %-30s %s"
                % ((sector.display_name or '')[:30], values))

title("what to look at")
say("""  The two sector lists. Ours sums to the line's quantity by construction;
  theirs is what our claim rows were made from. If our claims carry a number
  four times theirs, the import multiplied. If our claims carry the same
  numbers but there are four times as many rows, it duplicated. If the sector
  rows on their side hold several columns and the import read the wrong one,
  that will be visible here too - and none of those three has been ruled out
  by anything counted so far.
""")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
