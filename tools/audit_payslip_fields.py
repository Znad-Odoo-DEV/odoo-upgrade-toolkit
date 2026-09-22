"""Every field of every ssc.payslip against its counterpart on hr.payslip, with the reason.

    cd ~/src/user
    # August 2026, everybody, every company, mismatches printed, all rows to CSV:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/audit_payslip_fields.py

    SSC_MONTH=AUG SSC_YEAR=2026            the period (default)
    SSC_WHO=labour | staff | all           default all
    SSC_COMPANIES="SAUD,ROYAL ARROW"       default every company
    SSC_DETAIL=all | mismatched            print every employee, or only those with a gap
    SSC_EMPLOYEE="Ahmad Ali"               one person, whole
    SSC_OUT=~/payslip_audit.csv            every row, every employee, always
    SSC_TOL=0.5                            money tolerance in AED

reconcile_payrolls.py answers "how far apart are the two payrolls". This
answers the question underneath it: for one person, one field at a time, what
does each side say and WHY do they differ. The reasons are derived from the
records, not typed - every line of the reason column is a fact the tool read
(a contract figure, a day count, an input that landed or did not) and never a
guess. Where the tool cannot name the cause it says "unexplained" and prints
the residual, which is the honest answer and the one worth chasing.

THE TWO ARITHMETICS

    ssc     gross        = basic + house + transport + other   (a SNAPSHOT taken
                                                                when the payslip
                                                                was generated)
            rate_per_day = gross / days in month
            total_salary = gross                    if attendance >= days
                         = rate_per_day * attendance otherwise
            attendance   = sum(day_ratio) - penalty + advance days
            overtime     = reg_hours * ot_rate_regular + off_hours * ot_rate_off
            adjustment   = sum(attachments.signed_value)
            net          = total_salary + overtime + adjustment

    native  BASIC/HOUALLOW/TRAALLOW/OTALLOW = contract figure * ratio
            ratio        = (days in month - absent) / days in month
                           (read back as BASIC / wage * days in month)
            AEUNPAID, ABSENCE, SL50, SL0, OOC     take back days not owed
            OT_REG / OT_OFF                         hours * wage / 240 * 1.25 / 1.5
            input rules                             OTHER_EARNINGS, BONUS,
                                                    AIRFARE_ALLOWANCE,
                                                    REIMBURSEMENT,
                                                    SALARY_DEDUCTIONS, ADVREC,
                                                    OTHER_DEDUCTIONS, DEDUCTION
            LEAVESAL / EOS / SICC / SIEC            computed by native from
                                                    hr.leave, departure, GPSSA
            NET

    So each ssc field has a counterpart, and every gap is one of:
      contract   the snapshot on the ssc payslip vs the contract as it is now
      days       what each side counted as a paid day
      hours      approved overtime (ssc) vs punched overtime (native)
      rate       basic/240 on a different basic
      attachment an attachment that did or did not become an input, or an
                 input a rule did or did not consume
      native-only a line native computes itself (leave salary, gratuity,
                 pension) that ssc carried as an attachment or not at all
      unexplained the residual, printed as a number

Read-only. Nothing is created, computed, or written; the CSV is the only output.
"""
import csv
import os
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

WIDTH = 150
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
WHO = (os.environ.get('SSC_WHO') or 'all').lower()
DETAIL = (os.environ.get('SSC_DETAIL') or 'mismatched').lower()
WANTED = (os.environ.get('SSC_EMPLOYEE') or '').strip().lower()
ONLY = [n.strip().upper() for n in (os.environ.get('SSC_COMPANIES') or '').split(',')
        if n.strip()]
TOL = float(os.environ.get('SSC_TOL') or 0.5)
OUT = os.path.expanduser(os.environ.get('SSC_OUT')
                         or '~/payslip_audit_%s_%s.csv' % (MONTH, YEAR))

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

if 'hr.payslip' not in env or 'ssc.payslip' not in env:
    print("hr.payslip or ssc.payslip is not on this database - nothing to compare")
    raise SystemExit

BASE_CODES = ('BASIC', 'HOUALLOW', 'TRAALLOW', 'OTALLOW')
# Deductions that are about DAYS - they belong beside the base, because ssc's
# total_salary already has the absence inside it.
DAY_DEDUCTIONS = ('AEUNPAID', 'ABSENCE', 'SL50', 'SL0', 'OOC', 'AEPUBLICH')
OT_CODES = ('OT_REG', 'OT_OFF')
INPUT_RULES = ('OTHER_EARNINGS', 'BONUS', 'AIRFARE_ALLOWANCE', 'REIMBURSEMENT',
               'SALARY_DEDUCTIONS', 'ADVREC', 'OTHER_DEDUCTIONS', 'DEDUCTION')
NATIVE_OWN = ('LEAVESAL', 'EOS', 'SICC', 'SIEC', 'DEWS', 'ALEA', 'ALED')
TOTALS = ('GROSS', 'NET', 'NETCOST')

# ssc.attachment.type name -> the input code that pays it. Copied from
# move_attachments_to_inputs.py, which is what wrote the inputs; if the two
# ever differ, that tool is the truth and this one is stale.
DESTINATION = {
    'Salary Addition': 'OTHER_EARNINGS',
    'Salary Advance': 'OTHER_EARNINGS',
    'Sick Leave Reimbursement': 'OTHER_EARNINGS',
    'Salary Bonus': 'BONUS',
    'Air Ticket Reimbursement': 'AIRFARE_ALLOWANCE',
    'Phone Bill Reimbursement': 'REIMBURSEMENT',
    'Medical Bill Reimbursement': 'REIMBURSEMENT',
    'Salary Deductions': 'SALARY_DEDUCTIONS',
    'Salary Advance-Deduction': 'ADVREC',
    'Penalty Fine': 'OTHER_DEDUCTIONS',
}
WITHHELD = {
    'Pension for Emirati Employees': ('SICC', 'SIEC'),
    'Leave Salary': ('LEAVESAL',),
}

MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
          'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value, width=11):
    return ("{:>%s,.2f}" % width).format(value or 0.0)


def close(a, b, tol=TOL):
    return abs((a or 0.0) - (b or 0.0)) <= tol


def in_scope(company):
    if not ONLY:
        return True
    return any(part in (company.name or '').upper() for part in ONLY)


NativeSlip = env['hr.payslip'].sudo()
SscSlip = env['ssc.payslip'].sudo()

month_index = MONTHS.index(MONTH) + 1
month_first = date(int(YEAR), month_index, 1)
month_days = ((month_first + relativedelta(months=1)) - month_first).days

print("")
print("=" * WIDTH)
print("  period     %s-%s   (%s days in the month)" % (MONTH, YEAR, month_days))
print("  who        %s" % WHO)
print("  companies  %s" % (", ".join(ONLY) if ONLY else "all"))
print("  csv        %s" % OUT)
print("=" * WIDTH)

# ------------------------------------------------------------------ collect
# Native: every non-cancelled payslip whose period starts in the month. More
# than one per employee is reported, never silently picked from.
native = {}
native_dupes = defaultdict(list)
month_last = month_first + relativedelta(months=1, days=-1)
for slip in NativeSlip.search([('state', '!=', 'cancel'),
                               ('date_from', '>=', month_first),
                               ('date_from', '<=', month_last)]):
    if not in_scope(slip.employee_id.company_id):
        continue
    # The same population on both sides, or "native only" fills with the
    # other population - a labour run listed every staff payslip as somebody
    # ssc never paid.
    staff_slip = (slip.struct_id.name or '').endswith('Staff Pay')
    if WHO == 'labour' and staff_slip:
        continue
    if WHO == 'staff' and not staff_slip:
        continue
    key = slip.employee_id.id
    if key in native:
        native_dupes[key].append(slip)
        continue
    native[key] = slip

ssc_by_employee = {}
ssc_unlinked = []
domain = [('month', '=', MONTH), ('year', '=', str(YEAR))]
if WHO == 'labour':
    domain.append(('is_staff', '=', False))
elif WHO == 'staff':
    domain.append(('is_staff', '=', True))
for slip in SscSlip.search(domain):
    if not in_scope(slip.employee_id.company_id):
        continue
    employee = slip.employee_id.hr_employee_id if 'hr_employee_id' in slip.employee_id._fields \
        else slip.employee_id
    if not employee or employee._name != 'hr.employee':
        ssc_unlinked.append(slip)
        continue
    ssc_by_employee[employee.id] = (employee, slip)

title("1. who is on each side")
both = sorted(set(ssc_by_employee) & set(native))
print("  ssc payslips          %s" % len(ssc_by_employee))
print("  native payslips       %s" % len(native))
print("  on both sides         %s" % len(both))
print("  ssc only              %s" % len(set(ssc_by_employee) - set(native)))
print("  native only           %s" % len(set(native) - set(ssc_by_employee)))
if ssc_unlinked:
    print("  !! %s ssc payslip(s) point at no hr.employee and cannot be compared:"
          % len(ssc_unlinked))
    for slip in ssc_unlinked[:10]:
        print("       %s" % (slip.employee_id.display_name or '?'))
if native_dupes:
    print("  !! %s employee(s) hold more than one native payslip this month - "
          "the first found is used:" % len(native_dupes))
    for key, extra in list(native_dupes.items())[:10]:
        print("       %s  (+%s)" % (native[key].employee_id.name or '?', len(extra)))


def why_no_native(employee):
    """What stops the native run from making this person a payslip.

    Read off the record, in the order the engine checks: an archived employee
    gets nothing; no contract, nothing; a contract with no structure type has
    no structure to compute; a contract that starts after the period or ends
    before it is out of range; and a contract that passes all four was simply
    not in the batch.
    """
    if not employee.active:
        return "archived"
    version = employee.version_id
    if not version:
        return "no contract (hr.version)"
    bits = []
    if not version.structure_type_id:
        bits.append("contract has no structure type")
    elif not version.structure_type_id.default_struct_id:
        bits.append("structure type %r has no structure" % version.structure_type_id.name)
    start = version.contract_date_start
    end = version.contract_date_end
    if not start:
        bits.append("no contract start date")
    elif start > month_first + relativedelta(months=1, days=-1):
        bits.append("contract starts %s, after the period" % start)
    if end and end < month_first:
        bits.append("contract ended %s" % end)
    if 'contract_state' in version._fields and version.contract_state not in ('open', 'draft', False):
        bits.append("contract state %s" % version.contract_state)
    return "; ".join(bits) or "eligible - just not in the batch"


for label, ids in (("ssc only - the native run never made them", set(ssc_by_employee) - set(native)),
                   ("native only - ssc never paid them", set(native) - set(ssc_by_employee))):
    if ids:
        print("\n  %s:" % label)
        reasons = defaultdict(list)
        for key in sorted(ids):
            who = (ssc_by_employee[key][0] if key in ssc_by_employee
                   else native[key].employee_id)
            reason = why_no_native(who) if key in ssc_by_employee else ''
            reasons[reason].append(who)
        for reason, people in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
            print("     %3s  %s" % (len(people), reason or '-'))
            for who in people[:8]:
                print("            %-40s %s" % ((who.name or '?')[:40],
                                                (who.company_id.name or '')[:30]))
            if len(people) > 8:
                print("            ... and %s more" % (len(people) - 8))


# ----------------------------------------------------------------- one pair
def native_view(slip):
    """Everything the tool needs off one native payslip, read once."""
    lines = defaultdict(float)
    qty = defaultdict(float)
    for line in slip.line_ids:
        lines[line.code or '?'] += line.total or 0.0
        qty[line.code or '?'] += line.quantity or 0.0
    worked = {}
    for line in slip.worked_days_line_ids:
        worked[line.code or line.name or '?'] = (
            line.number_of_days or 0.0, line.number_of_hours or 0.0, line.amount or 0.0)
    inputs = defaultdict(float)
    for line in slip.input_line_ids:
        inputs[line.code or '?'] += line.amount or 0.0
    version = slip.version_id if 'version_id' in slip._fields else slip.employee_id.version_id
    wage = version.wage or 0.0
    house = version.l10n_ae_housing_allowance if 'l10n_ae_housing_allowance' in version._fields else 0.0
    transport = (version.l10n_ae_transportation_allowance
                 if 'l10n_ae_transportation_allowance' in version._fields else 0.0)
    other = version.l10n_ae_other_allowances if 'l10n_ae_other_allowances' in version._fields else 0.0
    gross = wage + (house or 0.0) + (transport or 0.0) + (other or 0.0)
    base = sum(lines[c] for c in BASE_CODES)
    day_deductions = sum(lines[c] for c in DAY_DEDUCTIONS)
    ot_reg, ot_off = lines['OT_REG'], lines['OT_OFF']
    net = lines['NET']
    # Hours: the OT rule lines carry them as quantity when the rule sets
    # result_qty; when it does not, the worked-days overtime lines do.
    ot_reg_hours = qty['OT_REG'] if qty['OT_REG'] not in (0.0, 1.0) else sum(
        h for code, (d, h, a) in worked.items()
        if 'overtime' in code.lower() and 'off' not in code.lower())
    ot_off_hours = qty['OT_OFF'] if qty['OT_OFF'] not in (0.0, 1.0) else sum(
        h for code, (d, h, a) in worked.items()
        if 'overtime' in code.lower() and 'off' in code.lower())
    basic_line = lines['BASIC']
    ratio = (basic_line / wage) if wage else 0.0
    return {
        'slip': slip, 'lines': lines, 'qty': qty, 'worked': worked, 'inputs': inputs,
        'wage': wage, 'house': house or 0.0, 'transport': transport or 0.0,
        'other': other or 0.0, 'gross': gross, 'base': base,
        'day_deductions': day_deductions, 'salary': base + day_deductions,
        'ot_reg': ot_reg, 'ot_off': ot_off, 'ot_reg_hours': ot_reg_hours,
        'ot_off_hours': ot_off_hours, 'net': net, 'ratio': ratio,
        'days': ratio * month_days,
        'adjust': net - base - day_deductions - ot_reg - ot_off,
        'period_days': ((slip.date_to - slip.date_from).days + 1)
        if slip.date_from and slip.date_to else 0,
        'is_staff': (slip.struct_id.name or '').endswith('Staff Pay'),
        'rate_reg': wage / 240.0 * 1.25 if wage else 0.0,
        'rate_off': wage / 240.0 * 1.5 if wage else 0.0,
    }


def compare(employee, s, n):
    """One employee: every field, both values, the gap and the reason."""
    rows = []

    def row(field, label, ssc_value, native_label, native_value, reason,
            kind='money'):
        if kind == 'money' or kind == 'days' or kind == 'hours':
            gap = (ssc_value or 0.0) - (native_value or 0.0)
            tol = TOL if kind == 'money' else 0.05
            same = abs(gap) <= tol
        elif kind == 'info':
            # Facts, not findings. A row that is always different - the two
            # workflows' states, a project split native does not keep - is not
            # a mismatch, and counting it as one buried the real ones: five of
            # these on every employee made 895 of the first run's 2,444.
            gap = ''
            same = True
        else:
            gap = ''
            same = (ssc_value or '') == (native_value or '')
        rows.append({
            'employee': employee.name or '?',
            'company': employee.company_id.name or '',
            'field': field, 'label': label,
            'ssc': ssc_value, 'native_field': native_label, 'native': native_value,
            'gap': gap, 'same': same,
            'reason': '' if same else reason,
        })

    # --- identity and period ------------------------------------------------
    row('employee_id', 'employee', employee.name, 'employee_id',
        n['slip'].employee_id.name, '', 'text')
    row('is_staff', 'staff?', 'staff' if s.is_staff else 'labour', 'struct_id',
        'staff' if n['is_staff'] else 'labour',
        'ssc says %s, the native structure is %s - the contract is on the wrong '
        'structure type or ssc.employee.is_engineer_office disagrees with Workforce'
        % ('staff' if s.is_staff else 'labour', n['slip'].struct_id.name), 'text')
    row('from_date', 'period from', str(s.from_date or ''), 'date_from',
        str(n['slip'].date_from or ''),
        'the ssc period is the attendance cycle, the native period is what the '
        'pay run was typed with', 'text')
    row('to_date', 'period to', str(s.to_date or ''), 'date_to',
        str(n['slip'].date_to or ''),
        'ssc period ends %s, native %s - the days after the ssc end are the '
        'advance days on the ssc side and ordinary work entries on the native side'
        % (s.to_date, n['slip'].date_to), 'info')
    row('days', 'days in month', s.days or 0, 'days in month',
        month_days, 'ssc priced the day at gross/%s; native prices it at '
        'gross/%s' % (s.days, month_days), 'days')
    row('state', 'state', s.state or '', 'state', n['slip'].state or '',
        'informational - the two workflows are different', 'info')

    # --- the contract snapshot vs the contract now ---------------------------
    gross_same = close(s.gross_salary, n['gross'])
    split_note = ('gross agrees, only the split differs: the wage split tool '
                  'wrote basic/house/transport/other in different proportions '
                  'than the ssc snapshot carries' if gross_same else
                  'the ssc payslip carries a snapshot taken at generation; native '
                  'reads hr.version as it is today - the contract changed after '
                  'the payslip was issued, or the wage split wrote other figures')
    row('basic_salary', 'basic', s.basic_salary, 'version.wage', n['wage'], split_note)
    row('house_allowance', 'house allowance', s.house_allowance,
        'version.l10n_ae_housing_allowance', n['house'], split_note)
    row('transport_allowance', 'transport allowance', s.transport_allowance,
        'version.l10n_ae_transportation_allowance', n['transport'], split_note)
    row('other_allowance', 'other allowance', s.other_allowance,
        'version.l10n_ae_other_allowances', n['other'], split_note)
    row('gross_salary', 'gross', s.gross_salary, 'wage + allowances', n['gross'],
        'contract snapshot vs contract now (see basic)')
    row('rate_per_day', 'rate per day', s.rate_per_day, 'gross / days in month',
        n['gross'] / month_days if month_days else 0.0,
        'follows the gross gap and the days-in-month gap above')

    # --- overtime rates ------------------------------------------------------
    rate_note = ('native takes basic/240 * 1.25 (1.5 off-day) from the contract '
                 'basic of %s; ssc froze %s at generation' % (num(n['wage'], 1),
                                                              num(s.basic_salary, 1)))
    row('ot_rate_regular', 'OT rate regular', s.ot_rate_regular, 'wage/240*1.25',
        n['rate_reg'], rate_note)
    row('ot_rate_off', 'OT rate off-day', s.ot_rate_off, 'wage/240*1.5',
        n['rate_off'], rate_note)

    # --- days ----------------------------------------------------------------
    summary = s.summary_id if 'summary_id' in s._fields else None
    penalty = (summary.penalty_this_month or 0.0) if summary else 0.0
    advance = s.advance_days or 0.0
    day_gap = (s.total_attendance or 0.0) - n['days']
    worked_total = sum(d for (d, h, a) in n['worked'].values())
    worked_text = ", ".join("%s %.2fd" % (code[:22], d)
                            for code, (d, h, a) in sorted(n['worked'].items()) if d)
    if day_gap > 0.05:
        why = ('ssc counts %.2f day(s) native did not. ' % day_gap)
        parts = []
        if advance:
            parts.append('%.2f advance day(s) are inside ssc attendance and native '
                         'has no such thing' % advance)
        parts.append('the rest is days with no work entry on the native side - '
                     'punches missing from hr.attendance, or a Friday ssc paid '
                     'because the days either side were worked')
        why += "; ".join(parts)
    elif day_gap < -0.05:
        why = ('native paid %.2f day(s) ssc did not: ' % -day_gap)
        parts = []
        if penalty:
            parts.append('ssc took a %.2f-day penalty off' % penalty)
        if 'OUT' in n['worked'] and n['worked']['OUT'][0]:
            parts.append('%.2f day(s) are OUT (no contract start date) and BASIC '
                         'counts OUT as covered' % n['worked']['OUT'][0])
        parts.append('or the ssc daily lines earned less than a full day (missing '
                     'check-out, half day) where native saw a whole work entry')
        why += "; ".join(parts)
    else:
        why = ''
    # The two periods differ by design - ssc pays the calendar month, the
    # native run stops on the 25th - so the days after the native period are
    # taken out BEFORE the two sides are compared. What is left is a real
    # disagreement about a day inside the same window.
    period_days = n['period_days'] or month_days
    present_in_period = max(0.0, min((s.total_attendance or 0.0) - advance,
                                     float(period_days)))
    after_period = (s.total_attendance or 0.0) - present_in_period
    gross_day = (n['gross'] / month_days) if month_days else 0.0
    native_days_effective = (n['salary'] / gross_day) if gross_day else n['days']
    real_day_gap = present_in_period - native_days_effective
    row('total_attendance', 'days paid', s.total_attendance,
        'BASIC/wage * days in month', n['days'], why, 'info')
    row('total_attendance (after native period)', 'days after the native period',
        after_period, '(none)', 0.0,
        'ssc pays 1..%s, native 1..%s: these %.2f day(s) are the advance and the '
        'days after the 25th, paid by ssc by design and outside the native run'
        % (s.days or month_days, period_days, after_period), 'info')
    row('total_attendance (inside native period)', 'days paid inside the period',
        present_in_period, 'salary / (gross/days in month)', native_days_effective,
        why if abs(real_day_gap) > 0.05 else '', 'days')
    row('total_attendance (worked-days lines)', 'days on work entries',
        s.total_attendance, 'sum(worked_days_line_ids.number_of_days)', worked_total,
        'native work-entry days by code: %s' % (worked_text or 'none'), 'info')
    row('advance_days', 'advance days', advance, '(none)', 0.0,
        'native has no advance days; they sit inside ssc attendance', 'info')
    row('advance_amount', 'advance amount', s.advance_amount, '(none)', 0.0,
        'native has no advance amount; it is inside ssc total_salary', 'info')

    # --- overtime hours and money -------------------------------------------
    for (side, hours_field, amount_field, ssc_rate_field, code, hours_key,
         amount_key, rate_key) in (
            ('regular', 'overtime_reg', 'overtime_reg_amount', 'ot_rate_regular',
             'OT_REG', 'ot_reg_hours', 'ot_reg', 'rate_reg'),
            ('off-day', 'overtime_off', 'overtime_off_amount', 'ot_rate_off',
             'OT_OFF', 'ot_off_hours', 'ot_off', 'rate_off')):
        ssc_hours = s[hours_field] or 0.0
        nat_hours = n[hours_key]
        if nat_hours > ssc_hours + 0.05:
            hours_why = ('native pays every punched hour beyond the schedule '
                         '(%.2f); ssc pays the approved daily figure (%.2f). '
                         'Policy, not a fault - undecided which to keep'
                         % (nat_hours, ssc_hours))
        elif nat_hours < ssc_hours - 0.05:
            hours_why = ('native saw fewer overtime hours (%.2f vs %.2f): overtime '
                         'lines not rebuilt for the period, or punches missing'
                         % (nat_hours, ssc_hours))
        else:
            hours_why = ''
        row(hours_field, 'OT hours %s' % side, ssc_hours, '%s quantity' % code,
            nat_hours, hours_why, 'hours')
        ssc_amount = s[amount_field] or 0.0
        nat_amount = n[amount_key]
        bits = []
        if not close(ssc_hours, nat_hours, 0.05):
            bits.append('hours differ (see above)')
        if not close(s[ssc_rate_field] or 0.0, n[rate_key], 0.005):
            bits.append('rate differs (see OT rate)')
        row(amount_field, 'OT amount %s' % side, ssc_amount, '%s total' % code,
            nat_amount, "; ".join(bits) or 'hours and rate agree but the amount does '
            'not - the native rule is not hours * wage/240 * factor here')
    row('overtime_salary', 'overtime total', s.overtime_salary, 'OT_REG + OT_OFF',
        n['ot_reg'] + n['ot_off'], 'sum of the two sides above')

    # --- salary for the month -----------------------------------------------
    sal_gap = (s.total_salary or 0.0) - n['salary']
    explained = 0.0
    bits = []
    by_period = after_period * (s.rate_per_day or 0.0)
    if abs(by_period) > TOL:
        explained += by_period
        bits.append('%s BY DESIGN - %.2f day(s) after the native period'
                    % (num(by_period, 1), after_period))
    if not close(s.gross_salary, n['gross']):
        by_gross = ((s.gross_salary or 0.0) - n['gross']) * (
            present_in_period / s.days if s.days else 0.0)
        explained += by_gross
        bits.append('%s from the contract gross' % num(by_gross, 1))
    if abs(real_day_gap) > 0.05:
        by_days = real_day_gap * gross_day
        explained += by_days
        bits.append('%s from %.2f day(s) inside the period'
                    % (num(by_days, 1), real_day_gap))
    if s.days and s.days != month_days:
        bits.append('ssc divides by %s days, native by %s' % (s.days, month_days))
    if n['day_deductions']:
        bits.append('(native day deductions %s: %s - already inside the day count)' % (
            num(n['day_deductions'], 1),
            ", ".join("%s %s" % (c, num(n['lines'][c], 1))
                      for c in DAY_DEDUCTIONS if n['lines'][c])))
    residual = sal_gap - explained
    row('total_salary (by design)', 'salary: period difference, expected',
        by_period, '(none)', 0.0,
        'ssc 1..%s against native 1..%s' % (s.days or month_days, period_days),
        'info')
    row('total_salary (residual)', 'salary: unexplained residual', residual, '',
        0.0, 'what is left after the period, the gross and the days are '
             'accounted for' if abs(residual) > TOL else '')
    if abs(residual) > TOL and bits:
        bits.append('unexplained residual %s' % num(residual, 1))
    elif abs(residual) > TOL:
        bits.append('unexplained %s - gross and days agree yet the salary does not'
                    % num(residual, 1))
    row('total_salary', 'salary for the month', s.total_salary,
        'BASIC+HOUALLOW+TRAALLOW+OTALLOW + day deductions', n['salary'],
        "; ".join(bits))

    # --- adjustments: attachment by attachment ------------------------------
    # By destination code, because three ssc types land on OTHER_EARNINGS and
    # one native line carries all of them. Compared one attachment at a time
    # the first took the whole line and the rest showed a gap of their own
    # value - 250.87 against -156.03 against -94.84, adding to nothing, and
    # read as three findings.
    by_code = defaultdict(lambda: [0.0, [], []])   # ssc total, names, states
    for attachment in s.attachment_ids:
        type_name = attachment.type_id.name or '?'
        value = attachment.signed_value or 0.0
        if type_name in WITHHELD:
            codes = WITHHELD[type_name]
            native_value = sum(n['lines'][c] for c in codes)
            row('attachment: %s' % type_name, attachment.name or type_name, value,
                "/".join(codes), native_value,
                'deliberately not moved: native computes %s itself (%s)'
                % ("/".join(codes), num(native_value, 1)))
            continue
        code = DESTINATION.get(type_name)
        if not code:
            row('attachment: %s' % type_name, attachment.name or type_name, value,
                '(no destination)', 0.0,
                'attachment type %r is in no map - nothing carried it to native'
                % type_name)
            continue
        by_code[code][0] += value
        by_code[code][1].append(type_name)
        by_code[code][2].append(attachment.state or '-')
    inputs_left = dict(n['inputs'])
    for code, (value, names, states) in sorted(by_code.items()):
        written = inputs_left.pop(code, 0.0)
        landed = n['lines'][code]
        label = "%s  (%s)" % (code, ", ".join(sorted(set(names)))[:40])
        if abs(written) < 0.005:
            why = ('no native input of code %s on this payslip - the attachment(s) '
                   'were never moved (state %s)' % (code, "/".join(sorted(set(states)))))
        elif abs(landed) < 0.005:
            why = ('input %s written (%s) but no rule line landed - the rule is '
                   'INERT on this structure' % (code, num(written, 1)))
        else:
            why = ('same code, different amount: input carries %s, rule line %s, '
                   'ssc attachments %s' % (num(written, 1), num(landed, 1), num(value, 1)))
        row('attachments -> %s' % code, label, value, '%s line' % code, landed, why)
    for code, amount in inputs_left.items():
        if abs(amount) > 0.005 and code in INPUT_RULES:
            row('input only on native: %s' % code, code, 0.0, '%s input' % code,
                n['lines'][code] if n['lines'][code] else amount,
                'native carries an input ssc has no attachment for')
    for code in NATIVE_OWN:
        if n['lines'][code]:
            row('native computes: %s' % code, code, 0.0, code, n['lines'][code],
                {'LEAVESAL': 'annual leave salary from hr.leave, paid the month before '
                             'the leave; ssc pays it as a Leave Salary attachment or '
                             'not at all',
                 'EOS': 'end of service gratuity on the final payslip; ssc has no '
                        'counterpart on the payslip',
                 'SICC': 'GPSSA employer share, Emiratis only',
                 'SIEC': 'GPSSA employee share, Emiratis only'}.get(
                    code, 'computed by native, no ssc counterpart'))
    named = set(BASE_CODES) | set(DAY_DEDUCTIONS) | set(OT_CODES) | set(INPUT_RULES) \
        | set(NATIVE_OWN) | set(TOTALS)
    for code, value in sorted(n['lines'].items()):
        if code not in named and value:
            row('native line: %s' % code, code, 0.0, code, value,
                'a native rule this tool does not know - read it')
    row('salary_adjustment', 'adjustments total', s.salary_adjustment,
        'NET - salary - overtime', n['adjust'],
        'the attachment rows above say which one')

    # --- net -----------------------------------------------------------------
    net_bits = []
    if abs(by_period) > TOL:
        net_bits.append('BY DESIGN %s' % num(by_period, 1))
    if not close((s.total_salary or 0.0) - by_period, n['salary']):
        net_bits.append('salary %s'
                        % num((s.total_salary or 0.0) - by_period - n['salary'], 1))
    if not close(s.overtime_salary, n['ot_reg'] + n['ot_off']):
        net_bits.append('overtime %s' % num((s.overtime_salary or 0.0)
                                            - n['ot_reg'] - n['ot_off'], 1))
    if not close(s.salary_adjustment, n['adjust']):
        net_bits.append('adjustments %s' % num((s.salary_adjustment or 0.0)
                                               - n['adjust'], 1))
    row('net_amount', 'NET', s.net_amount, 'NET', n['net'],
        "made of: " + ", ".join(net_bits) if net_bits
        else 'components agree yet NET does not - a native line outside the '
             'components, see the native line rows')

    # --- what has no counterpart at all --------------------------------------
    row('project_ids', 'project split', len(s.project_ids), '(none)', 0,
        'no native counterpart: costing goes through the analytic on the '
        'contract, not through payslip lines', 'info')
    row('is_cash', 'paid in cash', 'cash' if s.is_cash else 'WPS', '(none)', '',
        'no native counterpart until WPS is built', 'info')
    return rows


# ----------------------------------------------------------------- run it
all_rows = []
per_employee = []
for key in both:
    employee, s = ssc_by_employee[key]
    if WANTED and WANTED not in (employee.name or '').lower():
        continue
    n = native_view(native[key])
    if WHO == 'labour' and n['is_staff']:
        continue
    if WHO == 'staff' and not n['is_staff']:
        continue
    rows = compare(employee, s, n)
    all_rows.extend(rows)
    per_employee.append((employee, s, n, rows))

# ------------------------------------------------------------- 2. by reason
title("2. the gaps, counted by field")
by_field = defaultdict(lambda: [0, 0.0])
for r in all_rows:
    if not r['same']:
        by_field[r['field']][0] += 1
        if isinstance(r['gap'], float):
            by_field[r['field']][1] += r['gap']
print("  %-46s %10s %16s" % ("field", "employees", "sum of gaps"))
print("  " + "-" * 76)
by_field_rows = defaultdict(list)
for r in all_rows:
    if not r['same']:
        by_field_rows[r['field']].append(r)
for field, (count, total) in sorted(by_field.items(), key=lambda kv: -kv[1][0]):
    print("  %-46s %10s %16s" % (field[:46], count, num(total, 15)))
    # Few enough to name: a field that differs on a dozen people is a dozen
    # records to open, and a count sends somebody looking for them by hand.
    if count <= 12:
        for r in sorted(by_field_rows[field],
                        key=lambda r: -abs(r['gap']) if isinstance(r['gap'], float) else 0):
            print("      %-38s %s   %s"
                  % (r['employee'][:38],
                     num(r['gap'], 11) if isinstance(r['gap'], float) else '',
                     r['reason'][:70]))
if not by_field:
    print("  every field agrees on every employee")

# ------------------------------------------------ 2b. the month, reconciled
title("2b. the whole month reconciled: ssc net = native net + these")


def total(field):
    return sum(float(r['gap']) for r in all_rows
               if r['field'] == field and isinstance(r['gap'], float))


ssc_net = sum(float(r['ssc']) for r in all_rows if r['field'] == 'net_amount')
nat_net = sum(float(r['native']) for r in all_rows if r['field'] == 'net_amount')
by_design = sum(float(r['ssc']) for r in all_rows
                if r['field'] == 'total_salary (by design)')
sal_res = total('total_salary (residual)')
ot = total('overtime_salary')
adj = total('salary_adjustment')
print("  %-54s %16s" % ("ssc net, everybody compared", num(ssc_net, 15)))
print("  %-54s %16s" % ("native net", num(nat_net, 15)))
print("  %-54s %16s" % ("gap", num(ssc_net - nat_net, 15)))
print("  " + "-" * 72)
print("  %-54s %16s" % ("BY DESIGN: days after the native period", num(by_design, 15)))
print("  %-54s %16s" % ("salary: gross + days inside the period + residual",
                        num(total('total_salary') - by_design, 15)))
print("  %-54s %16s" % ("    of which unexplained residual", num(sal_res, 15)))
print("  %-54s %16s" % ("overtime", num(ot, 15)))
print("  %-54s %16s" % ("adjustments (attachments / inputs / native-only)", num(adj, 15)))
print("  %-54s %16s" % ("outside all of the above",
                        num((ssc_net - nat_net) - total('total_salary') - ot - adj, 15)))

# ---------------------------------------------------------- 3. by employee
title("3. employee by employee   (detail: %s)" % DETAIL)
shown = 0
for employee, s, n, rows in sorted(per_employee,
                                   key=lambda t: -abs((t[1].net_amount or 0.0) - t[2]['net'])):
    gaps = [r for r in rows if not r['same']]
    if DETAIL != 'all' and not gaps:
        continue
    shown += 1
    print("\n  %s   -   %s   -   %s"
          % (employee.name or '?', employee.company_id.name or '-',
             'staff' if n['is_staff'] else 'labour'))
    print("    net  ssc %s   native %s   gap %s"
          % (num(s.net_amount), num(n['net']),
             num((s.net_amount or 0.0) - n['net'])))
    print("    %-38s %13s %13s %11s   %s" % ("field", "ssc", "native", "gap", "why"))
    for r in (rows if DETAIL == 'all' else gaps):
        ssc_v = num(r['ssc'], 13) if isinstance(r['ssc'], float) else str(r['ssc'])[:13].rjust(13)
        nat_v = num(r['native'], 13) if isinstance(r['native'], float) else str(r['native'])[:13].rjust(13)
        gap_v = num(r['gap']) if isinstance(r['gap'], float) else ''.rjust(11)
        print("    %-38s %s %s %s   %s"
              % (r['label'][:38], ssc_v, nat_v, gap_v, r['reason'][:120]))
        if len(r['reason']) > 120:
            print("    %-38s %13s %13s %11s   %s" % ('', '', '', '', r['reason'][120:240]))
print("\n  %s employee(s) printed of %s compared" % (shown, len(per_employee)))

# ------------------------------------------------------------------ 4. csv
with open(OUT, 'w', newline='', encoding='utf-8') as handle:
    writer = csv.DictWriter(handle, fieldnames=[
        'employee', 'company', 'field', 'label', 'ssc', 'native_field', 'native',
        'gap', 'same', 'reason'])
    writer.writeheader()
    for r in all_rows:
        writer.writerow(r)
title("every row of every employee is in %s   (%s rows)" % (OUT, len(all_rows)))
print("read only - nothing was written to the database")
