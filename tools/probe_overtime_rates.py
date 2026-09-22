"""What the stored overtime rates are actually made of.

    odoo-bin shell -d <database> --no-http < tools/probe_overtime_rates.py

Read only. Nothing is written, ever.

The two rates are to become multipliers - 1.25 on a normal day, 1.5 on an off
day - applied to an hourly rate of salary / 30 / 8. Before changing what they
mean, this asks what they mean now, because the answer decides whether the
change is a tidy-up or a pay rise.

Spot-checking a dozen of them, ot_rate_regular x 240 lands on round salaries
(2775, 1875, 1500, 2100, 3750), which says the stored figure is already
salary / 30 / 8 with a multiplier of exactly 1.0. If that holds across all 400,
then moving regular overtime to 1.25 raises everybody's overtime by a quarter,
and that is a decision about money rather than about fields.

Two things are measured, per employee and then summarised:

  which base   - rate x 240 against basic_salary and against gross_salary, so
                 "the basic" and "the wage" stop being the same word for two
                 different numbers.
  which factor - the multiplier each stored rate implies over its own base,
                 and how many employees sit on each one.
"""
from collections import Counter, defaultdict

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

Ssc = env['ssc.employee']
Payslip = env['ssc.payslip']

DAYS = 30.0
HOURS = 8.0
DIVISOR = DAYS * HOURS  # 240


def title(text):
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


def factor(rate, base):
    """The multiplier this stored rate implies over base / 30 / 8."""
    if not base or not rate:
        return None
    return round(rate / (base / DIVISOR), 4)


employees = Ssc.with_context(active_test=False).search(
    ['|', ('ot_rate_regular', '!=', 0), ('ot_rate_off', '!=', 0)])
print("%s employee(s) carry an overtime rate" % len(employees))

# ----------------------------------------------------------------------
title("1. WHICH BASE - is it the basic salary or the gross")
# ----------------------------------------------------------------------
on_basic = on_gross = on_neither = 0
for employee in employees:
    implied = employee.ot_rate_regular * DIVISOR
    if employee.basic_salary and abs(implied - employee.basic_salary) < 0.5:
        on_basic += 1
    elif employee.gross_salary and abs(implied - employee.gross_salary) < 0.5:
        on_gross += 1
    else:
        on_neither += 1
print("rate x 240 equals the BASIC salary : %s" % on_basic)
print("rate x 240 equals the GROSS salary : %s" % on_gross)
print("matches neither                    : %s" % on_neither)
print()
print("These are different numbers on this database, so 'the basic' and 'the")
print("wage' cannot both be right. Whichever column wins here is the one the")
print("new formula has to divide.")

# ----------------------------------------------------------------------
title("2. WHICH FACTOR - what multiplier is stored today")
# ----------------------------------------------------------------------
for label, field_name in (("REGULAR days", 'ot_rate_regular'),
                          ("OFF days / holidays", 'ot_rate_off')):
    print("\n--- %s ---" % label)
    for base_label, base_field in (("basic", 'basic_salary'),
                                   ("gross", 'gross_salary')):
        counts = Counter()
        for employee in employees:
            f = factor(employee[field_name], employee[base_field])
            if f is None:
                continue
            counts[round(f, 2)] += 1
        common = counts.most_common(6)
        print("  over the %-6s %s"
              % (base_label,
                 ", ".join("x%s on %s" % (f, n) for f, n in common) or "nothing"))

# ----------------------------------------------------------------------
title("3. THE RATIO BETWEEN THE TWO")
# ----------------------------------------------------------------------
# Whatever the base, off / regular is a pure number and says what the off-day
# premium is today.
ratios = Counter()
for employee in employees:
    if employee.ot_rate_regular and employee.ot_rate_off:
        ratios[round(employee.ot_rate_off / employee.ot_rate_regular, 3)] += 1
for ratio, count in ratios.most_common(10):
    print("  off / regular = %-8s on %s employee(s)" % (ratio, count))
missing_off = employees.filtered(lambda e: e.ot_rate_regular and not e.ot_rate_off)
print()
print("%s carry a regular rate and NO off rate." % len(missing_off))

# ----------------------------------------------------------------------
title("4. WHAT THE CHANGE WOULD COST")
# ----------------------------------------------------------------------
# The only figure that matters: overtime already paid, repriced at the proposed
# multipliers, on the last twelve months of payslips.
slips = Payslip.search([('overtime_salary', '>', 0)], order='id desc', limit=4000)
old_total = new_total = 0.0
hours_reg = hours_off = 0.0
for slip in slips:
    employee = slip.employee_id
    base = employee.basic_salary if on_basic >= on_gross else employee.gross_salary
    hourly = (base or 0) / DIVISOR
    hours_reg += slip.overtime_reg
    hours_off += slip.overtime_off
    old_total += slip.overtime_salary
    new_total += slip.overtime_reg * hourly * 1.25 + slip.overtime_off * hourly * 1.5

print("%s payslip(s) with overtime" % len(slips))
print("regular hours %s, off hours %s" % (round(hours_reg, 1), round(hours_off, 1)))
print()
print("paid as it stands            : %s AED" % round(old_total, 2))
print("repriced at 1.25 / 1.5       : %s AED" % round(new_total, 2))
delta = new_total - old_total
print("difference                   : %s AED  (%s%%)"
      % (round(delta, 2),
         round(100.0 * delta / old_total, 1) if old_total else 0))
print()
print("That difference is what the new multipliers would have cost over these")
print("payslips. It is a decision about wages, not about where a field lives.")

# ----------------------------------------------------------------------
title("5. A DOZEN, WORKED THROUGH")
# ----------------------------------------------------------------------
print("%-34s %-10s %-10s %-10s %-10s %-8s %-8s"
      % ("NAME", "BASIC", "GROSS", "REG RATE", "OFF RATE", "f(reg)", "f(off)"))
print("-" * 100)
for employee in employees[:12]:
    print("%-34s %-10s %-10s %-10s %-10s %-8s %-8s"
          % (employee.name[:34],
             employee.basic_salary, employee.gross_salary,
             round(employee.ot_rate_regular, 4), round(employee.ot_rate_off, 4),
             factor(employee.ot_rate_regular, employee.basic_salary),
             factor(employee.ot_rate_off, employee.basic_salary)))
print()
print("f() is the multiplier over basic / 30 / 8. If it reads 1.0 for the")
print("regular column, the stored rate carries no premium at all today.")

print("\nDone. Read only - nothing was written.")
