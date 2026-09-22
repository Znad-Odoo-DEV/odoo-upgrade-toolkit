"""Does every imported staff payslip still say the number Studio said?

    odoo-bin shell --no-http --shell-interface=python < tools/compare_staff_payslip_money.py

Reads only. The same gate the labour payslips went through, on the same terms:
zero differences on the net is the answer that permits the source to be deleted,
and anything else is a number to explain first.

Four figures, and the net on its own and in full - it is the one that was paid.
A payslip that never came across announces itself. One that came across and
disagrees does not, and after x_staff_payslips is gone there is nothing left to
notice it with.
"""
SOURCE = 'x_staff_payslips'
TOLERANCE = 0.01

PAIRS = [
    ('gross', 'gross_salary', 'x_studio_total_gross_salary'),
    ('total salary', 'total_salary', 'x_studio_total_salary_of_this_month'),
    ('adjustment', 'salary_adjustment', 'x_studio_salary_adjusments'),
    ('net', 'net_amount', 'x_studio_value'),
]

cr = env.cr                                                      # noqa: F821
Slip = env['ssc.payslip'].sudo().with_context(active_test=False)  # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def g(record, name):
    if not record or name not in record._fields:
        return 0.0
    return record[name] or 0.0


title("1. what is being compared")

rows = {r.id: r for r in Source.search([])}
slips = Slip.search([('studio_ref_id', 'in', list(rows)),
                     ('is_staff', '=', True)])
print("  %s Studio staff payslip(s)" % len(rows))
print("  %s mirrored here and marked staff" % len(slips))
missing = len(rows) - len(slips)
if missing:
    print("  %s have no mirror" % missing)


title("2. figure by figure")

differences = {label: [] for label, _o, _s in PAIRS}
for slip in slips:
    src = rows.get(slip.studio_ref_id)
    if not src:
        continue
    for label, ours_field, studio_field in PAIRS:
        mine = slip[ours_field] or 0.0
        theirs = g(src, studio_field)
        if abs(mine - theirs) > TOLERANCE:
            differences[label].append((slip, mine, theirs))

for label, _o, _s in PAIRS:
    off = differences[label]
    drift = sum(m - t for _sl, m, t in off)
    print("  %-14s %5s of %s differ    net drift %s"
          % (label, len(off), len(slips), round(drift, 2)))


title("3. the net, in full")

net = differences['net']
if not net:
    print("  Every mirrored staff payslip agrees with Studio on the amount paid.")
else:
    by_month = {}
    for slip, mine, theirs in net:
        entry = by_month.setdefault('%s %s' % (slip.month, slip.year), [0, 0.0])
        entry[0] += 1
        entry[1] += mine - theirs
    print("  %s payslip(s) differ on the net" % len(net))
    for month, (count, drift) in sorted(by_month.items()):
        print("      %-12s %4s payslip(s)   %s" % (month, count, round(drift, 2)))
    print("\n  the largest, either way:")
    for slip, mine, theirs in sorted(net, key=lambda d: -abs(d[1] - d[2]))[:15]:
        print("      %-8s %-30s %-4s %-6s ours %-11s studio %-11s %s"
              % (slip.id, (slip.employee_id.name or '')[:30], slip.month, slip.year,
                 round(mine, 2), round(theirs, 2), round(mine - theirs, 2)))


title("4. and the staff flag")

wrong = Slip.search_count([('studio_ref_id', 'in', list(rows)),
                           ('is_staff', '=', False)])
print("  %s mirrored from the staff master and not marked staff" % wrong)
print("""
  It matters: is_staff is what separates a monthly salary from one paid by the
  punch, and every report that splits the payroll reads it.""")


title("before deleting the source")
print("""  Zero on the net is the answer that permits it. Anything else is a number
  to explain first - and afterwards there is nothing left to explain it with.""")
