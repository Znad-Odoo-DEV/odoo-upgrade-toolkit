"""Can the native pay run follow the 21st-to-20th cycle, or is it tied to the
calendar month?

    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/probe_payroll_period.py

SSC pays a labour cycle that runs from the 21st of one month to the 20th of the
next (res.company.ssc_payroll_start_day). The native pay run in the interface
came out "Aug 1 - Aug 31". If the period is genuinely free, the cycle is a data
decision and nothing needs building; if anything computes or constrains it to a
month, the whole native payroll has to be told about the cycle before a single
entry is posted in the wrong period.

So this reads, from the registry rather than from the documentation:

  * the date fields on the pay run and the payslip - computed? related?
    readonly? required? - and the source of whatever computes them;
  * every @api.constrains on both models that mentions a date, in full;
  * the pay runs and payslips that already exist, with their dates;
  * each company's configured cycle start day, next to what the runs actually
    use;
  * the work entries on record, since they are generated per period and are
    what a payslip counts.

Reads only. It rolls its transaction back before it exits.
"""
import inspect

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def source_of(model, name):
    function = getattr(model, name, None)
    if function is None:
        return None
    try:
        return inspect.getsource(function)
    except (OSError, TypeError):
        return None


def show_source(model, name, limit=40):
    code = source_of(model, name)
    if not code:
        print(f"    ({name}: source not available)")
        return
    lines = code.splitlines()
    for line in lines[:limit]:
        print("    " + line)
    if len(lines) > limit:
        print(f"    ... {len(lines) - limit} more line(s)")


title("0. what is installed")

for name in ('hr.payslip', 'hr.payslip.run', 'hr.work.entry', 'hr.version',
             'hr.payroll.structure'):
    print(f"  {name:<24} {'yes' if name in env else 'NO'}")

if 'hr.payslip' not in env:
    title("stop")
    print("  hr_payroll is not installed - nothing to probe.")
else:
    # ------------------------------------------------------------------
    title("1. the date fields, and what decides them")

    for model_name in ('hr.payslip.run', 'hr.payslip'):
        if model_name not in env:
            continue
        model = env[model_name].sudo()
        print(f"\n  {model_name}")
        computes = []
        for field_name, field in sorted(model._fields.items()):
            if field.type not in ('date', 'datetime'):
                continue
            if not any(word in field_name for word in ('date', 'from', 'to', 'start', 'end')):
                continue
            bits = [f"type={field.type}"]
            if getattr(field, 'compute', None):
                bits.append(f"compute={field.compute}")
                computes.append(field.compute)
            if getattr(field, 'related', None):
                bits.append(f"related={'.'.join(field.related) if isinstance(field.related, (list, tuple)) else field.related}")
            bits.append(f"store={bool(field.store)}")
            bits.append(f"readonly={bool(field.readonly)}")
            bits.append(f"required={bool(field.required)}")
            print(f"    {field_name:<22} {'  '.join(bits)}")
        for compute in dict.fromkeys(computes):
            print(f"\n    --- {model_name}.{compute}")
            show_source(model, compute)

    # ------------------------------------------------------------------
    title("2. constraints that mention a date")

    for model_name in ('hr.payslip.run', 'hr.payslip'):
        if model_name not in env:
            continue
        model = env[model_name].sudo()
        print(f"\n  {model_name}")
        found = False
        for name in dir(model):
            if not name.startswith('_check') and 'constrain' not in name:
                continue
            code = source_of(model, name)
            if not code or 'date' not in code:
                continue
            found = True
            print(f"\n    --- {name}")
            show_source(model, name, limit=25)
        if not found:
            print("    none that mentions a date")

    # ------------------------------------------------------------------
    title("3. the pay runs that exist")

    Run = env['hr.payslip.run'].sudo() if 'hr.payslip.run' in env else None
    if Run is None:
        print("  no hr.payslip.run model.")
    else:
        runs = Run.search([], order='id desc', limit=20)
        if not runs:
            print("  none.")
        for run in runs:
            struct = run.struct_id.name if 'struct_id' in run._fields else '-'
            print(f"  [{run.id}] {run.name[:38]:<38} {run.date_start} -> {run.date_end}"
                  f"  {run.state:<8} {run.company_id.name[:22]:<22} {struct}")

    # ------------------------------------------------------------------
    title("4. the payslips that exist")

    slips = env['hr.payslip'].sudo().search([], order='id desc', limit=20)
    if not slips:
        print("  none.")
    for slip in slips:
        print(f"  [{slip.id}] {slip.employee_id.name[:26]:<26} {slip.date_from} -> "
              f"{slip.date_to}  {slip.state:<8} {slip.company_id.name[:22]:<22} "
              f"{slip.struct_id.name[:24]}")

    # ------------------------------------------------------------------
    title("5. the cycle each company is configured for")

    for company in env['res.company'].sudo().search([]):
        day = (company.ssc_payroll_start_day
               if 'ssc_payroll_start_day' in company._fields else None)
        print(f"  {company.name[:44]:<44} start day: "
              + (f"{day} (so {day}th -> {day - 1 if day > 1 else 'end'}th)"
                 if day else "not configured"))

    # ------------------------------------------------------------------
    title("6. work entries on record")

    if 'hr.work.entry' not in env:
        print("  no hr.work.entry model.")
    else:
        Entry = env['hr.work.entry'].sudo()
        total = Entry.search_count([])
        print(f"  {total} work entry/entries")
        # 19.0 dates a work entry with `date`; older series used `date_start`.
        column = next((name for name in ('date', 'date_start')
                       if name in Entry._fields), None)
        if total and column:
            first = Entry.search([], order=f'{column} asc', limit=1)
            last = Entry.search([], order=f'{column} desc', limit=1)
            print(f"  earliest {first[column]}   latest {last[column]}")
            rows = Entry._read_group([], ['work_entry_type_id'], ['__count'])
            for entry_type, count in rows[:15]:
                print(f"    {(entry_type.name or '-')[:44]:<44} {count:>7}")

    # ------------------------------------------------------------------
    title("7. what the structures say about the schedule")

    for structure in env['hr.payroll.structure'].sudo().search([]):
        schedule = (structure.schedule_pay
                    if 'schedule_pay' in structure._fields else '-')
        print(f"  [{structure.id}] {structure.name[:44]:<44} schedule_pay={schedule}"
              f"  journal={structure.journal_id.display_name or '-'}")

    # ------------------------------------------------------------------
    title("8. which structure a contract actually lands on")

    # The run carries no structure in 19.0: a payslip takes it from the
    # contract's structure type, so this is what decides the journal.
    StructType = (env['hr.payroll.structure.type'].sudo()
                  if 'hr.payroll.structure.type' in env else None)
    if StructType is None or 'default_struct_id' not in StructType._fields:
        print("  no structure type with a default on this database.")
    else:
        Version = env['hr.version'].sudo()
        for stype in StructType.search([]):
            versions = Version.search([('structure_type_id', '=', stype.id)])
            per_company = {}
            for version in versions:
                per_company[version.company_id.name or '-'] = \
                    per_company.get(version.company_id.name or '-', 0) + 1
            default = stype.default_struct_id
            print(f"\n  [{stype.id}] {stype.name[:44]:<44} {len(versions):>5} version(s)")
            print(f"      default structure: "
                  + (f"[{default.id}] {default.name}" if default else "(none)"))
            print(f"      its journal:       "
                  + (default.journal_id.display_name or '(none)' if default else '-'))
            for name, count in sorted(per_company.items(), key=lambda kv: -kv[1]):
                print(f"      {name[:40]:<40} {count:>5}")

env.cr.rollback()
print("\nread only - transaction rolled back.")
