"""Why a Time Off record will not open.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http < tools/diagnose_emergency_leave.py

    # the run that matters - as the person who sees the failure:
    SSC_USER=<your login> odoo-bin shell -d <database> --no-http \
      < tools/diagnose_emergency_leave.py

This one writes nothing at all. There is no SSC_APPLY.

The migration did not invent the type
-------------------------------------
tools/migrate_annual_leave_to_hr.py reads x_all_requests, keeps the rows whose
kind is ELR, and files each one against a leave type it LOOKS UP by the exact
name 'Emergency Leave', active. Had that type been missing the script would
have printed "leave type 'Emergency Leave' does not exist - stopping" and moved
nothing. The 23 records are the proof it was there.

What the first run ruled out
----------------------------
Type 72 is active, sits on no company at all, is listed among the fourteen, and
reads without complaint. So the type is not archived and it is not somebody
else's. Both of the easy answers are gone.

What is left, and what this looks for
-------------------------------------
  * THE COMPANY SWITCHER. The record rule on hr.leave is
    ['|', ('company_id', '=', False), ('company_id', 'in', company_ids)], and
    company_ids is whatever is TICKED in the switcher, not what the user is
    allowed. Emergency Leave 599 belongs to ROYAL ARROW while the shell sits in
    SAUD. So every sample is opened here under three different company
    selections, and the one that refuses names the cause.

  * THE FORM ITSELF. A record that will not open without so much as a red
    popup is usually a view that cannot be built, not a record that cannot be
    read - a Studio inheritance still pointing at a field somebody removed.
    That breaks get_views for EVERY leave, not only the emergency ones, which
    is why an annual leave is opened here beside an emergency one. If both
    fail, the type was never the problem.

  * WHO YOU ARE. `odoo-bin shell` runs as OdooBot, who is in all four
    companies and has every right, so it meets neither problem. SSC_USER is
    the whole point of the tool; when it matches nothing, section 3 now prints
    the logins to choose from instead of quietly carrying on as OdooBot.
"""
import os

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92
AS_USER = (os.environ.get('SSC_USER') or '').strip()
NEEDLE = (os.environ.get('SSC_LEAVE_TYPE') or 'emergency').strip().lower()


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def short(text, size=40):
    text = text or '-'
    return text if len(text) <= size else text[:size - 1] + '.'


def first_line(error):
    text = str(error).strip().splitlines()
    return text[0] if text else type(error).__name__


LeaveType = env['hr.leave.type'].sudo()
Leave = env['hr.leave'].sudo()
Users = env['res.users'].sudo()
Company = env['res.company'].sudo()
View = env['ir.ui.view'].sudo()

# ---------------------------------------------------------------------------
title("1. the type, and where its records live")

target = LeaveType.search([]).filtered(lambda t: NEEDLE in (t.name or '').lower())
if not target:
    print(f"  no leave type has {NEEDLE!r} in its name. Nothing else to say.")

for leave_type in target:
    leaves = Leave.search([('holiday_status_id', '=', leave_type.id)])
    print(f"\n  [{leave_type.id}] {leave_type.name}   active={leave_type.active}   "
          f"company={leave_type.company_id.name or '(all companies)'}")
    # A record is refused by company, so counting the records BY company is the
    # question worth asking - not how many there are.
    by_company = {}
    for leave in leaves:
        by_company.setdefault(leave.company_id, 0)
        by_company[leave.company_id] += 1
    for company, count in sorted(by_company.items(), key=lambda kv: -kv[1]):
        print(f"      {count:>4} record(s) in {company.name or '(no company)'}")

# ---------------------------------------------------------------------------
title("2. who is reading")

# Matching loosely and taking the first hit is how the last run measured uid 6
# - an account carrying this name and no right to read a single leave - and
# reported its refusal as though it were yours. So: exact login first, then
# exact email, and only then a loose match; every candidate is printed, and an
# account that is not an internal user is called out rather than trusted.
user = env.user
matches = Users.browse()
if AS_USER:
    for domain in ([('login', '=', AS_USER)],
                   [('email', '=', AS_USER)],
                   ['|', '|', ('login', 'ilike', AS_USER),
                    ('name', 'ilike', AS_USER), ('email', 'ilike', AS_USER)]):
        matches = Users.search(domain)
        if matches:
            break

def describe(record):
    kind = 'portal/share' if record.share else 'internal'
    officer = record.has_group('hr_holidays.group_hr_holidays_user')
    manager = record.has_group('hr_holidays.group_hr_holidays_manager')
    rights = ('manager' if manager else 'officer' if officer
              else 'own leaves only' if not record.share else 'no Time Off at all')
    return f"{kind:<12} {rights:<16} active={record.active}"

if matches:
    print(f"  {len(matches)} account(s) match {AS_USER!r}:")
    for record in matches:
        print(f"      [{record.id:>3}] {short(record.login, 34):<34} "
              f"{short(record.name, 26):<26} {describe(record)}")
    # An account that cannot read a leave cannot be the one whose browser shows
    # the kanban, so it is not the one to measure.
    usable = matches.filtered(lambda u: not u.share and u.active)
    user = (usable[:1] or matches[:1])
    if len(matches) > 1:
        print(f"  reading as [{user.id}] {user.login} - if that is not the")
        print("  account in your browser, re-run with its exact login.")
elif AS_USER:
    print(f"  !! nothing matches {AS_USER!r}. These accounts can see Time Off:")
    for record in Users.search([('share', '=', False), ('active', '=', True)],
                               order='login'):
        if record.has_group('hr_holidays.group_hr_holidays_user'):
            print(f"      SSC_USER={record.login:<38} {short(record.name, 30)}")
else:
    print(f"  running as {env.user.name} - pass SSC_USER=<your login> to read as")
    print("  yourself. OdooBot is in every company and meets no access problem.")

print("")
print(f"  reading as [{user.id}] {user.name} <{user.login}>   {describe(user)}")
print("  allowed companies: "
      + ", ".join(short(c.name, 28) for c in user.company_ids))
if user.share or not user.has_group('base.group_user'):
    print("")
    print("  !! this is NOT an internal user. The Time Off app does not open for")
    print("     it at all, so everything below measures the wrong account and")
    print("     says nothing about your problem. Find your own login in")
    print("     Settings > Users and re-run with it.")

# ---------------------------------------------------------------------------
title("3. can the form even be built")

# A record that will not open and says nothing is usually this: the view fails
# to assemble, so the dialog never appears. It would fail for every leave, not
# only the ones of one type - which is exactly what makes it worth separating.
for view_type in ('form', 'kanban', 'list'):
    try:
        env['hr.leave'].with_user(user).get_views([(False, view_type)])
        print(f"  hr.leave {view_type:<7} builds")
    except Exception as error:
        print(f"  hr.leave {view_type:<7} FAILS - {type(error).__name__}")
        print(f"      {first_line(error)}")

studio = View.search([('model', '=', 'hr.leave')]).filtered(
    lambda v: (v.name or '').lower().startswith('odoo studio')
    or (v.key or '').startswith('studio_customization'))
print(f"\n  Studio views on hr.leave: {len(studio)}")
for view in studio:
    print(f"      [{view.id}] {short(view.name, 46):<46} active={view.active}")

# ---------------------------------------------------------------------------
title("4. opening one record of each type, under each company selection")

# The web client sends allowed_company_ids straight from the switcher, so the
# same record opens or refuses depending on what is ticked. One sample per type
# tells whether this is about Emergency Leave at all.
samples = []
for leave_type in (target | LeaveType.search([('id', 'in', Leave.search([]).
                                               holiday_status_id.ids)])):
    sample = Leave.search([('holiday_status_id', '=', leave_type.id)], limit=1)
    if sample:
        samples.append((leave_type, sample))

scopes = [("every company the user has", user.company_ids.ids)]
for company in Company.search([]):
    if company in user.company_ids:
        scopes.append((f"only {short(company.name, 34)}", [company.id]))

for leave_type, sample in samples:
    print(f"\n  {leave_type.name} - hr.leave [{sample.id}] "
          f"{short(sample.employee_id.name, 30)}, company "
          f"{short(sample.company_id.name, 30)}")
    print(f"      /odoo/time-off/{sample.id}")
    for label, company_ids in scopes:
        scoped = sample.with_user(user).with_context(allowed_company_ids=company_ids)
        try:
            # Section 1 read these as the superuser, and a value already in the
            # transaction's cache is handed back without a query - so without
            # this the type's display_name comes from cache and NO rule is ever
            # consulted. That is what made this section report "opens" on a
            # record whose type the user cannot read.
            env.invalidate_all()
            scoped.read()
            # Reading is not opening: the client also asks the record to render
            # its name and its type, and either can refuse on its own.
            scoped.holiday_status_id.display_name
            print(f"      {label:<38} opens")
        except Exception as error:
            print(f"      {label:<38} REFUSED - {type(error).__name__}")
            print(f"          {first_line(error)}")

# ---------------------------------------------------------------------------
title("5. the configuration list, as you, under each company selection")

# The second complaint: Emergency Leave is not in Time Off Types. As OdooBot it
# is - fourteen types, 72 among them. So the question is not whether it exists
# but whether the screen shows it TO YOU, with what you have ticked. The list
# hides an archived type by itself, and the record rule hides another company's,
# so both are asked here at once.
for label, company_ids in scopes:
    listed = env['hr.leave.type'].with_user(user).with_context(
        active_test=True, allowed_company_ids=company_ids).search([])
    names = [t.name for t in listed]
    print("")
    print(f"  {label} - {len(listed)} type(s)")
    for leave_type in target:
        mark = 'listed' if leave_type in listed else 'NOT LISTED'
        print(f"      {leave_type.name:<26} {mark}")
    print("      " + ", ".join(short(name, 22) for name in names))

# ---------------------------------------------------------------------------
title("6. the rule that hides them, in its own terms")

# hr_holidays.hr_holidays_status_rule_multi_company, shipped with Odoo 19:
#
#   ['|', ('company_id', 'in', company_ids),
#         '&', ('company_id', '=', False),
#              ('country_id', 'in', user.env.companies.country_id.ids + [False])]
#
# So a type belonging to NO company - which is what a type shared by four
# companies has to be - is visible only while its country is empty or is a
# country one of the ticked companies is in. Both sides of that comparison are
# printed here, because a type carrying a country and a company carrying none
# can never meet.
rule = env.ref('hr_holidays.hr_holidays_status_rule_multi_company',
               raise_if_not_found=False)
print(f"  rule: {rule.name if rule else '(not found)'}"
      + ("" if not rule else f"   active={rule.active}"))

print("")
print("  each company's country - the right-hand side of the comparison:")
countries = env['res.country'].browse()
for company in Company.search([]):
    countries |= company.country_id
    print(f"      {short(company.name, 44):<44} "
          f"{company.country_id.name or '!! none'}")
if not countries:
    print("      -> not one company has a country, so the only types anybody can")
    print("         see are the ones whose country is empty too.")

print("")
print("  each active type - the left-hand side:")
for leave_type in LeaveType.with_context(active_test=True).search([], order='id'):
    admitted = (leave_type.company_id in user.company_ids if leave_type.company_id
                else (not leave_type.country_id or leave_type.country_id in countries))
    print(f"      [{leave_type.id:>3}] {short(leave_type.name, 26):<26} "
          f"company={short(leave_type.company_id.name, 22) if leave_type.company_id else '(none)':<24} "
          f"country={leave_type.country_id.name or '(none)':<24} "
          f"{'visible' if admitted else 'HIDDEN'}")

# ---------------------------------------------------------------------------
title("7. if everything above opens")

print("  then the failure is in the browser, not in the data, and only two")
print("  things say what it is:")
print("    * the red popup's text, copied as it stands; or")
print("    * odoo.sh > Logs, at the second you click the card - a traceback")
print("      there names the field or the view that broke.")
print("  A card that opens a blank dialog and logs nothing on the server is a")
print("  client-side error: F12 > Console, and send the first red line.")
env.cr.rollback()
