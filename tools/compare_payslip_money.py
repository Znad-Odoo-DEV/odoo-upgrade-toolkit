"""Does every imported payslip still say the same number Studio said?

    odoo-bin shell --no-http --shell-interface=python < tools/compare_payslip_money.py

Reads only. The import said 4,565 payslips came across; it did not say they are
right. A mirrored payslip stores the Studio figures as they were and computes
its own from them - the computes take the Studio value when studio_ref_id is set
and work it out otherwise - so a difference here means one of two things, and
they are not the same thing at all:

 * the Studio figure did not arrive, and our side computed from what it had
 * the Studio figure arrived and the compute overrode it

Both are worth knowing before the source is deleted, because afterwards there is
nothing to compare against. A payslip that is missing announces itself. A
payslip that is present and wrong does not.

Four figures are compared: the total salary, the overtime, the adjustment and
the net. The net is the one that was paid, so it is reported on its own and in
full: how many differ, by how much, and which way.
"""
SOURCE = 'x_all_payslips'

PAIRS = [
    ('total salary', 'total_salary', 'x_studio_total_salary_of_this_month'),
    ('overtime', 'overtime_salary', 'x_studio_total_overtime_salary_of_this_month'),
    ('adjustment', 'salary_adjustment', 'x_studio_salary_adjustment'),
    ('net', 'net_amount', 'x_studio_net_amount'),
]
TOLERANCE = 0.01

cr = env.cr                                                      # noqa: F821
Slip = env['ssc.payslip'].sudo().with_context(active_test=False)  # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def _get(record, name):
    if not record or name not in record._fields:
        return 0.0
    return record[name] or 0.0


title("1. what is being compared")

slips = Slip.search([('studio_ref_id', '!=', False)])
rows = {r.id: r for r in Source.search([])}
print("  %s mirrored payslip(s)" % len(slips))
print("  %s Studio row(s) to compare against" % len(rows))

orphan = [s for s in slips if s.studio_ref_id not in rows]
if orphan:
    print("  %s mirror(s) name a Studio row that is gone - skipped" % len(orphan))


title("2. figure by figure")

differences = {label: [] for label, _o, _s in PAIRS}
missing_source = 0
for slip in slips:
    src = rows.get(slip.studio_ref_id)
    if not src:
        missing_source += 1
        continue
    for label, ours_field, studio_field in PAIRS:
        mine = slip[ours_field] or 0.0
        theirs = _get(src, studio_field)
        if abs(mine - theirs) > TOLERANCE:
            differences[label].append((slip, src, mine, theirs))

for label, _o, _s in PAIRS:
    rows_off = differences[label]
    drift = sum(m - t for _sl, _sr, m, t in rows_off)
    print("  %-14s %5s of %s differ    net drift %s"
          % (label, len(rows_off), len(slips) - missing_source, round(drift, 2)))


title("3. the net, in full")

net = differences['net']
if not net:
    print("  Every mirrored payslip agrees with Studio on the amount paid.")
else:
    higher = [d for d in net if d[2] > d[3]]
    lower = [d for d in net if d[2] < d[3]]
    print("  %s payslip(s) differ on the net" % len(net))
    print("      %s say more than Studio, %s in total"
          % (len(higher), round(sum(m - t for _a, _b, m, t in higher), 2)))
    print("      %s say less than Studio, %s in total"
          % (len(lower), round(sum(t - m for _a, _b, m, t in lower), 2)))

    by_month = {}
    for slip, src, mine, theirs in net:
        key = '%s %s' % (slip.month, slip.year)
        entry = by_month.setdefault(key, [0, 0.0])
        entry[0] += 1
        entry[1] += mine - theirs
    print("\n  by month:")
    for month, (count, drift) in sorted(by_month.items(), key=lambda kv: -abs(kv[1][1])):
        print("      %-12s %4s payslip(s)   %s" % (month, count, round(drift, 2)))

    print("\n  the largest, either way:")
    for slip, src, mine, theirs in sorted(net, key=lambda d: -abs(d[2] - d[3]))[:15]:
        print("      %-8s %-28s %-4s %-6s ours %-11s studio %-11s %s"
              % (slip.id, (slip.employee_id.name or '')[:28], slip.month, slip.year,
                 round(mine, 2), round(theirs, 2), round(mine - theirs, 2)))


title("4. where a difference comes from")

# A mirrored payslip's computes take the Studio figure when it is there. So a
# net that differs while studio_net_amount holds the Studio value means the
# compute ignored it; a net that differs with studio_net_amount empty means the
# figure never arrived. The two need opposite fixes.
never_arrived, overridden = [], []
for slip, src, mine, theirs in net:
    if abs((slip.studio_net_amount or 0.0) - theirs) > TOLERANCE:
        never_arrived.append((slip, theirs))
    else:
        overridden.append((slip, mine, theirs))

print("  %s where the Studio figure never arrived on our record" % len(never_arrived))
print("  %s where it arrived and the compute did not use it" % len(overridden))
for slip, mine, theirs in overridden[:8]:
    print("      %-8s %-26s stored studio %-11s computed %s"
          % (slip.id, (slip.employee_id.name or '')[:26],
             round(slip.studio_net_amount or 0, 2), round(mine, 2)))

title("read this before deleting anything")
print("""  A payslip that never came across announces itself. A payslip that came
  across and disagrees does not, and after %s is deleted there is nothing left
  to notice it with.

  Zero differences on the net is the answer that permits the deletion. Anything
  else is a number to explain first.""" % SOURCE)
