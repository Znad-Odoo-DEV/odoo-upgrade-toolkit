"""Compare the hours a payslip was paid for against the hours its calendar says
the period holds, so a payslip that priced two seconds of work is visible.

    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/check_payslip_hours.py > hours.txt

    # only the drafts, and print every row instead of the worst ones:
    SSC_STATE=draft SSC_ALL=1 odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/check_payslip_hours.py > hours.txt

Under the UAE structure a contract whose work entry source is ATTENDANCE is paid

    basic = worked WORK100 hours * wage / hours the calendar holds for the period

so the whole payslip hangs off one ratio. When that ratio collapses the payslip
does not fail - it quietly pays nothing, and the overtime rate, whose divisor is
the payslip's own days, explodes in the other direction. Both are printed here
side by side because one number is meaningless without the other.

The ratio is computed from the worked-day lines directly rather than from the
localization's own fields, so this still reports on a database where
l10n_ae_hr_payroll is absent; where the fields do exist they are printed beside
it and any disagreement is the finding.

Then, for the payslips that came out empty, it counts the attendances and the
work entries covering the same employee and the same dates - that is where the
chain breaks, and it says which link is missing.

Reads only. It rolls its transaction back before it exits.
"""
import os
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import fields as odoo_fields

STATES = [s.strip() for s in (os.environ.get('SSC_STATE') or '').split(',') if s.strip()]
SHOW_ALL = os.environ.get('SSC_ALL') == '1'
LIMIT = int(os.environ.get('SSC_LIMIT') or 0)

# A payslip is "empty" below this many paid hours: small enough that no real
# shift lands there, large enough to catch the two-second rows.
EMPTY_HOURS = 0.5
# How far the paid hours may sit from the calendar before it is worth a line.
OK_LOW, OK_HIGH = 0.9, 1.1
# How many empty payslips get the attendance / work entry probe.
PROBE = 8

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 100


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def version_of(payslip):
    """19.0 hangs the payslip off a version, 18.0 off a contract."""
    for field in ('version_id', 'contract_id'):
        if field in payslip._fields:
            return payslip[field]
    return None


def calendar_hours(payslip, version):
    """What the working schedule says the payslip's own period holds.

    Deliberately the same call the localization makes, so this reports the
    divisor actually used rather than a second opinion about it.
    """
    calendar = version.resource_calendar_id if version else None
    if not calendar or not payslip.date_from or not payslip.date_to:
        return None
    start = odoo_fields.Datetime.to_datetime(payslip.date_from)
    end = (odoo_fields.Datetime.to_datetime(payslip.date_to)
           + relativedelta(days=1) - relativedelta(microseconds=1))
    try:
        return calendar.get_work_duration_data(start, end).get('hours', 0)
    except Exception as error:                                   # noqa: BLE001
        print(f"  ! calendar {calendar.display_name}: {error}")
        return None


if 'hr.payslip' not in env:
    print("hr_payroll is not installed on this database - nothing to check.")
else:
    Payslip = env['hr.payslip'].sudo()

    domain = [('state', 'in', STATES)] if STATES else []
    payslips = Payslip.search(domain, order='date_from, id', limit=LIMIT or None)

    title(f"1. scope ({len(payslips)} payslip(s))")
    by_state = defaultdict(int)
    for payslip in payslips:
        by_state[payslip.state] += 1
    for state, count in sorted(by_state.items()):
        print(f"  {state:<12} {count:>5}")
    if not payslips:
        print("  nothing to report")

    # --- measure every payslip ------------------------------------------------

    rows = []
    for payslip in payslips:
        version = version_of(payslip)
        worked = paid = 0.0
        for line in payslip.worked_days_line_ids:
            hours = line.number_of_hours or 0.0
            if line.code == 'WORK100':
                worked += hours
            if line.is_paid:
                paid += hours
        expected = calendar_hours(payslip, version)
        ratio = (worked / expected) if expected else None
        rows.append({
            'payslip': payslip,
            'version': version,
            'source': (version.work_entry_source if version and 'work_entry_source'
                       in version._fields else '?'),
            'wage': version.wage if version else 0.0,
            'worked': worked,
            'paid': paid,
            'expected': expected,
            'ratio': ratio,
            'basic': payslip.l10n_ae_basic_salary
            if 'l10n_ae_basic_salary' in payslip._fields else None,
            'hourly': payslip.l10n_ae_hourly_wage
            if 'l10n_ae_hourly_wage' in payslip._fields else None,
        })

    def verdict(row):
        if row['worked'] <= EMPTY_HOURS:
            return 'EMPTY'
        if row['ratio'] is None:
            return 'no calendar'
        if row['ratio'] < OK_LOW:
            return 'short'
        if row['ratio'] > OK_HIGH:
            return 'OVER'
        return 'ok'

    counts = defaultdict(int)
    for row in rows:
        counts[verdict(row)] += 1

    title("2. verdicts")
    for name in ('ok', 'short', 'OVER', 'EMPTY', 'no calendar'):
        if counts[name]:
            print(f"  {name:<12} {counts[name]:>5}")
    print(f"\n  EMPTY  = paid for {EMPTY_HOURS} h or less - the payslip pays ~nothing")
    print(f"  OVER   = more hours than the calendar holds - basic exceeds the wage")

    # --- the rows themselves --------------------------------------------------

    interesting = rows if SHOW_ALL else [r for r in rows if verdict(r) != 'ok']
    title(f"3. rows ({len(interesting)}{'' if SHOW_ALL else ' not ok'})")
    print(f"  {'employee':<28} {'period':<23} {'src':<11} "
          f"{'worked':>9} {'calendar':>9} {'%':>7} {'basic':>10} {'hourly':>14}")
    for row in interesting:
        payslip = row['payslip']
        ratio = f"{row['ratio'] * 100:6.1f}%" if row['ratio'] is not None else '     -'
        expected = f"{row['expected']:9.2f}" if row['expected'] is not None else '        -'
        basic = f"{row['basic']:10.2f}" if row['basic'] is not None else '         -'
        hourly = f"{row['hourly']:14.2f}" if row['hourly'] is not None else '             -'
        print(f"  {(payslip.employee_id.name or '')[:28]:<28} "
              f"{str(payslip.date_from)} {str(payslip.date_to)} "
              f"{str(row['source'])[:11]:<11} {row['worked']:9.2f} {expected} "
              f"{ratio} {basic} {hourly}  {verdict(row)}")

    # --- the overtime rate the same rows would price at -----------------------

    priced = [r for r in rows if r['hourly']]
    if priced:
        title("4. overtime rate sanity")
        multiplier = 1.5
        parameter = env['hr.rule.parameter'].sudo().search(
            [('code', '=', 'l10n_ae_overtime')], limit=1) if 'hr.rule.parameter' in env \
            else None
        if parameter and parameter.parameter_version_ids:
            latest = max(parameter.parameter_version_ids,
                         key=lambda v: str(v.date_from or ''))
            try:
                multiplier = float(latest.parameter_value)
            except (TypeError, ValueError):
                pass
        print(f"  multiplier l10n_ae_overtime = {multiplier}")
        worst = sorted(priced, key=lambda r: -r['hourly'])[:10]
        print(f"\n  {'employee':<28} {'hourly wage':>16} {'one OT hour':>16}")
        for row in worst:
            print(f"  {(row['payslip'].employee_id.name or '')[:28]:<28} "
                  f"{row['hourly']:16,.2f} {row['hourly'] * multiplier:16,.2f}")
        print("\n  an hourly wage far above wage/200 means the divisor collapsed:")
        print("  it is the payslip's OWN days, so fewer days paid = higher overtime rate.")

    # --- where the chain breaks ----------------------------------------------

    empties = [r for r in rows if verdict(r) == 'EMPTY'][:PROBE]
    if empties:
        title(f"5. why they are empty (first {len(empties)})")
        Attendance = env['hr.attendance'].sudo() if 'hr.attendance' in env else None
        WorkEntry = env['hr.work.entry'].sudo() if 'hr.work.entry' in env else None
        # An empty recordset is falsy, so these have to be compared to None -
        # `if not Attendance` would report the model missing on every database.
        if Attendance is None:
            print("  hr.attendance is not installed")
        if WorkEntry is None:
            print("  hr.work.entry is not installed")

        for row in empties:
            payslip = row['payslip']
            employee = payslip.employee_id
            print(f"\n  {employee.name}  {payslip.date_from} -> {payslip.date_to}")

            if Attendance is not None:
                attendances = Attendance.search([
                    ('employee_id', '=', employee.id),
                    ('check_in', '<=', str(payslip.date_to) + ' 23:59:59'),
                    ('check_out', '>=', str(payslip.date_from) + ' 00:00:00'),
                ])
                hours = sum(attendances.mapped('worked_hours'))
                print(f"        attendances  {len(attendances):>5}   {hours:>9.2f} h")

            if WorkEntry is not None:
                entries = WorkEntry.search([
                    ('employee_id', '=', employee.id),
                    ('date_start', '<=', str(payslip.date_to) + ' 23:59:59'),
                    ('date_stop', '>=', str(payslip.date_from) + ' 00:00:00'),
                ])
                per_type = defaultdict(float)
                for entry in entries:
                    seconds = (entry.date_stop - entry.date_start).total_seconds()
                    per_type[entry.work_entry_type_id.code or entry.work_entry_type_id.name
                             or '?'] += seconds / 3600.0
                print(f"        work entries {len(entries):>5}")
                for code, hours in sorted(per_type.items()):
                    print(f"          {code:<20} {hours:>9.2f} h")
                states = defaultdict(int)
                for entry in entries:
                    states[entry.state] += 1
                if states:
                    print("          states: " + ", ".join(
                        f"{state} {count}" for state, count in sorted(states.items())))

            print("        worked day lines:")
            for line in payslip.worked_days_line_ids:
                print(f"          {line.code:<20} {line.number_of_days:>9.5f} d "
                      f"{line.number_of_hours:>9.5f} h  paid={line.is_paid}")

        print("\n  attendances but no work entries -> the work entry generation never ran")
        print("  work entries but empty worked-day lines -> the payslip predates them;")
        print("  recompute the payslip after regenerating the work entries.")

env.cr.rollback()
print("\nread only - nothing written.")
