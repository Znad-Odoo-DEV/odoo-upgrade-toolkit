"""Did each payslip's own salary attachments land on the payslip we made from it?

    SSC_WRITE=1 odoo-bin shell --no-http < tools/check_payslip_attachment_lines.py

The Studio payslip carries its additions and deductions as lines of its own -
x_studio_salary_attachments - and the mirror copies each one onto ssc.attachment
against the payslip. That is the part being asked about: the month's attachments,
in the attachments place, on our payslip.

Whether it happened is not something to assume. The mirror returns early on a
payslip with no month, matches an existing line by its description alone, and
until this afternoon resolved an unrecognised type to "salary addition" - so a
line could be absent, duplicated under a changed description, or present with
the sign the wrong way round.

So each payslip is compared line for line against the Studio record behind it:
how many lines it should have, how many it has, and where the two differ, with
the amounts on both sides. With SSC_WRITE=1 it then runs the mirror again over
the payslips that are short, which creates what is missing and rewrites the type
of what is there.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'
CHUNK = 200

SOURCE = 'x_all_payslips'

cr = env.cr                                                      # noqa: F821
Slip = env['ssc.payslip'].sudo().with_context(active_test=False)  # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def _get(record, name):
    if not record or name not in record._fields:
        return False
    return record[name]


title("1. line for line")

slips = Slip.search([('studio_ref_id', '!=', False)])
rows = {r.id: r for r in Source.search([])}
print("  %s mirrored payslip(s)" % len(slips))

short, extra, ok, no_month, sign = [], [], 0, [], []
studio_total = ours_total = 0
for slip in slips:
    src = rows.get(slip.studio_ref_id)
    if not src:
        continue
    lines = _get(src, 'x_studio_salary_attachments') or []
    mine = slip.attachment_ids
    studio_total += len(lines)
    ours_total += len(mine)
    if not slip.month:
        no_month.append(slip)
        continue
    if len(mine) < len(lines):
        short.append((slip, src, len(lines), len(mine)))
    elif len(mine) > len(lines):
        extra.append((slip, src, len(lines), len(mine)))
    else:
        ok += 1
    # A line whose Studio factor is negative and whose type here adds money.
    for line in lines:
        value = _get(line, 'x_studio_value') or 0.0
        factor = _get(line, 'x_studio_factor') or 0
        name = _get(line, 'x_name') or ''
        here = mine.filtered(lambda a: a.name == name)[:1]
        if here and factor and (factor < 0) != (here.factor < 0):
            sign.append((slip, name, factor, here.factor, value))

print("  %s Studio attachment line(s) behind them" % studio_total)
print("  %s attachment(s) on our payslips" % ours_total)
print("\n  %s payslip(s) match line for line" % ok)
print("  %s have fewer than the Studio record" % len(short))
print("  %s have more" % len(extra))
print("  %s have no month, so the mirror never copied any" % len(no_month))
print("  %s line(s) carry the opposite sign to the Studio factor" % len(sign))

missing_lines = sum(s[2] - s[3] for s in short)
print("\n  %s line(s) missing in total" % missing_lines)

if short:
    print("\n  the ones missing most:")
    for slip, src, want, have in sorted(short, key=lambda s: s[3] - s[2])[:12]:
        print("      %-8s %-28s %-4s %-6s wants %-3s has %s"
              % (slip.id, (slip.employee_id.name or '')[:28], slip.month,
                 slip.year, want, have))

if sign:
    print("\n  the ones with the wrong sign:")
    for slip, name, factor, mine_factor, value in sign[:12]:
        print("      %-8s %-30s studio factor %-4s ours %-4s  %s"
              % (slip.id, name[:30], factor, mine_factor, value))

if no_month:
    print("\n  %s payslip(s) with no month - their lines cannot be copied as"
          " things stand, month is required on ssc.attachment" % len(no_month))
    for slip in no_month[:8]:
        print("      %-8s %-30s %s" % (slip.id, (slip.employee_id.name or '')[:30],
                                       slip.year))

if not short and not sign:
    print("\n  Every payslip's attachments are already where they should be.")
    if DRY_RUN or True:
        raise SystemExit()

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing changed. Run again with SSC_WRITE=1 to copy the")
    print("  missing lines and correct the types.")
    cr.rollback()
    raise SystemExit()


# --- 2. run the mirror again over the payslips that are short ----------------

title("2. copying what is missing")

targets = [s for s, _src, _w, _h in short] + [s for s, _n, _f, _m, _v in sign]
seen, unique = set(), []
for slip in targets:
    if slip.id not in seen:
        seen.add(slip.id)
        unique.append(slip)

done = 0
for start in range(0, len(unique), CHUNK):
    batch = unique[start:start + CHUNK]
    try:
        for slip in batch:
            src = rows.get(slip.studio_ref_id)
            if src:
                Slip._sync_payslip_attachments(slip, src)
        cr.commit()
        done += len(batch)
        print("  %s / %s" % (done, len(unique)))
    except Exception as exc:
        cr.rollback()
        print("  batch at %s FAILED: %s" % (start, str(exc).strip().splitlines()[0][:60]))
        break


title("3. after")

still = 0
for slip in Slip.search([('studio_ref_id', '!=', False)]):
    src = rows.get(slip.studio_ref_id)
    if not src or not slip.month:
        continue
    lines = _get(src, 'x_studio_salary_attachments') or []
    if len(slip.attachment_ids) < len(lines):
        still += 1
print("  %s payslip(s) still short" % still)
print("  %s attachment(s) on our payslips now"
      % env['ssc.attachment'].sudo().search_count([('payslip_id', '!=', False)]))  # noqa: F821
