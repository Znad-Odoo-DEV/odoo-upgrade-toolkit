"""The ssc adjustment total fell and nothing I ran touched the ssc side.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null \
        < tools/probe_ssc_adjustment_drop.py

Between two runs of reconcile_payrolls.py the ssc adjustment total moved:

    ROYAL ARROW   2,471.22  ->    345.22    -2,126.00
    SAUD          6,927.66  ->  1,951.66    -4,976.00

with the same 52 and 189 matched employees on both runs. Everything applied in
between was on the native side - thirty three payslips cancelled and deleted,
thirty two salary rules patched, two hundred and forty five payslips recomputed
- and none of it can write ssc.payslip.salary_adjustment.

salary_adjustment is a stored compute over attachment_ids.signed_value, and
attachment_ids is the one2many of ssc.attachment on payslip_id. So the total
falls if attachments were detached from their payslip, had their value or sign
changed, changed state, or were deleted. Which of those it is decides whether
7,102 dirhams of deductions and additions have gone missing from this month's
ssc payroll or whether the field simply needs recomputing.

WHAT IT PRINTS

  the ssc payslips whose salary_adjustment does not equal the signed total of
  the attachments still pointing at them - that is the recompute case, and it
  is harmless;
  every attachment for the month with no payslip_id at all, which is the
  detached case and is not;
  the totals both ways, so the 7,102 can be accounted for or not.

Read-only.
"""
import os
from collections import defaultdict

WIDTH = 118
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or 'SAUD,ROYAL ARROW').split(',')
        if n.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("")
    print(char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value, width=12):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


SscSlip = env['ssc.payslip'].sudo()
Attachment = env['ssc.attachment'].sudo()

slips = SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR)),
                        ('is_staff', '=', False)]).filtered(
    lambda s: any(p in (s.employee_id.company_id.name or '').upper()
                  for p in ONLY))

# ------------------------------------------- 1. stored value against its source
title("1. salary_adjustment against the attachments still on the payslip")
stale, stored_total, live_total = [], 0.0, 0.0
for slip in slips:
    stored = slip.salary_adjustment or 0.0
    live = sum(a.signed_value or 0.0 for a in slip.attachment_ids)
    stored_total += stored
    live_total += live
    if abs(stored - live) > 0.005:
        stale.append((slip, stored, live))

print("  %s ssc payslip(s) in scope" % len(slips))
print("  stored salary_adjustment   %s" % num(stored_total))
print("  attachments on them        %s" % num(live_total))
print("  %s payslip(s) where the two disagree" % len(stale))
for slip, stored, live in sorted(stale, key=lambda r: -abs(r[1] - r[2]))[:15]:
    print("      %-42s stored %s   attachments %s"
          % ((slip.employee_id.display_name or '?')[:42], num(stored), num(live)))
if stale:
    print("")
    print("  A disagreement here is only a stale stored field. It recomputes.")

# ----------------------------------------------- 2. attachments off any payslip
title("2. attachments for %s-%s with no payslip behind them" % (MONTH, YEAR))
loose = Attachment.search([('month', '=', MONTH), ('year', '=', str(YEAR))]).filtered(
    lambda a: not a.payslip_id
    and any(p in (a.employee_id.company_id.name or '').upper() for p in ONLY))
by_type = defaultdict(lambda: [0, 0.0])
for attachment in loose:
    key = attachment.type_id.name or '?'
    by_type[key][0] += 1
    by_type[key][1] += attachment.signed_value or 0.0
print("  %s attachment(s) carry no payslip_id" % len(loose))
for name, (count, total) in sorted(by_type.items(), key=lambda kv: -abs(kv[1][1])):
    print("      %-40s %4s   %s" % (name[:40], count, num(total)))
if loose:
    print("")
    print("  These are the ones that would have left the payroll. Whether that")
    print("  is right depends on whether the money moved to the native inputs.")
    for attachment in sorted(loose, key=lambda a: -abs(a.signed_value or 0))[:12]:
        print("      %-38s %-24s %s  state=%s"
              % ((attachment.employee_id.display_name or '?')[:38],
                 (attachment.type_id.name or '?')[:24],
                 num(attachment.signed_value), attachment.state or '-'))

# ------------------------------------------------------- 3. everything, by state
title("3. every attachment this month, by state and type")
everything = Attachment.search([('month', '=', MONTH), ('year', '=', str(YEAR))]).filtered(
    lambda a: any(p in (a.employee_id.company_id.name or '').upper() for p in ONLY))
grid = defaultdict(lambda: [0, 0.0])
for attachment in everything:
    grid[(attachment.type_id.name or '?', attachment.state or '-',
          bool(attachment.payslip_id))][0] += 1
    grid[(attachment.type_id.name or '?', attachment.state or '-',
          bool(attachment.payslip_id))][1] += attachment.signed_value or 0.0
print("  %-34s %-12s %-10s %6s %s"
      % ("type", "state", "on payslip", "count", "signed total"))
print("  " + "-" * (WIDTH - 4))
for (name, state, attached), (count, total) in sorted(grid.items()):
    print("  %-34s %-12s %-10s %6s %s"
          % (name[:34], state, "yes" if attached else "NO", count, num(total)))
print("")
print("  total across every attachment this month: %s"
      % num(sum(a.signed_value or 0.0 for a in everything)))

env.cr.rollback()
title("read only - nothing was written")
