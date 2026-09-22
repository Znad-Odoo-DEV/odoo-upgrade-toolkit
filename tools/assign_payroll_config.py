"""Put every contract on its company's payroll configuration - the overtime
ruleset AND the salary structure - instead of one employee at a time.

    # report only, writes nothing:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/assign_payroll_config.py

    # one company at a time, which is the sane way to do it:
    SSC_COMPANY="SAUD SHEHATHA" SSC_LIMIT=20 SSC_APPLY=1 odoo-bin shell ...

    # everything, once the first batch has been checked:
    SSC_APPLY=1 odoo-bin shell ...

Two different things decide how somebody is paid, and they are stored in two
different places:

  * the OVERTIME RULESET sits on the contract (`hr.version.ruleset_id`) and
    decides which hours are overtime and at what multiplier;
  * the SALARY STRUCTURE is not on the contract at all. The contract carries a
    structure TYPE, and the structure is picked when a payslip is made - from
    the type's default. So the structure is assigned by pointing the type's
    default at it, once, and by making sure every contract is on that type.

This is the one tool here that moves real money, so it is deliberately narrow:

  * it writes `ruleset_id` and `structure_type_id` and NOTHING else;
  * it only ever assigns a ruleset belonging to the contract's own company, and
    names the companies that have none rather than guessing;
  * it NEVER regenerates overtime. Regenerating recomputes from the earliest
    contract version - years of attendance at once - so it reports how much
    would be rewritten and leaves that to tools/regenerate_overtime.py;
  * SSC_LIMIT does a slice, so the first twenty can be watched before the rest.

Matching: for each company, the ruleset whose name contains SSC_RULESET
(default "Overtime"). Odoo's own "Default Ruleset" and the "Legacy Rules" the
upgrade left behind are never assigned - they are what we are moving away from.

Reads only unless SSC_APPLY=1.
"""
import os
from collections import defaultdict

APPLY = os.environ.get('SSC_APPLY') == '1'
WANTED = os.environ.get('SSC_RULESET') or 'Overtime'
STRUCTURE = os.environ.get('SSC_STRUCTURE') or 'SSC Monthly Pay'
ONLY_COMPANY = (os.environ.get('SSC_COMPANY') or '').strip().lower()
LIMIT = int(os.environ.get('SSC_LIMIT') or 0)

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92

# Never assigned: these are the ones being replaced.
NEVER = ('legacy', 'default')


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


if 'hr.version' not in env:
    print("This database has no hr.version - nothing to do.")
else:
    Version = env['hr.version'].sudo()
    Company = env['res.company'].sudo()
    Ruleset = (env['hr.attendance.overtime.ruleset'].sudo()
               if 'hr.attendance.overtime.ruleset' in env else None)
    Structure = (env['hr.payroll.structure'].sudo()
                 if 'hr.payroll.structure' in env else None)
    Attendance = env['hr.attendance'].sudo() if 'hr.attendance' in env else None
    Line = (env['hr.attendance.overtime.line'].sudo()
            if 'hr.attendance.overtime.line' in env else None)

    # --- the salary structure -------------------------------------------------

    title("1. the salary structure")

    structure = Structure.search([('name', '=', STRUCTURE)], limit=1) \
        if Structure is not None else None
    structure_type = structure.type_id if structure else None
    default_field = None
    if structure_type is not None and structure_type:
        default_field = ('default_struct_id'
                         if 'default_struct_id' in structure_type._fields else None)

    if Structure is None:
        print("  hr_payroll is not installed - no structure to assign")
    elif not structure:
        print(f"  !! no structure named {STRUCTURE!r}")
        print(f"  structures that exist: "
              f"{', '.join(Structure.search([]).mapped('name')) or '(none)'}")
    else:
        print(f"  [{structure.id}] {structure.name}")
        print(f"  its type: {structure_type.name if structure_type else '(none)'}")
        if not structure_type:
            print("  !! the structure has no type, so no contract can be pointed "
                  "at it")
        elif default_field is None:
            print("  this Odoo has no default structure on the type; the structure")
            print("  must be chosen on each payslip or batch by hand")
        else:
            current = structure_type[default_field]
            print(f"  the type's default structure: "
                  f"{current.name if current else '(none)'}"
                  + ("" if current == structure else "  -> would point at "
                     f"{structure.name}"))

    # --- which ruleset belongs to which company -------------------------------

    title("2. the ruleset each company would get")

    target = {}
    if Ruleset is not None:
        for ruleset in Ruleset.search([]):
            name = (ruleset.name or '').lower()
            if WANTED.lower() not in name or any(word in name for word in NEVER):
                continue
            if ruleset.company_id:
                target.setdefault(ruleset.company_id.id, ruleset)
            else:
                # No company means it serves any company without its own.
                target.setdefault(None, ruleset)

    companies = Company.search([])
    if ONLY_COMPANY:
        companies = companies.filtered(lambda c: ONLY_COMPANY in (c.name or '').lower())
        print(f"  restricted to companies matching {ONLY_COMPANY!r}")

    in_scope = []
    missing = []
    for company in companies:
        count = Version.search_count([('company_id', '=', company.id)])
        if not count:
            continue
        ruleset = target.get(company.id) or target.get(None)
        print(f"  {company.name[:44]:<44} {count:>5} version(s)  -> "
              f"{ruleset.name if ruleset else 'NO RULESET FOR THIS COMPANY'}")
        if ruleset:
            in_scope.append((company, ruleset))
        else:
            missing.append(company.name)

    if missing:
        print(f"\n  !! no {WANTED!r} ruleset for: {', '.join(missing)}")
        print("     tools/setup_overtime_rules.py builds one per company.")

    # --- where the contracts stand today --------------------------------------

    title("3. where the contracts stand today")

    move_ruleset = Version.browse()
    move_type = Version.browse()
    for company, ruleset in in_scope:
        versions = Version.search([('company_id', '=', company.id)])
        by_ruleset = defaultdict(int)
        by_type = defaultdict(int)
        for version in versions:
            by_ruleset[version.ruleset_id.name or '(none)'] += 1
            by_type[version.structure_type_id.name or '(none)'] += 1
        print(f"\n  {company.name}")
        print("    overtime ruleset")
        for name, count in sorted(by_ruleset.items(), key=lambda kv: -kv[1]):
            mark = '  <- target' if name == ruleset.name else ''
            print(f"      {name[:38]:<38} {count:>5}{mark}")
        print("    salary structure type")
        for name, count in sorted(by_type.items(), key=lambda kv: -kv[1]):
            mark = ('  <- target' if structure_type and name == structure_type.name
                    else '')
            print(f"      {name[:38]:<38} {count:>5}{mark}")

        move_ruleset |= versions.filtered(lambda v, r=ruleset: v.ruleset_id != r)
        if structure_type:
            move_type |= versions.filtered(
                lambda v, t=structure_type: v.structure_type_id != t)

    if LIMIT:
        if len(move_ruleset) > LIMIT:
            print(f"\n  SSC_LIMIT={LIMIT}: only the first {LIMIT} of "
                  f"{len(move_ruleset)} would get the ruleset this run")
            move_ruleset = move_ruleset[:LIMIT]
        if len(move_type) > LIMIT:
            print(f"  SSC_LIMIT={LIMIT}: only the first {LIMIT} of "
                  f"{len(move_type)} would get the structure type this run")
            move_type = move_type[:LIMIT]

    # --- what regenerating afterwards would touch -----------------------------

    title("4. what a Regenerate would rewrite afterwards")

    employees = move_ruleset.employee_id
    if not employees:
        print("  no contract changes ruleset, so nothing would need recomputing")
    else:
        earliest = min((v.date_version for v in move_ruleset if v.date_version),
                       default=None)
        print(f"  {len(employees)} employee(s) across {len(move_ruleset)} version(s)")
        print(f"  earliest contract version: {earliest}")
        if Attendance is not None:
            print(f"  attendances on record:     "
                  f"{Attendance.search_count([('employee_id', 'in', employees.ids)])}")
        if Line is not None:
            lines = Line.search([('employee_id', 'in', employees.ids)])
            print(f"  overtime lines today:      {len(lines)} "
                  f"({sum(lines.mapped('duration')):,.1f} h)")
            per_rate = defaultdict(float)
            for line in lines:
                per_rate[round(line.amount_rate, 4)] += line.duration
            for rate, hours in sorted(per_rate.items()):
                print(f"    at rate {rate:<6g} {hours:>10,.1f} h")
        print("\n  This tool does NOT recompute. Use tools/regenerate_overtime.py")
        print("  with a period, so a cycle is re-rated instead of a decade.")

    # --- apply ----------------------------------------------------------------

    title("summary")

    planned_default = (structure and structure_type and default_field
                       and structure_type[default_field] != structure)
    if planned_default:
        print(f"  . point {structure_type.name!r}'s default structure at "
              f"{structure.name!r}")
    if move_ruleset:
        per_company = defaultdict(int)
        for version in move_ruleset:
            per_company[version.company_id.name or '-'] += 1
        for name, count in sorted(per_company.items(), key=lambda kv: -kv[1]):
            print(f"  . {count} version(s) in {name} -> overtime ruleset")
    if move_type:
        print(f"  . {len(move_type)} version(s) -> structure type "
              f"{structure_type.name!r}")
    if not (planned_default or move_ruleset or move_type):
        print("  every contract already carries the configuration it should")

    if not APPLY:
        env.cr.rollback()
        print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write.")
    else:
        written = []
        if planned_default:
            structure_type.write({default_field: structure.id})
            written.append(f"{structure_type.name} now defaults to {structure.name}")
        for company, ruleset in in_scope:
            batch = move_ruleset.filtered(lambda v, c=company: v.company_id == c)
            if batch:
                batch.write({'ruleset_id': ruleset.id})
                written.append(f"{len(batch)} version(s) in {company.name[:28]} "
                               f"-> {ruleset.name}")
        if move_type:
            move_type.write({'structure_type_id': structure_type.id})
            written.append(f"{len(move_type)} version(s) -> {structure_type.name}")
        env.cr.commit()
        print("\nwritten:")
        for line in written or ['(nothing)']:
            print(f"  . {line}")
        print("\nOvertime already on record keeps its old rate until it is")
        print("recomputed - tools/regenerate_overtime.py, with a period.")
