"""One employee's two payslips, line by line, until the gap has a name.

    cd ~/src/user

    # the worst gaps, whoever they are:
    SSC_COMPANIES="ROYAL ARROW" odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/explain_payslip_gap.py

    # somebody in particular:
    SSC_EMPLOYEE="Ahmad Ali Sameu" odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/explain_payslip_gap.py

compare_payrolls.py says forty eight of fifty two Royal Arrow labourers differ
on "other" by two and a half thousand dirhams, and that number is a remainder -
it names nothing. Forty four differ on base, but almost all of those are one or
two fils of rounding, and five are real. A total cannot tell those apart and
neither can an average, so this stops totalling and prints both payslips whole:

  NATIVE   every worked-days line with its day count and amount - proration
           lives here and nowhere else, so a base gap is visible as days rather
           than inferred from money; then every salary rule line with its code;
           then every salary input with its code and amount.

  SSC      the four figures the comparison uses, the attendance summary's own
           day counts beside them, and every attachment with its type, value
           and whether it was already paid.

Then the two are set against each other by code where the codes correspond, so
"other differs by fifty" becomes "OTHER_EARNINGS is on the input but no rule
consumed it", or "ssc counted twenty six days and native counted five".

Read-only.
"""
import os
from collections import defaultdict

WIDTH = 112
MONTH = (os.environ.get('SSC_MONTH') or 'AUG').upper()
YEAR = os.environ.get('SSC_YEAR') or '2026'
TOP = int(os.environ.get('SSC_TOP') or 4)
WANTED = (os.environ.get('SSC_EMPLOYEE') or '').strip().lower()
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or '').split(',') if n.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def hr_employee_of(record):
    """The hr.employee behind an ssc record, whichever generation it is.

    ssc.employee retired on production on 2026-09-08 and every payroll document
    names hr.employee directly since. This tool still walked the old chain -
    employee_id.hr_employee_id - and hr.employee has no such field, so it died
    on the first record with the traceback hidden behind 2>/dev/null.
    """
    employee = record.employee_id
    if not employee or employee._name == 'hr.employee':
        return employee
    return employee.hr_employee_id

BASE_CODES = ('BASIC', 'HOUALLOW', 'TRAALLOW', 'OTALLOW')
OT_CODES = ('OT_REG', 'OT_OFF')


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def num(value):
    return "{:>12,.2f}".format(value or 0.0)


NativeSlip = env['hr.payslip'].sudo()
SscSlip = env['ssc.payslip'].sudo()

# ------------------------------------------------- pair the two sides up first
pairs = []               # (employee, native slip, ssc slip)
for slip in SscSlip.search([('month', '=', MONTH), ('year', '=', str(YEAR)),
                            ('is_staff', '=', False)]):
    employee = hr_employee_of(slip)
    if not employee:
        continue
    if ONLY and not any(p in (employee.company_id.name or '').upper() for p in ONLY):
        continue
    native = NativeSlip.search([
        ('employee_id', '=', employee.id),
        ('date_from', '>=', '%s-01-01' % YEAR)], limit=10)
    native = native.filtered(
        lambda s: s.date_from and s.date_from.strftime('%b').upper() == MONTH
        and (s.struct_id.name or '').endswith('Labour Pay'))
    if not native:
        continue
    pairs.append((employee, native[0], slip))


def native_parts(slip):
    base = overtime = net = 0.0
    for line in slip.line_ids:
        if line.code in BASE_CODES:
            base += line.total
        elif line.code in OT_CODES:
            overtime += line.total
        elif line.code == 'NET':
            net = line.total
    return base, overtime, net


if WANTED:
    chosen = [p for p in pairs if WANTED in (p[0].name or '').lower()]
    if not chosen:
        print("no labour payslip pair for an employee matching %r" % WANTED)
        raise SystemExit
else:
    scored = []
    for employee, native, ssc in pairs:
        _b, _o, net = native_parts(native)
        scored.append((abs((ssc.net_amount or 0.0) - net), employee, native, ssc))
    scored.sort(key=lambda row: -row[0])
    chosen = [(e, n, s) for _gap, e, n, s in scored[:TOP]]

for employee, native, ssc in chosen:
    base, overtime, net = native_parts(native)
    title("%s   -   %s" % (employee.name or '?', employee.company_id.name or '-'))
    print("  ssc  base %s  overtime %s  other %s  net %s"
          % (num(ssc.total_salary), num(ssc.overtime_salary),
             num(ssc.salary_adjustment), num(ssc.net_amount)))
    print("  nat  base %s  overtime %s  other %s  net %s"
          % (num(base), num(overtime), num(net - base - overtime), num(net)))
    print("  gap  base %s  overtime %s  other %s  net %s"
          % (num((ssc.total_salary or 0) - base),
             num((ssc.overtime_salary or 0) - overtime),
             num((ssc.salary_adjustment or 0) - (net - base - overtime)),
             num((ssc.net_amount or 0) - net)))

    # ------------------------------------------------ the days, on both sides
    title("days - a base gap is a day-count gap before it is a money gap", '-')
    print("  native worked-days lines   [%s .. %s]" % (native.date_from, native.date_to))
    if not native.worked_days_line_ids:
        print("      none - the payslip has no worked-days lines at all")
    for line in native.worked_days_line_ids:
        print("      %-34s %8s day(s)  %8s hour(s)  %s"
              % ((line.name or line.code or '?')[:34],
                 line.number_of_days, line.number_of_hours, num(line.amount)))
    print("  ssc")
    for field, label in (('total_attendance', 'total attendance'),
                         ('total_absence', 'absence'),
                         ('overtime_reg', 'overtime regular'),
                         ('overtime_off', 'overtime off-day')):
        if field in ssc._fields:
            print("      %-34s %s" % (label, ssc[field]))
    summary = getattr(ssc, 'summary_id', None)
    if summary:
        print("      summary %s" % (summary.display_name or summary.id))

    # ------------------------------------------------------- the native lines
    title("native salary rule lines", '-')
    for line in native.line_ids:
        if not line.total:
            continue
        print("      %-14s %-42s %s"
              % (line.code or '?', (line.name or '')[:42], num(line.total)))

    title("native salary inputs", '-')
    if not native.input_line_ids:
        print("      none")
    inputs_by_code = defaultdict(float)
    for line in native.input_line_ids:
        inputs_by_code[line.code or '?'] += line.amount or 0.0
        print("      %-20s %-36s %s"
              % (line.code or '?', (line.input_type_id.name or '')[:36],
                 num(line.amount)))

    # An input nothing consumes is money written and never paid - the commonest
    # way "other" ends up short by exactly the amount that was moved.
    line_codes = {line.code for line in native.line_ids}
    print("\n      input code(s) with no salary rule line of the same code:")
    orphans = [code for code in inputs_by_code if code not in line_codes]
    for code in sorted(orphans):
        print("        %-20s %s   <-- written but nothing consumed it"
              % (code, num(inputs_by_code[code])))
    if not orphans:
        print("        none - every input code has a matching line")

    # ---------------------------------------------------- the ssc attachments
    title("ssc attachments", '-')
    Attachment = env.get('ssc.attachment')
    if Attachment is None:
        print("      ssc.attachment is not installed")
    else:
        found = Attachment.sudo().search([
            ('employee_id', '=', ssc.employee_id.id),
            ('month', '=', MONTH), ('year', '=', str(YEAR))])
        if not found:
            print("      none")
        for attachment in found:
            print("      %-34s %s  %-10s %s"
                  % ((attachment.type_id.name or '?')[:34],
                     num(attachment.value), attachment.state or '-',
                     "on ssc payslip" if attachment.payslip_id else "loose"))
        print("")
        print("      total on attachments: %s"
              % num(sum(a.signed_value for a in found)))

title("read only - nothing was written")
