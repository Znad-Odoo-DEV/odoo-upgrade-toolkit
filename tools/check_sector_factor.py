"""The factor on a sector row, and the rule that switches deductions off.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/check_sector_factor.py

    SSC_OUT=~/sector_factor.md

Reads only.

SPC0003 answered both of the remaining questions at once, and this counts the
answers across all 206 before either becomes code.

THE FACTOR. Studio's sector rows carry x_studio_factor, 4.0 on every one of
the eighteen under that line. Their quantities are 8, 24, 8, 24, 3, 9 ... and
they add to 188, which is exactly what our claims add to. Studio's line
quantity is 47, and 188 / 4 = 47.

So the sector rows count pieces - Block A's Ground Floor, Block A's 1st Floor,
and so on - and the line is priced in a unit worth four of them. 47 at 4,000
is 188,000. Our import took the piece counts and never applied the factor,
which is the whole of the four.

Before that becomes a division somewhere, two things have to be true: the
factor has to be constant within a line, or dividing a sum by one of them is
meaningless; and it has to be knowable per line rather than per certificate.

THE SUPPRESSION. That same line's work done reads 'Advance Payment', and
Studio's retention and advance recovery on that certificate are both zero -
its rule switches both off when any line says that. Ours deducted 75,200 and
225,600 on it. So an advance-payment certificate is being deducted twice over
in our data, and the rule is not a rounding matter.

This counts how many lines and certificates that covers, and what
x_studio_work_done actually points at, since our line has no equivalent field
and one will have to be added.
"""
import os

OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/sector_factor.md')

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
HERE = STUDIO in env                                             # noqa: F821
if not HERE:
    say("  %s is not on this database." % STUDIO)
    finish()

Studio = env[STUDIO].sudo()                                      # noqa: F821
item_field = IrField.search([('model', '=', STUDIO),
                             ('name', '=', 'x_studio_spc_item')], limit=1)
LineModel = item_field.relation if item_field else None
if not LineModel or LineModel not in env:                        # noqa: F821
    say("  x_studio_spc_item does not resolve.")
    finish()

rows = Studio.with_context(active_test=False).search(
    [('x_studio_type_of_request_1', '=', 'SPC')])

title("the factor on the sector rows")

lines_seen = 0
constant = varying = no_factor = 0
factors = {}
mismatched = []

for row in rows:
    for item in g(row, 'x_studio_spc_item') or []:
        lines_seen += 1
        sectors = g(item, 'x_studio_sectors_1') or []
        if not sectors:
            continue
        values = set()
        total = 0.0
        for sector in sectors:
            factor = g(sector, 'x_studio_factor', 0.0) or 0.0
            values.add(factor)
            total += g(sector, 'x_studio_quantity', 0.0) or 0.0
        if not values or values == {0.0}:
            no_factor += 1
            continue
        if len(values) > 1:
            varying += 1
            continue
        constant += 1
        factor = list(values)[0]
        factors[factor] = factors.get(factor, 0) + 1

        # and does dividing actually reproduce their line quantity?
        theirs = g(item, 'x_studio_quantity', 0.0) or 0.0
        if factor and abs(total / factor - theirs) > 0.005:
            mismatched.append((row, item, total, factor, theirs))

say()
say("      %s line(s) across %s certificate(s)" % (lines_seen, len(rows)))
say("      %s line(s) whose sector rows all carry the same factor" % constant)
say("      %s where the factor differs between sector rows" % varying)
say("      %s where there is no factor at all" % no_factor)
say()
say("      the factors in use:")
for value in sorted(factors, key=lambda v: -factors[v]):
    say("          %-10s on %s line(s)" % (value, factors[value]))

say()
say("      %s line(s) where sum(sector quantity) / factor does NOT equal"
    % len(mismatched))
say("      Studio's own line quantity - if this is zero, the division is")
say("      exactly what their line means and can be relied on.")
for row, item, total, factor, theirs in mismatched[:20]:
    say("          %-28s sum %10.2f / %-6s = %10.4f   theirs %s"
        % ((g(row, 'x_name') or '')[:28], total, factor,
           total / factor if factor else 0, theirs))
if len(mismatched) > 20:
    say("          ... and %s more" % (len(mismatched) - 20))

# ------------------------------------------------------------ the suppression
title("the rule that switches retention and recovery off", '-')

work_field = IrField.search([('model', '=', LineModel),
                             ('name', '=', 'x_studio_work_done')], limit=1)
if work_field:
    say("      x_studio_work_done points at %s" % work_field.relation)
    kinds = {}
    for row in rows:
        for item in g(row, 'x_studio_spc_item') or []:
            work = g(item, 'x_studio_work_done')
            label = work.display_name if work else "(none)"
            kinds[label] = kinds.get(label, 0) + 1
    say()
    say("      what the lines say the work is:")
    for label in sorted(kinds, key=lambda k: -kinds[k])[:20]:
        say("          %-46s %s line(s)" % (label[:46], kinds[label]))

advance_certificates = []
for row in rows:
    for item in g(row, 'x_studio_spc_item') or []:
        work = g(item, 'x_studio_work_done')
        if work and (g(work, 'x_name') or '') == 'Advance Payment':
            advance_certificates.append(row)
            break

say()
say("      %s certificate(s) have a line whose work done is 'Advance Payment'"
    % len(advance_certificates))
say("      On those, Studio charges no retention and recovers no advance.")

if advance_certificates:
    Request = env['ssc.request'].sudo()                          # noqa: F821
    ours_by_ref = {rec.studio_ref_id: rec for rec in
                   Request.with_context(active_test=False).search(
                       [('type_code', '=', 'SPC')])}
    say()
    say("      what we currently deduct on them:")
    say("      %-30s %14s %14s" % ("certificate", "retention", "recovery"))
    charged = 0
    for row in advance_certificates:
        rec = ours_by_ref.get(row.id)
        if not rec:
            continue
        retention = rec.certificate_retention or 0.0
        recovery = rec.certificate_advance_recovery or 0.0
        if retention or recovery:
            charged += 1
        say("      %-30s %14.2f %14.2f"
            % ((rec.name or '')[:30], retention, recovery))
    say()
    say("      %s of them are being deducted where Studio deducts nothing."
        % charged)

title("what this decides")
say("""  If the factor is constant within a line and the division reproduces
  Studio's quantity every time, then our certificate line needs a factor and
  our claim quantities are piece counts - a small, exact change.

  If it varies within a line, the factor is a property of the sector row and
  not of the line, and the model has to hold it there instead.

  The suppression is the same shape of question already answered: our line has
  no 'work done', so one has to be added before the rule can be written. What
  it points at is printed above.
""")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
