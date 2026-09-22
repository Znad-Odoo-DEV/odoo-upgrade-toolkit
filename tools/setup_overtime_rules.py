"""Give each overtime rule the pay rate it is meant to carry.

    # report only, writes nothing:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/setup_overtime_rules.py

    # same again, this time writing:
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http 2>/dev/null < tools/setup_overtime_rules.py

    # other rates:
    SSC_RATE_REG=1.25 SSC_RATE_OFF=1.5 SSC_APPLY=1 odoo-bin shell ...

The rate cannot be typed on the rule, and that is deliberate. With Payroll
installed the field is computed:

    @api.depends('work_entry_type_id')
    def _compute_amount_rate(self):
        for rule in self:
            rule.amount_rate = rule.work_entry_type_id.amount_rate

and the form marks it readonly. The rate belongs to the WORK ENTRY TYPE, so two
rules that must pay differently need two types - pointing both at the shared
"Overtime Hours" leaves them both on whatever that type says, which is why they
read 100% however often the number is retyped.

So this creates one work entry type per rate, points each rule at the right one,
and lets the rate follow. On a database where the field is NOT computed - Payroll
absent - it writes the rate straight onto the rule instead, and says so.

Rules are matched by name: one containing "off" is the off-day rule, any other
paid rule is the working-day rule. Rates are multipliers: 1.25 is 125%.

Only rulesets whose name contains SSC_RULESET (default "Overtime") are touched -
the Legacy Rules the upgrade left behind and Odoo's Default Ruleset are listed
and left alone.

Reads only unless SSC_APPLY=1.
"""
import os

APPLY = os.environ.get('SSC_APPLY') == '1'
RATE_REG = float(os.environ.get('SSC_RATE_REG') or 1.25)
RATE_OFF = float(os.environ.get('SSC_RATE_OFF') or 1.5)

# A type that already exists keeps the rate it was given. These defaults are a
# starting point, not an opinion worth overwriting a decision with: a re-run
# that forgot SSC_RATE_REG must not quietly pull 130% back down to 125%.
FORCE_RATE = os.environ.get('SSC_FORCE_RATE') == '1'

# Only the rulesets we built get re-rated. The database also carries Odoo's
# Default Ruleset and the Legacy Rules the upgrade left behind, and re-rating
# those would change overtime for people nobody meant to touch. Matched on the
# name, case-insensitive; widen it deliberately if that is really wanted.
SCOPE = os.environ.get('SSC_RULESET') or 'Overtime'

# One type per rate. Codes are ours, so they cannot collide with the shared
# OVERTIME type the localization also prices.
WANTED_TYPES = {
    'reg': {'code': 'SSC_OT_REG', 'name': 'SSC Overtime - Working Days',
            'rate': RATE_REG},
    'off': {'code': 'SSC_OT_OFF', 'name': 'SSC Overtime - Off Days',
            'rate': RATE_OFF},
}

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

WIDTH = 92
MODEL = 'hr.attendance.overtime.rule'


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


if MODEL not in env:
    print(f"{MODEL} does not exist on this database - this Odoo has no overtime "
          f"rulesets.")
else:
    Rule = env[MODEL].sudo()

    # --- 1. what the field is ------------------------------------------------

    title("1. the field in the registry")

    field = Rule._fields.get('amount_rate')
    if field is None:
        print("  amount_rate does not exist on this model")
    else:
        for name in ('type', 'readonly', 'required', 'store', 'related',
                     'compute', 'company_dependent'):
            print(f"  {name:<18} {getattr(field, name, None)}")
        print("\n  readonly=True here would mean the model itself forbids typing;")
        print("  False means the refusal comes from a view or from access rights.")

    # --- 2. every view that mentions it --------------------------------------

    title("2. views mentioning amount_rate on this model")

    views = env['ir.ui.view'].sudo().search([('model', '=', MODEL)], order='id')
    touching = []
    for view in views:
        arch = view.arch_db or ''
        if 'amount_rate' in arch:
            touching.append((view, arch))
    print(f"  {len(views)} view(s) on the model, {len(touching)} mention the field")
    for view, arch in touching:
        module = view.xml_id.split('.')[0] if view.xml_id else '(no xml id)'
        studio = 'STUDIO' if 'studio' in (view.xml_id or '').lower() else ''
        print(f"\n  [{view.id}] {view.name}")
        print(f"      type={view.type}  from={module} {studio}")
        print(f"      inherits={view.inherit_id.name or '-'}  active={view.active}")
        for line in arch.splitlines():
            if 'amount_rate' in line:
                stripped = line.strip()
                flag = '  <-- LOCKS IT' if 'readonly' in stripped else ''
                print(f"      {stripped[:150]}{flag}")

    # Any view at all that carries a readonly on this model, even without naming
    # the field - a readonly on the whole form would do it too.
    for view in views:
        arch = view.arch_db or ''
        if 'readonly' in arch and 'amount_rate' not in arch:
            print(f"\n  [{view.id}] {view.name}: carries a readonly elsewhere in the "
                  f"arch - worth a look")

    # --- 3. may this user write it at all ------------------------------------

    title("3. access")

    user = env.user
    print(f"  user: {user.name} (id {user.id})")
    for operation in ('read', 'write', 'create', 'unlink'):
        try:
            allowed = env[MODEL].with_user(user).check_access(operation) is None
        except Exception:                                        # noqa: BLE001
            allowed = False
        print(f"  {operation:<8} {'yes' if allowed else 'NO'}")

    rules = env['ir.rule'].sudo().search([('model_id.model', '=', MODEL)])
    print(f"  {len(rules)} record rule(s) on the model")
    for record_rule in rules:
        print(f"    {record_rule.name}: {record_rule.domain_force}")

    # --- 3b. companies with no ruleset of their own --------------------------

    title("3b. companies missing a ruleset")

    Ruleset = env['hr.attendance.overtime.ruleset'].sudo()
    Company = env['res.company'].sudo()
    Version = env['hr.version'].sudo() if 'hr.version' in env else None

    # Copied from a ruleset that already works rather than written out here, so
    # every company ends up with the same rules - including which work entry
    # type each one points at, which is what carries the rate.
    COPY_FIELDS = [
        'name', 'sequence', 'base_off', 'timing_type', 'timing_start',
        'timing_stop', 'expected_hours_from_contract', 'expected_hours',
        'quantity_period', 'resource_calendar_id', 'paid', 'employee_tolerance',
        'employer_tolerance', 'work_entry_type_id',
    ]

    def in_scope(ruleset):
        return SCOPE.lower() in (ruleset.name or '').lower()

    template_name = os.environ.get('SSC_TEMPLATE')
    candidates = Ruleset.search([]).filtered(in_scope)
    if template_name:
        template = candidates.filtered(lambda r: r.name == template_name)[:1]
    else:
        template = candidates.sorted(lambda r: -len(r.rule_ids))[:1]

    to_create = []
    if not template:
        print(f"  no ruleset matching {SCOPE!r} exists yet, so there is nothing "
              f"to copy from")
    else:
        print(f"  template: {template.name} "
              f"({template.company_id.name or 'all companies'}) - "
              f"{len(template.rule_ids)} rule(s)")
        covered = {r.company_id.id for r in candidates if r.company_id}
        for company in Company.search([]):
            if Version is None or not Version.search_count(
                    [('company_id', '=', company.id)]):
                continue
            if company.id in covered:
                print(f"  {company.name[:44]:<44} has one already")
                continue
            name = (os.environ.get('SSC_NAME') or '{company} Overtime').format(
                company=company.name)
            to_create.append((company, name))
            print(f"  {company.name[:44]:<44} CREATE {name!r} "
                  f"+ {len(template.rule_ids)} rule(s)")
        if not to_create:
            print("  every company with contracts already has one")

    # --- 4. what is configured today -----------------------------------------

    title("4. rulesets and their rules")

    Ruleset = env['hr.attendance.overtime.ruleset'].sudo()
    Version = env['hr.version'].sudo() if 'hr.version' in env else None
    Type = env['hr.work.entry.type'].sudo() if 'hr.work.entry.type' in env else None

    # The rate a rule SHOULD carry is the rate of the type it will point at -
    # which, for a type that already exists and is not being forced, is the rate
    # somebody already chose, not this run's default. Reporting the default
    # would tell the reader their 200% is wrong when it is exactly what they set.
    resolved = {}
    effective = {}
    for kind, spec in WANTED_TYPES.items():
        found = (Type.search([('code', '=', spec['code'])], limit=1)
                 if Type is not None else None)
        resolved[kind] = found
        keeps = found and not FORCE_RATE and 'amount_rate' in found._fields
        effective[kind] = found.amount_rate if keeps else spec['rate']

    planned = []
    skipped = []
    for ruleset in Ruleset.search([], order='company_id, id'):
        in_scope = SCOPE.lower() in (ruleset.name or '').lower()
        if not in_scope:
            skipped.append(ruleset)
            continue
        # `Version` is an empty recordset, and an empty recordset is falsy - so
        # `if Version and ...` reported every ruleset as used by nobody, however
        # many contracts pointed at it. Compared to None, never to itself.
        used_by = (Version.search_count([('ruleset_id', '=', ruleset.id)])
                   if Version is not None and 'ruleset_id' in Version._fields
                   else 0)
        print(f"\n  [{ruleset.id}] {ruleset.name}")
        print(f"      company={ruleset.company_id.name or '(all)'}  "
              f"mode={ruleset.rate_combination_mode}  "
              f"used by {used_by} version(s)")
        if not ruleset.rule_ids:
            print("      (no rules)")
        for rule in ruleset.rule_ids:
            work_entry = rule.work_entry_type_id if 'work_entry_type_id' \
                in rule._fields else None
            print(f"      - {rule.name[:38]:<38} based_off={rule.base_off:<9} "
                  f"paid={rule.paid}  rate={rule.amount_rate:g} "
                  f"({rule.amount_rate * 100:g}%)")
            if rule.base_off == 'timing':
                print(f"        timing={rule.timing_type} "
                      f"{rule.timing_start:g}-{rule.timing_stop:g}")
            else:
                print(f"        period={rule.quantity_period} "
                      f"from_contract={rule.expected_hours_from_contract} "
                      f"expected={rule.expected_hours:g}")
            print(f"        tolerance employer={rule.employer_tolerance:g} "
                  f"employee={rule.employee_tolerance:g}"
                  + (f"  work entry={work_entry.name}" if work_entry else ""))

            if not rule.paid:
                continue
            kind = 'off' if 'off' in (rule.name or '').lower() else 'reg'
            wanted = effective[kind]
            if abs(rule.amount_rate - wanted) > 0.0001:
                planned.append((rule, kind, wanted))
                print(f"        -> rate {rule.amount_rate:g} should be {wanted:g} "
                      f"({wanted * 100:g}%)")

    if skipped:
        print(f"\n  SKIPPED - name does not contain {SCOPE!r}, so left alone:")
        for ruleset in skipped:
            print(f"    [{ruleset.id}] {ruleset.name[:40]:<40} "
                  f"{len(ruleset.rule_ids)} rule(s)  "
                  f"company={ruleset.company_id.name or '(all)'}")

    # --- 5. where the rate actually comes from -------------------------------

    title("5. what carries the rate")

    rate_is_computed = bool(getattr(field, 'compute', None)) if field else False
    if rate_is_computed:
        print("  amount_rate on the rule is COMPUTED from the work entry type:")
        print("      rule.amount_rate = rule.work_entry_type_id.amount_rate")
        print("  so the rate is set by giving each rule its own type. Writing the")
        print("  number onto the rule would be undone by the next recompute.")
    else:
        print("  amount_rate on the rule is a plain stored field on this database")
        print("  (Payroll absent), so the rate is written straight onto the rule.")

    if Type is not None:
        print("\n  types this run needs:")
        for kind, spec in WANTED_TYPES.items():
            found = resolved[kind]
            if found:
                current = found.amount_rate if 'amount_rate' in found._fields else None
                differs = (current is not None
                           and abs(current - spec['rate']) > 0.0001)
                if not differs:
                    mark = ''
                elif FORCE_RATE:
                    mark = f"  -> FORCED to {spec['rate']:g}"
                else:
                    # A rate already chosen deliberately is not overwritten by a
                    # default. Losing 130% to a re-run that forgot the variable
                    # is how people get paid the wrong amount.
                    mark = (f"  KEPT (this run wanted {spec['rate']:g}; "
                            f"pass SSC_FORCE_RATE=1 to change it)")
                print(f"    {spec['code']:<14} EXISTS  rate="
                      f"{current if current is None else f'{current:g}'}{mark}")
            else:
                print(f"    {spec['code']:<14} MISSING -> would create "
                      f"{spec['name']!r} at {spec['rate'] * 100:g}%")

        print("\n  types the rules point at today:")
        shown = set()
        for ruleset in Ruleset.search([]):
            for rule in ruleset.rule_ids:
                work_entry = (rule.work_entry_type_id
                              if 'work_entry_type_id' in rule._fields else None)
                if work_entry and work_entry.id not in shown:
                    shown.add(work_entry.id)
                    rate = (work_entry.amount_rate
                            if 'amount_rate' in work_entry._fields else None)
                    shared = (' <- SHARED, do not re-rate'
                              if work_entry.code == 'OVERTIME' else '')
                    print(f"    {work_entry.code or '-':<14} "
                          f"{work_entry.name[:32]:<32} "
                          f"rate={rate if rate is None else f'{rate:g}'}{shared}")
        if not shown:
            print("    none")

        # The rule's rate is declared @api.depends('work_entry_type_id') - on
        # WHICH type, not on that type's rate. So re-rating a type leaves every
        # rule pointing at it holding the old number, and the old number is what
        # gets paid. Nothing warns about it, so this does.
        stale = []
        for ruleset in Ruleset.search([]):
            for rule in ruleset.rule_ids:
                work_entry = (rule.work_entry_type_id
                              if 'work_entry_type_id' in rule._fields else None)
                if not work_entry or 'amount_rate' not in work_entry._fields:
                    continue
                # An unpaid rule only flags the hours as extra; its rate is never
                # read, so a rate that disagrees with its type is not a problem
                # and saying so would bury the ones that are.
                if not rule.paid:
                    continue
                if abs(rule.amount_rate - work_entry.amount_rate) > 0.0001:
                    stale.append((rule, work_entry))
        if stale:
            print("\n  !! STALE: these rules hold a rate their type no longer says")
            for rule, work_entry in stale:
                print(f"    {rule.ruleset_id.name[:22]:<22} {rule.name[:26]:<26} "
                      f"rule={rule.amount_rate:g}  type={work_entry.amount_rate:g}")
            print("    The rule's number is the one that gets paid. Applying resyncs it.")

    # --- apply ---------------------------------------------------------------

    title("summary")

    # The summary has to name everything the run would do. Reporting only the
    # rate changes let three whole rulesets be created under a line that read
    # "already carries the rate it should".
    for company, name in to_create:
        print(f"  . create {name!r} for {company.name} "
              f"with {len(template.rule_ids)} rule(s)")

    if not planned:
        print("  every paid rule already carries the rate it should")
    else:
        for rule, kind, wanted in planned:
            how = (f"point at {WANTED_TYPES[kind]['code']}" if rate_is_computed
                   else f"set rate to {wanted:g}")
            print(f"  . {rule.ruleset_id.name} / {rule.name}: "
                  f"{rule.amount_rate:g} -> {wanted:g}   ({how})")

    if not APPLY:
        env.cr.rollback()
        print("\nreport only - nothing written. Re-run with SSC_APPLY=1 to write.")
    else:
        written = []

        # Created first, and copied from a working ruleset, so the new rules
        # arrive pointing at the same work entry types - which means they carry
        # the right rate immediately, with no second pass.
        for company, name in to_create:
            new_ruleset = Ruleset.create({
                'name': name,
                'company_id': company.id,
                'rate_combination_mode': template.rate_combination_mode,
                'country_id': template.country_id.id if template.country_id
                else False,
            })
            for source in template.rule_ids:
                vals = {'ruleset_id': new_ruleset.id}
                for field_name in COPY_FIELDS:
                    if field_name not in source._fields:
                        continue
                    value = source[field_name]
                    vals[field_name] = value.id if hasattr(value, '_name') else value
                env[MODEL].sudo().create(vals)
            written.append(f"created {name!r} with {len(template.rule_ids)} rule(s)")

        if rate_is_computed:
            if Type is None:
                print("\nhr.work.entry.type is missing - the rate cannot be set here.")
            else:
                for kind, spec in WANTED_TYPES.items():
                    work_entry = resolved.get(kind)
                    if not work_entry:
                        vals = {'name': spec['name'], 'code': spec['code']}
                        if 'amount_rate' in Type._fields:
                            vals['amount_rate'] = spec['rate']
                        if 'is_leave' in Type._fields:
                            vals['is_leave'] = False
                        work_entry = Type.create(vals)
                        resolved[kind] = work_entry
                        written.append(f"created {spec['code']} at "
                                       f"{spec['rate'] * 100:g}%")
                    elif ('amount_rate' in work_entry._fields
                          and abs(work_entry.amount_rate - spec['rate']) > 0.0001):
                        if FORCE_RATE:
                            work_entry.amount_rate = spec['rate']
                            written.append(f"re-rated {spec['code']} to "
                                           f"{spec['rate'] * 100:g}%")
                        else:
                            written.append(
                                f"kept {spec['code']} at "
                                f"{work_entry.amount_rate * 100:g}% "
                                f"(SSC_FORCE_RATE=1 would make it "
                                f"{spec['rate'] * 100:g}%)")
                for rule, kind, _wanted in planned:
                    work_entry = resolved.get(kind)
                    if work_entry and rule.work_entry_type_id != work_entry:
                        rule.work_entry_type_id = work_entry.id
                        written.append(f"{rule.name} -> {work_entry.code}")

                # Odoo recomputes the rule's rate only when the type it points at
                # CHANGES, never when that type is re-rated, so the rules are
                # brought back in line by hand. The rule's number is what the
                # overtime line copies, and the overtime line is what gets paid.
                for kind, spec in WANTED_TYPES.items():
                    work_entry = resolved.get(kind)
                    if not work_entry or 'amount_rate' not in work_entry._fields:
                        continue
                    behind = Rule.search([
                        ('work_entry_type_id', '=', work_entry.id)
                    ]).filtered(
                        lambda r, w=work_entry:
                        abs(r.amount_rate - w.amount_rate) > 0.0001)
                    if behind:
                        behind.write({'amount_rate': work_entry.amount_rate})
                        written.append(
                            f"resynced {len(behind)} rule(s) to {spec['code']} "
                            f"at {work_entry.amount_rate * 100:g}%")
        else:
            for rule, _kind, wanted in planned:
                rule.amount_rate = wanted
                written.append(f"{rule.name} rate -> {wanted:g}")

        env.cr.commit()
        print("\nwritten:")
        for line in written or ['(nothing)']:
            print(f"  . {line}")
        print("\nOvertime already computed keeps its old rate - press Regenerate")
        print("overtimes on each ruleset, or the old lines stay as they were.")
