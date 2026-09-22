"""The certificate lines, one against one, and where the advance belongs.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/reconcile_spc_lines.py

    SSC_OUT=~/spc_lines.md

Reads only.

The first guess about the money was wrong, and it was wrong usefully. Our
gross is larger than Studio's on 42 certificates and SMALLER on 31, so it is
not a quantity that was never reduced to this period - that error only goes
one way. What the same run did show is that Studio has 863 certificate lines
and we have 729. A hundred and thirty-four are not here.

So this stops guessing at totals and pairs the lines themselves, by
studio_ref_id. For each certificate it says how many lines each side has,
and for the ones that pair it compares quantity, unit price and amount. A
missing line and a wrong quantity are different repairs and the totals cannot
tell them apart.

It also answers the question left open about the advance. Ours reads
has_advance and advance_recovery_percent off the CONTRACT; Studio held them on
each CERTIFICATE, with three different percentages across 35 of them - 35, 30
and 50. If every certificate under one contract carries the same percentage,
the contract is where it belongs and the import simply never told it. If they
differ within a contract, then it is a fact about each claim and our model has
it in the wrong place - which is a change to the model, not to the import.

That is the distinction worth having before anything is written.
"""
import os

OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/spc_lines.md')

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


title("the certificate lines, one against one")

if STUDIO not in env or 'ssc.request' not in env:                # noqa: F821
    say("  Both sides have to be here.")
    finish()

Studio = env[STUDIO].sudo()                                      # noqa: F821
Request = env['ssc.request'].sudo()                              # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821

ours = Request.with_context(active_test=False).search(
    [('type_code', '=', 'SPC')])
studio_rows = Studio.with_context(active_test=False).search(
    [('x_studio_type_of_request_1', '=', 'SPC')])
studio_by_id = {row.id: row for row in studio_rows}

item_field = IrField.search([('model', '=', STUDIO),
                             ('name', '=', 'x_studio_spc_item')], limit=1)
if not item_field or item_field.relation not in env:             # noqa: F821
    say("  x_studio_spc_item does not resolve to a model on this database.")
    finish()

LineModel = item_field.relation
say("  Studio's lines are %s" % LineModel)

TheirLines = env[LineModel].sudo()                               # noqa: F821
their_all = TheirLines.with_context(active_test=False).search([])
our_all = ours.mapped('certificate_line_ids')
say("  %s line(s) on Studio's side, %s on ours" % (len(their_all), len(our_all)))

ours_by_ref = {}
for line in our_all:
    if line.studio_ref_id:
        ours_by_ref.setdefault(line.studio_ref_id, line)
say("  %s of ours carry a studio_ref_id" % len(ours_by_ref))

# ------------------------------------------------------ which columns to read
numeric = {f.name: f for f in IrField.search(
    [('model', '=', LineModel), ('ttype', 'in', ('float', 'monetary'))])}
say()
say("  the numeric columns on their line model: %s"
    % ", ".join(sorted(numeric)) or "none")

QTY = 'x_studio_quantity' if 'x_studio_quantity' in numeric else None
PRICE = 'x_studio_unit_price' if 'x_studio_unit_price' in numeric else None

# ------------------------------------------------------------- missing lines
title("lines that are on one side and not the other", '-')

their_ids = set(their_all.ids)
our_refs = set(ours_by_ref)
never_came = sorted(their_ids - our_refs)
no_origin = [line for line in our_all if not line.studio_ref_id]
orphaned = sorted(our_refs - their_ids)

say("      %s Studio line(s) have no counterpart here" % len(never_came))
say("      %s of our lines carry no Studio id at all" % len(no_origin))
say("      %s of ours name a Studio line that is not an SPC item"
    % len(orphaned))

if never_came:
    say()
    say("      the first of the ones that never came, with the certificate")
    say("      they belong to:")
    say()
    for line in TheirLines.browse(never_came[:25]):
        parent = None
        for field in IrField.search([('model', '=', LineModel),
                                     ('ttype', '=', 'many2one'),
                                     ('relation', '=', STUDIO)]):
            parent = g(line, field.name)
            break
        certificate = parent.display_name if parent else "(no certificate)"
        say("          %-8s %-34s qty %-10s price %s"
            % (line.id, certificate[:34],
               g(line, QTY, '') if QTY else '',
               g(line, PRICE, '') if PRICE else ''))
    if len(never_came) > 25:
        say("          ... and %s more" % (len(never_came) - 25))

# ------------------------------------------------------- the paired ones
title("the lines that did pair", '-')

checks = [('quantity', QTY), ('unit_price', PRICE)]
for mine, theirs in checks:
    if not theirs:
        continue
    agree = differ = 0
    worst = []
    for ref, line in ours_by_ref.items():
        their_line = TheirLines.browse(ref).exists()
        if not their_line:
            continue
        a = g(line, mine, 0.0) or 0.0
        b = g(their_line, theirs, 0.0) or 0.0
        if abs(a - b) < 0.005:
            agree += 1
        else:
            differ += 1
            worst.append((line, a, b, abs(a - b)))
    say()
    say("      %-14s %s agree, %s differ" % (mine, agree, differ))
    for line, a, b, gap in sorted(worst, key=lambda r: -r[3])[:15]:
        say("          %-34s ours %14.2f   Studio %14.2f"
            % ((line.request_id.name or '')[:34], a, b))
    if len(worst) > 15:
        say("          ... and %s more" % (len(worst) - 15))

# ------------------------------------------- is the advance a contract's fact?
title("does the advance percentage belong to the contract or the certificate?",
      '-')

by_contract = {}
for row in studio_rows:
    perc = g(row, 'x_studio_advance_perc', 0)
    if not perc:
        continue
    contract = g(row, 'x_studio_contract')
    key = contract.display_name if contract else "(no contract)"
    by_contract.setdefault(key, {})
    by_contract[key][perc] = by_contract[key].get(perc, 0) + 1

steady = varying = 0
say()
for key in sorted(by_contract):
    values = by_contract[key]
    if len(values) == 1:
        steady += 1
    else:
        varying += 1
    say("      %-46s %s"
        % (key[:46],
           ", ".join("%s%% on %s" % (v, c)
                     for v, c in sorted(values.items(), key=lambda kv: -kv[1]))))

say()
say("      %s contract(s) use one percentage throughout" % steady)
say("      %s use more than one" % varying)
say()
if varying:
    say("      ---> more than one percentage under a single contract means the")
    say("           advance recovery is a fact about each certificate, and our")
    say("           model reads it off the contract. That is a change to the")
    say("           model, not a gap in the import.")
else:
    say("      ---> every contract uses one percentage throughout, so the")
    say("           contract is where it belongs and the import simply never")
    say("           told it. That is a repair to the import alone.")

# ------------------------------------------------- and the retention likewise
title("and the retention percentage", '-')
by_contract_ret = {}
for row in studio_rows:
    perc = g(row, 'x_studio_ret_perc', 0)
    if not perc:
        continue
    contract = g(row, 'x_studio_contract')
    key = contract.display_name if contract else "(no contract)"
    by_contract_ret.setdefault(key, {})
    by_contract_ret[key][perc] = by_contract_ret[key].get(perc, 0) + 1
say()
for key in sorted(by_contract_ret):
    values = by_contract_ret[key]
    say("      %-46s %s"
        % (key[:46],
           ", ".join("%s on %s" % (v, c)
                     for v, c in sorted(values.items(), key=lambda kv: -kv[1]))))

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
