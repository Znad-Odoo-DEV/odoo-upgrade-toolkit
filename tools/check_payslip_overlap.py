"""How many payslips are already on our side, and would a re-sync duplicate them?

    odoo-bin shell --no-http --shell-interface=python < tools/check_payslip_overlap.py

Reads only, and it exists because the earlier audit answered a narrower question
than the one that matters. It counted how many ssc.payslip records carry a
studio_ref_id and found none, and reported that as 4,584 missing. It never asked
how many ssc.payslip records there are.

Those are not the same thing. A payslip created by hand, or by a migration that
did not fill studio_ref_id, is a payslip that exists - and the mirror would not
find it, because the mirror looks for the reference and nothing else:

    mirror = Slip.search([('studio_ref_id', '=', src.id)], limit=1)
    if mirror: write   else: create

So a re-sync against 4,584 Studio rows would create 4,584 records, on top of
whatever is already there, and the duplicates would be indistinguishable from
the originals a week later.

This asks the whole question: what is on our side, what is on theirs, and how
much of it is the same payslip - matched on the thing that identifies one, which
is an employee and a month and a year, not a reference number that was never
written.
"""
SOURCE = 'x_all_payslips'
TARGET = 'ssc.payslip'

# candidates for the same three facts on the Studio side
S_EMPLOYEE = ('x_studio_employee', 'x_studio_for_employee', 'x_studio_employee_1')
S_MONTH = ('x_studio_month', 'x_studio_salary_month', 'x_studio_period')
S_YEAR = ('x_studio_year', 'x_studio_salary_year')
S_NET = ('x_studio_net_amount', 'x_studio_net_salary', 'x_studio_total_salary',
         'x_studio_total_amount')

cr = env.cr                                                      # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def pick(Model, candidates):
    for name in candidates:
        if name in Model._fields:
            return name
    return None


Source = env.get(SOURCE)                                         # noqa: F821
Target = env.get(TARGET)                                         # noqa: F821
if Source is None or Target is None:
    raise SystemExit("%s or %s is not in this database." % (SOURCE, TARGET))
Source = Source.sudo().with_context(active_test=False)
Target = Target.sudo().with_context(active_test=False)


# --- 1. the counts nobody asked for ------------------------------------------

title("1. how many there are")

ours = Target.search([])
with_ref = ours.filtered('studio_ref_id')
theirs = Source.search([])

print("  %-28s %s" % (SOURCE, len(theirs)))
print("  %-28s %s" % (TARGET, len(ours)))
print("      carrying a studio_ref_id  %s" % len(with_ref))
print("      carrying none             %s" % (len(ours) - len(with_ref)))

if not ours:
    print("\n  Our side is empty. A re-sync creates rather than duplicates.")


# --- 2. the same payslip, however it got here --------------------------------

title("2. matching on employee, month and year")

s_employee = pick(Source, S_EMPLOYEE)
s_month = pick(Source, S_MONTH)
s_year = pick(Source, S_YEAR)
s_net = pick(Source, S_NET)
print("  %s uses: employee=%s  month=%s  year=%s  net=%s"
      % (SOURCE, s_employee, s_month, s_year, s_net))
print("  %s uses: employee=employee_id  month=month  year=year" % TARGET)

if not s_employee:
    links = sorted(n for n, f in Source._fields.items()
                   if f.type == 'many2one' and n.startswith('x_'))
    print("\n  No employee field found on %s. It has these links:" % SOURCE)
    print("      %s" % ', '.join(links[:20]))
    raise SystemExit("Tell me which one names the employee and I will redo this.")


def norm(value):
    return str(value or '').strip().lower()[:3]


def their_key(record):
    employee = record[s_employee]
    # the Studio employee is an hr.employee since the repoint
    return (employee.id if employee else 0,
            norm(record[s_month] if s_month else ''),
            str(record[s_year] if s_year else '')[:4])


def our_key(slip):
    # ours names the employee on ssc.employee; compare through hr.employee,
    # which is the one both sides now have in common
    employee = slip.employee_id.hr_employee_id or slip.hr_employee_id
    return (employee.id if employee else 0,
            norm(slip.month), str(slip.year or '')[:4])


theirs_by_key, ours_by_key = {}, {}
for record in theirs:
    theirs_by_key.setdefault(their_key(record), []).append(record)
for slip in ours:
    ours_by_key.setdefault(our_key(slip), []).append(slip)

both = set(theirs_by_key) & set(ours_by_key)
only_theirs = set(theirs_by_key) - set(ours_by_key)
only_ours = set(ours_by_key) - set(theirs_by_key)

print("\n  on both sides            %s" % len(both))
print("  only in %-16s %s" % (SOURCE, len(only_theirs)))
print("  only in %-16s %s" % (TARGET, len(only_ours)))

no_employee = len([k for k in theirs_by_key if not k[0]])
if no_employee:
    print("  %s Studio key(s) name no employee at all" % no_employee)


# --- 3. what a re-sync would do ----------------------------------------------

title("3. what a re-sync would do")

print("""  The mirror finds an existing record by studio_ref_id and by nothing else.
  %s Studio row(s) carry no matching reference on our side, so each one would
  be created.

  Of those, %s already exist here as a payslip for the same employee and month.
  Those would become a second copy of a payslip that is already there.""" % (
    len(theirs) - len(with_ref & Target.browse([])) if False else len(theirs),
    len(both)))

if both:
    print("\n  a few of them:")
    Employee = env['hr.employee'].sudo()                         # noqa: F821
    for key in sorted(both)[:12]:
        who = Employee.browse(key[0]).display_name if key[0] else '-'
        mine = ours_by_key[key]
        print("      %-34s %-5s %-6s ours=%s theirs=%s"
              % (who[:34], key[1], key[2], len(mine), len(theirs_by_key[key])))


# --- 4. the money, where both sides have one ---------------------------------

if both and s_net:
    title("4. the money on the rows that exist twice")
    agree, differ, examples = 0, 0, []
    for key in both:
        a = sum(r[s_net] or 0.0 for r in theirs_by_key[key])
        b = sum(s.net_amount or 0.0 for s in ours_by_key[key]
                if 'net_amount' in s._fields)
        if abs(a - b) < 0.01:
            agree += 1
        else:
            differ += 1
            if len(examples) < 10:
                examples.append((key, a, b))
    print("  same amount   %s" % agree)
    print("  different     %s" % differ)
    Employee = env['hr.employee'].sudo()                         # noqa: F821
    for (employee_id, month, year), a, b in examples:
        who = Employee.browse(employee_id).display_name if employee_id else '-'
        print("      %-32s %-5s %-6s studio %-12s ours %s"
              % (who[:32], month, year, round(a, 2), round(b, 2)))


title("read this before running any sync")
print("""  If "on both sides" above is large, the re-sync must not be run as it stands.
  It would need to match on the employee and the month first, write
  studio_ref_id onto the record already here, and only create where there is
  genuinely nothing - which is a different tool, and one worth writing rather
  than working around.""")
