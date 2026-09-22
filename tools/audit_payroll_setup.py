"""The whole payroll chain, read out loud, with the holes marked.

    odoo-bin shell -d <database> --no-http < tools/audit_payroll_setup.py

Read only. Nothing is written, ever.

A payslip is the end of a chain, and every link has to hold: a company, a
structure type on the contract, a structure on that type, rules on the
structure, a wage split across the right fields, a calendar, a source of work
entries, and work entries actually generated for the period. Break any one and
the payslip is quietly wrong rather than loudly absent.

This walks the chain for labour and for staff separately, because they are paid
differently on purpose - labour from the punch, staff from the schedule - and
prints what is configured, what each rule does, and what is missing.
"""
from collections import defaultdict
from datetime import date

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

Employee = env['hr.employee'].sudo()
Version = env['hr.version'].sudo()
Structure = env['hr.payroll.structure'].sudo()
StructureType = env['hr.payroll.structure.type'].sudo()
Rule = env['hr.salary.rule'].sudo()
WorkEntryType = env['hr.work.entry.type'].sudo()
WorkEntry = env['hr.work.entry'].sudo()
LeaveType = env['hr.leave.type'].sudo()
Attendance = env['hr.attendance'].sudo()
Payslip = env['hr.payslip'].sudo()
InputType = env['hr.payslip.input.type'].sudo()

gaps = []


def title(text):
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


def gap(text):
    gaps.append(text)
    print(f"  MISSING  {text}")


active = Employee.with_context(active_test=True).search([])
live_versions = active.mapped('current_version_id')

# ---------------------------------------------------------------------------
title("1. who is being paid, and on what")

by_type = defaultdict(lambda: env['hr.employee'])
for person in active:
    by_type[person.current_version_id.structure_type_id] += person

print(f"  {len(active)} active employee(s)")
print()
print(f"  {'structure type':<52} {'people':>7}  {'structure'}")
for stype, people in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
    if not stype:
        gap(f"{len(people)} employee(s) have no structure type on their contract")
        continue
    structs = Structure.search([('type_id', '=', stype.id)])
    label = ' / '.join(s.name for s in structs) or 'NONE'
    print(f"  {stype.name[:52]:<52} {len(people):>7}  {label[:40]}")
    if not structs:
        gap(f"structure type {stype.name!r} carries {len(people)} people and has no structure")
    elif len(structs) > 1:
        gap(f"structure type {stype.name!r} has {len(structs)} structures - "
            f"which one a payslip picks is not decided")

# ---------------------------------------------------------------------------
title("2. the contract each payslip reads")

checks = [
    ('no wage at all', lambda v: not v.wage),
    ('no contract start date', lambda v: not v.contract_date_start),
    ('contract already ended', lambda v: v.contract_date_end and v.contract_date_end < date.today()),
    ('no working calendar', lambda v: not v.resource_calendar_id),
    ('no structure type', lambda v: not v.structure_type_id),
]
print(f"  {len(live_versions)} live contract(s)")
print()
for label, test in checks:
    hit = live_versions.filtered(test)
    marker = 'MISSING ' if hit and 'ended' not in label else '        '
    print(f"  {marker}{label:<34} {len(hit):>5}")
    if hit and 'ended' not in label:
        gaps.append(f"{len(hit)} contract(s): {label}")

print()
print(f"  {'work entry source':<34} {'people'}")
for source in ('attendance', 'calendar'):
    print(f"  {source:<34} {len(live_versions.filtered(lambda v: v.work_entry_source == source))}")
print()
print(f"  {'overtime ruleset':<34} {'people'}")
for ruleset, versions in sorted(live_versions.grouped('ruleset_id').items(),
                                key=lambda kv: -len(kv[1])):
    print(f"  {(ruleset.name if ruleset else 'none'):<34} {len(versions)}")

# ---------------------------------------------------------------------------
title("3. how the money is put together, rule by rule")

for struct in Structure.browse((19, 24)).exists():
    print()
    print(f"  {struct.name}")
    print(f"  {'seq':>4} {'code':<14} {'cat':<6} {'amount':<8} {'condition':<10} name")
    for rule in Rule.search([('struct_id', '=', struct.id), ('active', '=', True)],
                            order='sequence, id'):
        print(f"  {rule.sequence:>4} {rule.code:<14} "
              f"{(rule.category_id.code or ''):<6} {rule.amount_select:<8} "
              f"{rule.condition_select:<10} {rule.name[:40]}")

# ---------------------------------------------------------------------------
title("4. the work entry types the rules look for")

for code in ('WORK100', 'SSC_OT_REG', 'SSC_OT_OFF', 'LEAVE120', 'LEAVE110',
             'AESICKLEAVE50', 'AESICKLEAVE0', 'LEAVE90', 'LEAVE100', 'OUT'):
    entry = WorkEntryType.search([('code', '=', code)], limit=1)
    if not entry:
        gap(f"work entry type {code} does not exist")
        continue
    print(f"  {code:<14} rate={entry.amount_rate:<6} is_leave={str(entry.is_leave):<6} "
          f"{entry.name[:40]}")

# ---------------------------------------------------------------------------
title("5. time off, and whether payroll can see it")

for leave_type in LeaveType.search([('active', '=', True)], order='id'):
    entry = leave_type.work_entry_type_id
    if not entry:
        gap(f"leave type {leave_type.name!r} has no work entry type - "
            f"payroll cannot price it")
        continue
    print(f"  {leave_type.name[:30]:<30} -> {entry.code:<14} "
          f"is_leave={str(entry.is_leave):<6} allocation={leave_type.requires_allocation}")

# ---------------------------------------------------------------------------
title("6. what the engine actually has to work with")

first = date.today().replace(day=1)
month_start = (first.replace(day=1) - date.resolution).replace(day=1)
month_end = first - date.resolution
print(f"  last complete month: {month_start} .. {month_end}")
print()
print(f"  {'code':<14} {'people':>7} {'days':>7} {'hours':>10}")
totals = defaultdict(lambda: [set(), set(), 0.0])
for entry in WorkEntry.search([('date', '>=', month_start), ('date', '<=', month_end),
                               ('state', '!=', 'cancelled')]):
    row = totals[entry.work_entry_type_id.code]
    row[0].add(entry.employee_id.id)
    row[1].add(entry.date)
    row[2] += entry.duration
for code, (people, days, hours) in sorted(totals.items(), key=lambda kv: -kv[1][2]):
    print(f"  {code:<14} {len(people):>7} {len(days):>7} {hours:>10,.1f}")
if not totals:
    gap(f"no work entries at all for {month_start:%B %Y}")

punching = Attendance.search([('check_in', '>=', month_start),
                              ('check_in', '<=', month_end)]).mapped('employee_id')
on_attendance = live_versions.filtered(lambda v: v.work_entry_source == 'attendance')
silent = on_attendance.mapped('employee_id') - punching
print()
print(f"  paid from the punch and never punched last month: {len(silent)}")
if silent:
    gaps.append(f"{len(silent)} employee(s) are paid from attendance and did not punch "
                f"at all last month - they would be paid nothing")

# ---------------------------------------------------------------------------
title("7. the parts nobody has set up yet")

if not env['resource.calendar.leaves'].sudo().search_count([('resource_id', '=', False)]):
    gap("no public holidays on any working calendar")
if not Payslip.search_count([]):
    gap("no payslip has ever been created")
if not env['hr.payslip.run'].sudo().search_count([]):
    gap("no payslip batch has ever been created")

print()
print("  payslip inputs available for manual entry:")
for kind in InputType.search([], order='code'):
    print(f"      {kind.code:<22} {kind.name}")

# journal_id on a structure is company-dependent - stored as jsonb keyed by
# company id - so reading it in one company's context says nothing about the
# others. Royal Arrow's structure holds its journal under Royal Arrow's key and
# looks empty from Saud Shehatha. Ask every company.
Company = env['res.company'].sudo()
all_companies = Company.search([])
print()
print("  salary journal per structure, read in each company's own context")
ours = Structure.search([('type_id.name', '!=', False)]).filtered(
    lambda s: any(word in (s.name or '') for word in
                  ('Labour Pay', 'Staff Pay')))
for struct in ours.sorted('id'):
    holders = [(c, struct.with_company(c).journal_id) for c in all_companies]
    holders = [(c, j) for c, j in holders if j]
    if not holders:
        gap(f"structure {struct.name!r} has no accounting journal in any company")
        continue
    # The structure's OWN company's journal is the right answer under every
    # key - the payslip copies the journal in the context of whoever creates
    # it, and batches are made with one company active for all four. What is
    # wrong is a journal belonging to neither the key's company nor the
    # structure's owner, or a key with nothing under it.
    owner_name = (struct.name or '').strip().upper()
    owner = next((c for c in all_companies
                  if owner_name.startswith((c.name or '').strip().upper())), None)
    for company, journal in holders:
        fine = journal.company_id == company or (owner and journal.company_id == owner)
        mark = '' if fine else '   <-- neither this company nor the owner'
        print(f"      {struct.name[:44]:<44} {company.name[:26]:<26} "
              f"{journal.display_name}{mark}")
        if not fine:
            gaps.append(f"structure {struct.name!r} points at "
                        f"{company.name}'s key but {journal.company_id.name}'s journal")
    missing_keys = [c for c in all_companies
                    if not struct.with_company(c).journal_id]
    if missing_keys:
        gaps.append(f"structure {struct.name!r} has no journal under "
                    f"{', '.join(c.name for c in missing_keys)} - a payslip made "
                    f"with that company active copies an empty journal "
                    f"(tools/fix_salary_journals.py)")

# ---------------------------------------------------------------------------
title("what is missing")

if not gaps:
    print("  nothing this file knows how to check")
for line in gaps:
    print(f"  - {line}")
