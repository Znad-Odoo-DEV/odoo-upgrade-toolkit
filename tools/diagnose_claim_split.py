"""Is our quantity the line's, repeated once per sector?

    odoo-bin shell --no-http --shell-interface=python \
        < tools/diagnose_claim_split.py

    SSC_OUT=~/claim_split.md

Reads only.

Forty-seven certificate lines carry a quantity different from Studio's, and
every difference printed so far is exactly four times:

    SPC0003   ours 188.00   Studio  47.00
    SPC0021   ours 115.00   Studio  28.75
    SPC0007   ours  44.00   Studio  11.00
    SPC0036   ours  19.00   Studio   4.75

Our line quantity is not typed. It is computed:

    quantity = sum(claim_ids.quantity)

because a certificate claims against sectors and never against an item as a
whole. So a line whose quantity reads four times Studio's is a line with four
sector claims, each carrying the whole of the line's quantity instead of its
share. Four sectors, four copies, four times the money.

This tests that against every differing line rather than the handful that fit
on a screen: for each, the ratio and the number of claims, and whether they
are the same number. If they are, the repair is one loop in the import and
nothing about the model changes. If some ratios do not match their claim
count, there is a second thing going on and it needs its own answer.

The two lines reading zero against 42 and 36 are asked about separately, since
a line with no claims at all is a different fault from one with too many.

It also settles the 134 Studio lines that never came across. They all printed
"(no certificate)", which is either the truth - orphans, as 2,311 of the bill
lines turned out to be - or my own tool failing to find the link. Every
many2one on that model is counted here, so the two cannot be confused.
"""
import os

OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/claim_split.md')

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


title("is our quantity the line's, counted once per sector?")

if STUDIO not in env or 'ssc.request' not in env:                # noqa: F821
    say("  Both sides have to be here.")
    finish()

Studio = env[STUDIO].sudo()                                      # noqa: F821
Request = env['ssc.request'].sudo()                              # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821

item_field = IrField.search([('model', '=', STUDIO),
                             ('name', '=', 'x_studio_spc_item')], limit=1)
LineModel = item_field.relation if item_field else None
if not LineModel or LineModel not in env:                        # noqa: F821
    say("  x_studio_spc_item does not resolve.")
    finish()

TheirLines = env[LineModel].sudo()                               # noqa: F821
ours = Request.with_context(active_test=False).search(
    [('type_code', '=', 'SPC')])
our_lines = ours.mapped('certificate_line_ids')

matches = mismatches = 0
no_claims = []
rows = []

for line in our_lines:
    if not line.studio_ref_id:
        continue
    theirs = TheirLines.browse(line.studio_ref_id).exists()
    if not theirs:
        continue
    mine = line.quantity or 0.0
    yours = g(theirs, 'x_studio_quantity', 0.0) or 0.0
    if abs(mine - yours) < 0.005:
        continue
    claims = len(line.claim_ids)
    if not claims:
        no_claims.append((line, mine, yours))
        continue
    ratio = (mine / yours) if yours else 0.0
    fits = yours and abs(ratio - claims) < 0.001
    if fits:
        matches += 1
    else:
        mismatches += 1
    rows.append((line, mine, yours, ratio, claims, fits))

say()
say("  %s line(s) whose quantity differs and which have sector claims"
    % (matches + mismatches))
say("  %s where ours is exactly the claim count times Studio's" % matches)
say("  %s where it is not" % mismatches)
say("  %s with no sector claim at all" % len(no_claims))

title("line by line", '-')
say("      %-28s %10s %10s %8s %7s  %s"
    % ("certificate", "ours", "Studio", "ratio", "claims", ""))
say()
for line, mine, yours, ratio, claims, fits in sorted(
        rows, key=lambda r: (r[5], -r[1])):
    say("      %-28s %10.2f %10.2f %8.3f %7s  %s"
        % ((line.request_id.name or '')[:28], mine, yours, ratio, claims,
           "" if fits else "<-- does not fit"))

if no_claims:
    title("the lines with no sector claim", '-')
    say("  Ours reads zero because there is nothing to add up. Studio has a")
    say("  quantity on them, so the claim rows were never made rather than")
    say("  made wrongly - a different repair from the ones above.")
    say()
    for line, mine, yours in no_claims:
        say("      %-30s ours %8.2f   Studio %8.2f   %s"
            % ((line.request_id.name or '')[:30], mine, yours,
               (line.name or '')[:30]))

# ---------------------------------------- and what a claim actually holds now
title("what the sector claims hold", '-')
claims = our_lines.mapped('claim_ids')
say("  %s claim(s) under %s line(s)" % (len(claims), len(our_lines)))
if claims:
    spread = {}
    for line in our_lines:
        spread[len(line.claim_ids)] = spread.get(len(line.claim_ids), 0) + 1
    say()
    say("      how many sectors a line is split across:")
    for count in sorted(spread):
        say("          %-4s sector(s)   on %s line(s)" % (count, spread[count]))
    say()
    identical = 0
    for line in our_lines:
        if len(line.claim_ids) < 2:
            continue
        quantities = line.claim_ids.mapped('quantity')
        if len(set(quantities)) == 1 and quantities[0]:
            identical += 1
    say("      %s line(s) with two or more sectors carry the SAME quantity on"
        % identical)
    say("      every one of them, which is what copying rather than splitting")
    say("      looks like from the outside.")

# ------------------------------------------- the 134 that never came across
title("the 134 Studio lines with no counterpart", '-')

parents = IrField.search([('model', '=', LineModel), ('ttype', '=', 'many2one')])
say("  every many2one on %s, and how many of its 863 rows fill it:" % LineModel)
say()
their_all = TheirLines.with_context(active_test=False).search([])
ours_refs = {line.studio_ref_id for line in our_lines if line.studio_ref_id}
never = their_all.filtered(lambda r: r.id not in ours_refs)
for field in parents:
    filled_all = sum(1 for row in their_all if g(row, field.name))
    filled_never = sum(1 for row in never if g(row, field.name))
    say("      %-42s %4s of 863     %4s of the %s that never came"
        % (field.name[:42], filled_all, filled_never, len(never)))

say()
say("  If the column pointing at %s is empty on all of them, they are" % STUDIO)
say("  orphans and were right to be left - the same as the 2,311 bill lines")
say("  that belonged to no bill. If it is filled, my tool failed to follow it")
say("  and 134 priced lines are missing from certificates that exist.")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
