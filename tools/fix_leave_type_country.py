"""Put the leave types in the country the companies are actually in.

    cd ~/src/user

    # report only, writes nothing - read this first:
    odoo-bin shell -d <database> --no-http < tools/fix_leave_type_country.py

    # write, and check the result through the eyes of a real user:
    SSC_USER=it.support@saudconstruction.com SSC_APPLY=1 \
      odoo-bin shell -d <database> --no-http < tools/fix_leave_type_country.py

What is wrong
-------------
Nine of the fourteen active leave types are invisible to every user in the
database, Emergency Leave among them - and the 23 emergency leaves that point
at it cannot be opened, because opening a leave means reading its type.

The rule doing it ships with Odoo 19,
hr_holidays.hr_holidays_status_rule_multi_company:

    ['|', ('company_id', 'in', company_ids),
          '&', ('company_id', '=', False),
               ('country_id', 'in', user.env.companies.country_id.ids + [False])]

A type belonging to no company - which is what a type shared by four companies
has to be - is visible only while its country is empty, or is a country one of
the ticked companies is in. All four companies are in the United Arab Emirates.
The nine hidden types are in Saudi Arabia, Egypt and Switzerland: Iddah and
Hajj give the game away, they came in with the Saudi localisation, Death Leave
with the Egyptian one and Unpaid leave with the Swiss. When 71 types were cut
down to 14, these survived carrying the country of the localisation that
shipped them.

Nobody noticed because every migration ran in `odoo-bin shell`, which runs as
OdooBot - the superuser, who bypasses record rules and therefore never met the
problem that every real user has.

What this writes
----------------
`country_id` on those types, set to the one country all the companies share.
Nothing else: not the name, not the work entry type, not a single leave.

Why the country of the companies rather than an empty country - both would
satisfy the rule. Because it is true: these are the types four UAE companies
take their leave under, and the field is there to say exactly that. Emptying it
would also work today and would silently let a type belong to a company in
another country tomorrow.

If the companies are ever in more than one country this tool stops and says so,
because then there is no single answer and emptying the field is the only
honest one - and that is a decision, not a repair.

In the interface
----------------
  * Time Off > Configuration > Time Off Types > (a type) > Country

Nothing here inherits, patches or extends a native model.

Reads only unless SSC_APPLY=1.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'
AS_USER = (os.environ.get('SSC_USER') or '').strip()

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92
RULE = 'hr_holidays.hr_holidays_status_rule_multi_company'


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def short(text, size=40):
    text = text or '-'
    return text if len(text) <= size else text[:size - 1] + '.'


LeaveType = env['hr.leave.type'].sudo()
Leave = env['hr.leave'].sudo()
Company = env['res.company'].sudo()
Users = env['res.users'].sudo()
ModelData = env['ir.model.data'].sudo()

# ---------------------------------------------------------------------------
title("1. the country the companies are in")

companies = Company.search([])
countries = companies.country_id
for company in companies:
    print(f"  {short(company.name, 46):<46} "
          f"{company.country_id.name or '!! no country'}")

if not countries:
    print("\n  Not one company has a country, so there is nothing to point the")
    print("  types at. Set the country on the companies first - and that is an")
    print("  accounting decision, since it drives the fiscal country too.")
    raise SystemExit
if len(countries) > 1:
    print(f"\n  The companies are in {len(countries)} different countries "
          f"({', '.join(countries.mapped('name'))}).")
    print("  A type shared by all of them cannot carry one country and stay")
    print("  visible in the others, so the only answer is an empty country -")
    print("  and that is your decision to make, not a repair I will do quietly.")
    raise SystemExit

home = countries
print(f"\n  one country for all of them: {home.name}")

# ---------------------------------------------------------------------------
title("2. every active type, and whether the rule lets it through")

rule = env.ref(RULE, raise_if_not_found=False)
print(f"  rule: {rule.name if rule else '(not found!)'}"
      + ("" if not rule else f"   active={rule.active}"))
if rule and not rule.active:
    print("  !! the rule is switched off, so this is NOT what is hiding them.")

types = LeaveType.with_context(active_test=True).search([], order='id')
plan = []
for leave_type in types:
    admitted = (bool(leave_type.company_id)
                or not leave_type.country_id
                or leave_type.country_id in countries)
    # Where it came from. A type carrying Saudi Arabia in a UAE database came
    # in with a localisation, and its origin says so plainly.
    data = ModelData.search([('model', '=', 'hr.leave.type'),
                             ('res_id', '=', leave_type.id)], limit=1)
    origin = f"{data.module}.{data.name}" if data else "made by hand"
    leaves = Leave.search_count([('holiday_status_id', '=', leave_type.id)])
    print(f"      [{leave_type.id:>3}] {short(leave_type.name, 22):<22} "
          f"country={short(leave_type.country_id.name or '(none)', 20):<22} "
          f"{'visible' if admitted else 'HIDDEN ':<8} "
          f"{leaves:>4} leave(s)   {short(origin, 34)}")
    if not admitted:
        plan.append((leave_type, leaves, origin))

# ---------------------------------------------------------------------------
title("3. what would be written")

if not plan:
    print("  every active type is already visible. Nothing to write.")
else:
    for leave_type, leaves, _origin in plan:
        print(f"  [{leave_type.id:>3}] {short(leave_type.name, 24):<24} "
              f"{leave_type.country_id.name or '(none)':<22} -> {home.name}")
    print(f"\n  {len(plan)} type(s), "
          f"{sum(count for _t, count, _o in plan)} leave(s) behind them.")
    print("  country_id only. No name, no work entry type, no leave is touched.")

# ---------------------------------------------------------------------------
if not APPLY:
    env.cr.rollback()
    print("")
    print("report only - nothing written. Re-run with SSC_APPLY=1 to write.")
else:
    for leave_type, _leaves, _origin in plan:
        # country_id is computed from company_id and stored, but the compute
        # only assigns when the type HAS a company. These have none, so the
        # written value is not recomputed away.
        leave_type.write({'country_id': home.id})
    env.cr.commit()
    print("")
    print("written:")
    for leave_type, _leaves, _origin in plan:
        print(f"  . [{leave_type.id}] {leave_type.name} -> "
              f"{leave_type.country_id.name}")
    if not plan:
        print("  . (nothing)")

# ---------------------------------------------------------------------------
title("4. through the eyes of a real user")

# Reading only, so it runs whether or not anything was written - the report
# run should show the problem as plainly as the repair run shows it gone.
#
# Resolving the login loosely is how the first version of this section died:
# 'it.support@saudconstruction.com' is uid 17's LOGIN and uid 6's EMAIL, and a
# search returns the lower id first. Uid 6 carries the same person's name and
# not one Time Off right, so the check blew up on an account that was never
# the subject. Exact login first, then exact email, and an internal user in
# preference to whatever else answers.
user = env.user
if AS_USER:
    matches = Users.browse()
    for domain in ([('login', '=', AS_USER)],
                   [('email', '=', AS_USER)],
                   ['|', ('login', 'ilike', AS_USER), ('name', 'ilike', AS_USER)]):
        matches = Users.search(domain)
        if matches:
            break
    usable = matches.filtered(
        lambda u: u.active and not u.share and u.has_group('base.group_user'))
    user = (usable[:1] or matches[:1]) or env.user
    if len(matches) > 1:
        print(f"  {len(matches)} accounts answer to {AS_USER!r}: "
              + ", ".join(f"[{u.id}] {u.login}" for u in matches))

if user.id == 1:
    print("  running as OdooBot, who bypasses record rules and would say yes to")
    print("  anything. Pass SSC_USER=<a real login> to see what the screen shows.")
else:
    print(f"  reading as [{user.id}] {user.name} <{user.login}>"
          + ("   !! not an internal user - the Time Off app does not open for it"
             if user.share or not user.has_group('base.group_user') else ""))
    # The values just written sit in this transaction's cache, and a cached
    # value is handed back with no query and no rule consulted. Reading them
    # from there would prove nothing about the rule being tested.
    env.invalidate_all()
    visible = LeaveType.with_user(user).with_context(active_test=True).search([])
    print("")
    print(f"  {len(visible)} of {len(types)} active type(s) visible:")
    for leave_type in types:
        print(f"      [{leave_type.id:>3}] {short(leave_type.name, 26):<26} "
              f"{'visible' if leave_type in visible else 'HIDDEN'}")

    # One leave of each type that carries a country - those are the ones the
    # rule can hide, and the only ones whose verdict has changed.
    for leave_type in types.filtered('country_id'):
        sample = Leave.search([('holiday_status_id', '=', leave_type.id)], limit=1)
        if not sample:
            continue
        env.invalidate_all()
        try:
            scoped = sample.with_user(user)
            scoped.read()
            scoped.holiday_status_id.display_name
            print("")
            print(f"  /odoo/time-off/{sample.id} ({leave_type.name}) opens.")
        except Exception as error:
            print("")
            print(f"  /odoo/time-off/{sample.id} ({leave_type.name}) "
                  f"refuses: {str(error).strip().splitlines()[0]}")
