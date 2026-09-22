"""Our certificate against Studio's, record by record, in money.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/reconcile_spc.py

    SSC_TOLERANCE=0.01   how close counts as equal
    SSC_OUT=~/spc_reconciliation.md

Reads only.

The profile said our computed net payable is filled on 183 of 206
certificates, which is the right shape. It cannot say whether it is the right
number, because two lists sorted differently show two different first rows.

That question has to be answered before a page is drawn. A payment certificate
is what a client is asked to pay against; one that prints a net which differs
from the figure the subcontractor was actually paid is not a formatting
problem, it is a wrong document with a signature on it.

So this pairs each of our certificates with the Studio row it was imported
from - studio_ref_id, not a name match - and compares the money:

    ours                          Studio
    certificate_gross             x_studio_total_amount
    certificate_subtotal          x_studio_sub_total_amount
    certificate_vat               x_studio_vat_5
    certificate_retention         x_studio_retention_1
    certificate_advance_recovery  x_studio_advance_recovery
    certificate_penalty           x_studio_penalty_amount
    certificate_net               x_studio_net_payable_amount

Every difference is listed with both figures. A total that agrees on 183 rows
and disagrees on 7 is a much better thing to know than a total that agrees on
average.

And the gross is measured against TWO of Studio's numbers, because they are
not the same thing. x_studio_total_amount is stored by a formula that adds up
item.x_studio_amount - a field which is not on their line model - so it has
not recomputed since that field went, and 40 of the 206 no longer match their
own lines. The live figure is the sum of quantity x unit price on the lines as
they stand today, and that is the one worth agreeing with. Judging our work
against the frozen column would be marking it against a number nobody has
been paid.

It also counts the four things the profile suggests were never imported - the
tax invoice and its date and reference, and the certificate's own date - and
the certificates whose state is draft while an approver and an approval date
sit on them.
"""
import os

TOLERANCE = float(os.environ.get('SSC_TOLERANCE') or 0.01)
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/spc_reconciliation.md')

STUDIO = 'x_all_requests'

MONEY = [
    ('certificate_gross', 'x_studio_total_amount', "work done"),
    ('certificate_subtotal', 'x_studio_sub_total_amount', "sub total"),
    ('certificate_vat', 'x_studio_vat_5', "VAT"),
    ('certificate_retention', 'x_studio_retention_1', "retention"),
    ('certificate_advance_recovery', 'x_studio_advance_recovery',
     "advance recovery"),
    ('certificate_penalty', 'x_studio_penalty_amount', "penalty"),
    ('certificate_net', 'x_studio_net_payable_amount', "NET PAYABLE"),
]

# what the profile says is on one side and not the other
CARRIED = [
    ('tax_invoice', 'x_studio_tax_invoice', "the tax invoice itself"),
    ('tax_invoice_date', 'x_studio_tax_invoice_date', "its date"),
    ('invoice_ref', 'x_studio_invoice_ref_no', "its reference"),
    ('certificate_notes', 'x_studio_additio', "the notes on it"),
]

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


title("our certificates against the ones they were imported from")

if STUDIO not in env or 'ssc.request' not in env:                # noqa: F821
    say()
    say("  Both sides have to be on this database, and they are not.")
    finish()

Studio = env[STUDIO].sudo()                                      # noqa: F821
Request = env['ssc.request'].sudo()                              # noqa: F821

ours = Request.with_context(active_test=False).search(
    [('type_code', '=', 'SPC')])
say()
say("  %s certificate(s) on our side" % len(ours))

studio_by_id = {row.id: row for row in
                Studio.with_context(active_test=False).search(
                    [('x_studio_type_of_request_1', '=', 'SPC')])}
say("  %s on Studio's" % len(studio_by_id))

paired = [(rec, studio_by_id[rec.studio_ref_id])
          for rec in ours
          if rec.studio_ref_id and rec.studio_ref_id in studio_by_id]
say("  %s paired by studio_ref_id" % len(paired))
unpaired = len(ours) - len(paired)
if unpaired:
    say("  %s of ours have no Studio row to compare against" % unpaired)


def value_of(record, name):
    try:
        return record[name] or 0.0
    except Exception:
        return None


# ---------------------------------------------------------------- the money
title("the gross against Studio's two answers", '-')
say("""  stored  - x_studio_total_amount, frozen since x_studio_amount stopped
            being a field on their line model
  live    - the sum of quantity x unit price on their lines as they stand
""")

live_agree = live_differ = 0
live_rows = []
for rec, row in paired:
    live = 0.0
    items = row['x_studio_spc_item'] if 'x_studio_spc_item' in row else []
    for item in items or []:
        quantity = value_of(item, 'x_studio_quantity') or 0.0
        price = value_of(item, 'x_studio_unit_price') or 0.0
        live += quantity * price
    mine = value_of(rec, 'certificate_gross') or 0.0
    if abs(mine - live) <= TOLERANCE:
        live_agree += 1
    else:
        live_differ += 1
        live_rows.append((rec, mine, live, abs(mine - live)))

say("      ours against their LIVE lines:  %s agree, %s differ"
    % (live_agree, live_differ))
say()

# A certificate is right when it says what was signed. The stored column is
# what was printed and signed at the time; the live lines are what the lines
# say today, after whatever edits came later. Agreeing with either is an
# explanation. Agreeing with neither is the only figure that has no story
# behind it, and the one list a person has to read before a page is drawn.
neither = []
with_stored_only = with_live_only = with_both = 0
for rec, row in paired:
    live = 0.0
    items = row['x_studio_spc_item'] if 'x_studio_spc_item' in row else []
    for item in items or []:
        live += ((value_of(item, 'x_studio_quantity') or 0.0)
                 * (value_of(item, 'x_studio_unit_price') or 0.0))
    stored = value_of(row, 'x_studio_total_amount') or 0.0
    mine = value_of(rec, 'certificate_gross') or 0.0
    ok_live = abs(mine - live) <= TOLERANCE
    ok_stored = abs(mine - stored) <= TOLERANCE
    if ok_live and ok_stored:
        with_both += 1
    elif ok_live:
        with_live_only += 1
    elif ok_stored:
        with_stored_only += 1
    else:
        neither.append((rec, mine, stored, live))
say("      agree with both answers      %s" % with_both)
say("      with the live lines only     %s   (the stored figure went stale)" % with_live_only)
say("      with the stored figure only  %s   (a line was edited after signing)" % with_stored_only)
say("      with NEITHER                 %s" % len(neither))
if neither:
    say()
    say("      %-30s %14s %14s %14s" % ("certificate", "ours", "Studio stored", "Studio live"))
    for rec, mine, stored, live in sorted(neither, key=lambda r: -abs(r[1] - r[3])):
        say("      %-30s %14.2f %14.2f %14.2f" % ((rec.name or '')[:30], mine, stored, live))
say()
if live_rows:
    say("      %-30s %14s %14s %12s"
        % ("certificate", "ours", "Studio live", "gap"))
    for rec, mine, live, gap in sorted(live_rows, key=lambda r: -r[3])[:25]:
        say("      %-30s %14.2f %14.2f %12.2f"
            % ((rec.name or '')[:30], mine, live, gap))
    if len(live_rows) > 25:
        say("      ... and %s more" % (len(live_rows) - 25))

title("the money against the stored figures, field by field", '-')
say("  %-22s %6s %8s %8s   %s" % ("", "pairs", "agree", "differ", "worst gap"))
say()

differences = {}
for mine, theirs, label in MONEY:
    if mine not in Request._fields:
        say("      %-22s we have no such field" % label)
        continue
    agree, differ, worst, rows = 0, 0, 0.0, []
    for rec, row in paired:
        a = value_of(rec, mine)
        b = value_of(row, theirs)
        if a is None or b is None:
            continue
        gap = abs(a - b)
        if gap <= TOLERANCE:
            agree += 1
        else:
            differ += 1
            rows.append((rec, a, b, gap))
            worst = max(worst, gap)
    differences[label] = rows
    say("      %-22s %6s %8s %8s   %.2f"
        % (label, len(paired), agree, differ, worst))

# ------------------------------------------------------- where they disagree
for label, rows in differences.items():
    if not rows:
        continue
    title("%s: the %s that disagree" % (label, len(rows)), '-')
    say("      %-30s %14s %14s %12s" % ("request", "ours", "Studio", "gap"))
    for rec, a, b, gap in sorted(rows, key=lambda r: -r[3])[:25]:
        say("      %-30s %14.2f %14.2f %12.2f"
            % ((rec.name or '')[:30], a, b, gap))
    if len(rows) > 25:
        say("      ... and %s more" % (len(rows) - 25))

# --------------------------------------------------- what was never carried
title("what Studio holds and we do not", '-')
say("  Counted on the paired records only, so the two columns are about the")
say("  same certificates.")
say()
for mine, theirs, label in CARRIED:
    have_ours = have_theirs = 0
    known = mine in Request._fields
    for rec, row in paired:
        if known and value_of(rec, mine):
            have_ours += 1
        if value_of(row, theirs):
            have_theirs += 1
    say("      %-26s Studio %4s      ours %s"
        % (label, have_theirs,
           have_ours if known else "no such field on our side"))

# ------------------------------------------- a date on every one of theirs
if 'x_studio_date_1' in Studio._fields:
    theirs_dated = sum(1 for _rec, row in paired if value_of(row, 'x_studio_date_1'))
    ours_dated = sum(1 for rec, _row in paired if value_of(rec, 'date_request'))
    say()
    say("      %-26s Studio %4s      ours %s"
        % ("the certificate's date", theirs_dated, ours_dated))
    say("      x_studio_date_1 is filled on every Studio certificate. If the")
    say("      page is meant to carry the month the work was done, that is")
    say("      the column it comes from, and we have no field for it.")

# ------------------------------------------------- approved, but still draft
title("approved and still a draft", '-')
say("  A certificate with an approver and an approval date on it, whose state")
say("  says draft, is two answers to the question of whether it was approved.")
say()
odd = ours.filtered(lambda r: r.approver_id and r.state == 'draft')
say("      %s of %s" % (len(odd), len(ours)))
states = {}
for rec in ours:
    states[rec.state] = states.get(rec.state, 0) + 1
say()
say("      the states our certificates are in:")
for state in sorted(states, key=lambda s: -states[s]):
    say("          %-20s %s" % (state, states[state]))

# ------------------------------------------------------ the consultant email
title("the consultant's address, which is a project's and not a request's", '-')
say("""  x_studio_consultant_email and x_studio_consultant_re_email are filled on
  95 and 89 certificates and nowhere else - they are how a certificate reaches
  the consultant. Across the whole database they hold one distinct value each,
  which is a configuration somebody set once rather than data. Here is what is
  actually in them, per project, which decides where they belong.
""")
addresses = {}
for _rec, row in paired:
    for field_name in ('x_studio_consultant_email',
                       'x_studio_consultant_re_email'):
        if field_name not in Studio._fields:
            continue
        value = value_of(row, field_name)
        if not value:
            continue
        project = row.x_studio_which_project_.display_name \
            if 'x_studio_which_project_' in Studio._fields \
            and row.x_studio_which_project_ else "(no project)"
        addresses.setdefault((project, field_name), {})
        addresses[(project, field_name)][value] = \
            addresses[(project, field_name)].get(value, 0) + 1

for (project, field_name) in sorted(addresses):
    for value, count in sorted(addresses[(project, field_name)].items(),
                               key=lambda kv: -kv[1]):
        say("      %-40s %-30s %-28s %s"
            % (project[:40], field_name[9:], value[:28], count))
if not addresses:
    say("      nothing in either field on the paired certificates")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
