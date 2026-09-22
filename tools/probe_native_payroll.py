"""Print how standard Payroll is actually wired on this database, so the SSC
logic can be rebuilt on it instead of beside it.

    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/probe_native_payroll.py > native.txt

Everything SSC does by hand has a native counterpart, and the counterpart only
matters if it exists HERE, in this version, with these codes. So this reads the
registry rather than the documentation:

  * what a contract may use as its work entry source, and what the fleet uses;
  * every work entry type, because SSC needs one per day-status it recognises
    (present, weekly off worked, public holiday worked, sick, absence) and two
    more for overtime priced at two different rates;
  * the code that turns an attendance into a work entry - the exact seam where
    the off-day and overtime classification has to be injected;
  * the payslip input types and salary attachments, which is where advances,
    loans and fines land once they stop being ssc.attachment;
  * the calendars, their weekly pattern and their public holidays, since the
    weekly off day and the holiday penalty are read off them.

Reads only. It rolls its transaction back before it exits.
"""
import inspect

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92
MAX_METHODS = 14


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def source_of(model_name, method_name):
    model = env[model_name] if model_name in env else None
    function = getattr(model, method_name, None) if model is not None else None
    if function is None:
        return None
    try:
        return inspect.getsource(function)
    except (OSError, TypeError):
        return None


def dump(model_name, fields, order=None, limit=None, domain=None):
    """One line per record, only the fields this version actually has."""
    if model_name not in env:
        print(f"  {model_name} is not installed")
        return env['res.users'].browse()
    model = env[model_name].sudo()
    present = [f for f in fields if f in model._fields]
    missing = [f for f in fields if f not in model._fields]
    records = model.search(domain or [], order=order, limit=limit)
    print(f"  {model_name}: {len(records)} record(s), showing {', '.join(present)}")
    if missing:
        print(f"    (absent in this version: {', '.join(missing)})")
    for record in records:
        parts = []
        for name in present:
            value = record[name]
            if hasattr(value, '_name'):
                value = value.display_name if len(value) == 1 else \
                    (', '.join(value.mapped('display_name')) or '-')
            parts.append(f"{name}={value}")
        print("    " + "  ".join(parts))
    return records


# --- 0. what is installed ----------------------------------------------------

title("0. modules")

wanted = [
    'hr', 'hr_contract', 'hr_attendance', 'hr_holidays', 'hr_payroll',
    'hr_work_entry', 'hr_work_entry_contract', 'hr_work_entry_contract_attendance',
    'hr_payroll_attendance', 'hr_payroll_account', 'hr_attendance_overtime',
    'l10n_ae', 'l10n_ae_hr_payroll', 'project', 'hr_timesheet',
    'ssc_payroll', 'ssc_attendance',
]
for module in env['ir.module.module'].sudo().search([('name', 'in', wanted)], order='name'):
    print(f"  {module.name:<38} {module.state}")

# --- 1. the work entry source ------------------------------------------------

title("1. work entry source on the contract")

contract_model = 'hr.version' if 'hr.version' in env else 'hr.contract'
Contract = env[contract_model].sudo()
field = Contract._fields.get('work_entry_source')
if field is None:
    print(f"  {contract_model} has no work_entry_source in this version")
else:
    for value, label in field.selection if isinstance(field.selection, list) else []:
        count = Contract.search_count([('work_entry_source', '=', value)])
        print(f"  {value:<16} {label:<28} {count:>5} contract(s)")

structure_types = env['hr.payroll.structure.type'].sudo().search([])
print(f"\n  structure types ({len(structure_types)}):")
for stype in structure_types:
    used = Contract.search_count([('structure_type_id', '=', stype.id)])
    calendar = stype.default_resource_calendar_id if 'default_resource_calendar_id' \
        in stype._fields else None
    print(f"    {stype.name:<44} {used:>5} contract(s)"
          f"   default calendar: {calendar.name if calendar else '-'}")

# --- 2. work entry types -----------------------------------------------------

title("2. work entry types - one per day status SSC recognises")

dump('hr.work.entry.type',
     ['code', 'name', 'is_leave', 'round_days', 'amount_rate', 'country_id',
      'is_unforeseen', 'sequence'],
     order='sequence, code')

# --- 3. the seam: attendance -> work entry -----------------------------------

title("3. where an attendance becomes a work entry")

candidates = []
for model_name in (contract_model, 'hr.employee', 'hr.work.entry', 'hr.payslip'):
    if model_name not in env:
        continue
    model = env[model_name]
    for name in sorted(dir(model)):
        if not name.startswith('_'):
            continue
        if 'work_entr' in name or 'attendance_interval' in name:
            candidates.append((model_name, name))

print(f"  {len(candidates)} candidate method(s); printing the first {MAX_METHODS}\n")
for model_name, name in candidates[:MAX_METHODS]:
    code = source_of(model_name, name)
    print("-" * WIDTH)
    print(f"{model_name}.{name}")
    print("-" * WIDTH)
    print(code.rstrip() if code else "  (source unavailable)")
if len(candidates) > MAX_METHODS:
    print(f"\n  ... {len(candidates) - MAX_METHODS} more not printed:")
    for model_name, name in candidates[MAX_METHODS:]:
        print(f"    {model_name}.{name}")

# --- 4. where advances, loans and fines will land ----------------------------

title("4. payslip inputs and salary attachments")

dump('hr.payslip.input.type', ['code', 'name', 'country_id', 'struct_ids'], order='code')

if 'hr.salary.attachment' in env:
    Attachment = env['hr.salary.attachment'].sudo()
    other_field = Attachment._fields.get('other_input_type_id')
    print(f"\n  hr.salary.attachment: {Attachment.search_count([])} record(s)")
    for name in ('other_input_type_id', 'monthly_amount', 'total_amount',
                 'state', 'date_start', 'date_end'):
        print(f"    field {name:<22} {'yes' if name in Attachment._fields else 'NO'}")
    if other_field is not None:
        print("    -> advances / loans / fines map onto this model")
else:
    print("\n  hr.salary.attachment is not installed")

# --- 5. the batch, which carries the 25 -> 25 period -------------------------

title("5. payslip batches")

if 'hr.payslip.run' in env:
    Run = env['hr.payslip.run'].sudo()
    for name in ('date_start', 'date_end', 'state', 'company_id', 'structure_id'):
        print(f"  field {name:<16} {'yes' if name in Run._fields else 'NO'}")
    dump('hr.payslip.run', ['name', 'date_start', 'date_end', 'state'],
         order='date_start desc', limit=5)
else:
    print("  hr.payslip.run is not installed")

# --- 6. leaves, for the sick-leave rule --------------------------------------

title("6. leave types and the work entry type each produces")

dump('hr.leave.type',
     ['name', 'code', 'work_entry_type_id', 'requires_allocation',
      'time_type', 'company_id'],
     order='name')

# --- 7. calendars: the weekly off day and the public holidays ----------------

title("7. calendars")

calendars = dump('resource.calendar',
                 ['name', 'hours_per_day', 'hours_per_week', 'tz',
                  'two_weeks_calendar', 'company_id'],
                 order='name')

for calendar in calendars:
    weekdays = {}
    for line in calendar.attendance_ids:
        # The lunch line sits on the same weekday and would be counted as work.
        if 'day_period' in line._fields and line.day_period == 'lunch':
            continue
        weekdays.setdefault(line.dayofweek, 0.0)
        weekdays[line.dayofweek] += (line.hour_to - line.hour_from)
    names = {'0': 'Mon', '1': 'Tue', '2': 'Wed', '3': 'Thu',
             '4': 'Fri', '5': 'Sat', '6': 'Sun'}
    worked = ", ".join(f"{names.get(day, day)} {hours:g}h"
                       for day, hours in sorted(weekdays.items()))
    off = ", ".join(names[d] for d in sorted(names) if d not in weekdays)
    print(f"\n  {calendar.name}")
    print(f"    works {worked or '-'}")
    print(f"    off   {off or '-'}")

title("8. public holidays already on the calendars")

Leaves = env['resource.calendar.leaves'].sudo()
globals_ = Leaves.search([('resource_id', '=', False)], order='date_from desc', limit=25)
print(f"  {Leaves.search_count([('resource_id', '=', False)])} global leave(s); "
      f"latest {len(globals_)}:")
for leave in globals_:
    print(f"    {str(leave.date_from)[:10]} -> {str(leave.date_to)[:10]}  "
          f"{(leave.name or '')[:40]:<40} "
          f"calendar={leave.calendar_id.name or 'ALL'}  "
          f"type={leave.work_entry_type_id.code if 'work_entry_type_id' in leave._fields and leave.work_entry_type_id else '-'}")

# --- 9. overtime plumbing ----------------------------------------------------

title("9. attendance overtime")

Attendance = env['hr.attendance'].sudo() if 'hr.attendance' in env else None
if Attendance is None:
    print("  hr.attendance is not installed")
else:
    for name in ('worked_hours', 'overtime_hours', 'validated_overtime_hours',
                 'expected_hours', 'in_mode', 'out_mode'):
        print(f"  hr.attendance.{name:<26} {'yes' if name in Attendance._fields else 'NO'}")
    print(f"  {Attendance.search_count([])} attendance record(s)")

if 'hr.attendance.overtime' in env:
    Overtime = env['hr.attendance.overtime'].sudo()
    print(f"\n  hr.attendance.overtime: {Overtime.search_count([])} record(s)")
    print(f"    fields: {', '.join(sorted(n for n in Overtime._fields if not n.startswith('_')))[:400]}")

Company = env['res.company'].sudo()
print("\n  overtime settings per company:")
for company in Company.search([]):
    flags = []
    for name in ('hr_attendance_overtime', 'attendance_overtime_validation',
                 'overtime_company_threshold', 'overtime_employee_threshold',
                 'attendance_from_systray', 'hr_attendance_display_overtime'):
        if name in Company._fields:
            flags.append(f"{name}={company[name]}")
    print(f"    {company.name[:34]:<34} {'  '.join(flags) or '(no overtime fields)'}")

env.cr.rollback()
print("\nread only - nothing written.")
