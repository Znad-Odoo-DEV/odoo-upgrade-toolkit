"""Print every salary rule of every payroll structure, code included, so the
payslip stops being a black box.

    # everything on the database:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/dump_salary_rules.py > rules.txt

    # only the structures whose name matches, case-insensitive:
    SSC_STRUCTURE="United Arab Emirates" odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/dump_salary_rules.py > rules.txt

Answers the question a functional read cannot: which rule produces BASIC, what
it reads it from, and what the localization silently adds on top. For each rule
it prints the condition, the amount, and - when the amount is Python - the code
verbatim, indented, so it can be read as code rather than as a form field.

Also prints, because a rule is unreadable without them:

  * the rule parameters (``hr.rule.parameter``) with the value in force per
    date - the UAE constants live there, not in the rule text;
  * the wage and allowance fields the localization added to the contract, taken
    from the registry, so the names used inside the rules resolve to something;
  * one worked example per structure: an employee sitting on it, with the wage
    and allowances actually stored on their running contract.

19.0 dissolved hr.contract into hr.version; both names are handled, so the same
script reads production before and after the jump.

Reads only. It rolls its transaction back before it exits.
"""
import os

# Case-insensitive substring; empty means every structure.
ONLY = (os.environ.get('SSC_STRUCTURE') or '').strip().lower()

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

RULE_WIDTH = 78


def title(text, char='='):
    print("\n" + char * RULE_WIDTH)
    print(text)
    print(char * RULE_WIDTH)


def get(record, field, default=''):
    """Read a field only if this series actually carries it."""
    if field not in record._fields:
        return default
    value = record[field]
    return default if value is False or value is None else value


def block(text, indent='            '):
    """Print a code blob so it still reads as code."""
    for line in str(text).rstrip().splitlines():
        print(indent + line)


if 'hr.salary.rule' not in env:
    print("hr_payroll is not installed on this database - nothing to dump.")
else:
    Structure = env['hr.payroll.structure'].sudo()
    Rule = env['hr.salary.rule'].sudo()

    # --- the contract fields the rules will be reading ------------------------

    title("0. wage and allowance fields on the contract")

    contract_model = 'hr.version' if 'hr.version' in env else 'hr.contract'
    print(f"  contract model: {contract_model}")

    Fields = env['ir.model.fields'].sudo()
    money = Fields.search([
        ('model', '=', contract_model),
        '|', '|', '|',
        ('name', 'like', 'wage'),
        ('name', 'like', 'allowance'),
        ('name', 'like', 'salary'),
        ('name', 'like', 'l10n_ae'),
    ], order='name')
    for field in money:
        stored = 'stored' if field.store else 'computed'
        print(f"  {field.name:<44} {field.ttype:<10} {stored:<9} {field.field_description}")
    if not money:
        print("  (none - the localization adds no wage field of its own)")

    # --- the structures -------------------------------------------------------

    structures = Structure.search([], order='country_id, name')
    if ONLY:
        structures = structures.filtered(lambda s: ONLY in (s.name or '').lower())

    title(f"1. structures ({len(structures)})")
    for structure in structures:
        country = get(structure, 'country_id')
        print(f"  [{structure.id:>4}] {structure.name}"
              f"{'  /  ' + country.name if country else ''}")

    for structure in structures:
        rules = Rule.search([('struct_id', '=', structure.id)], order='sequence, id')
        title(f"{structure.name}   -   {len(rules)} rule(s)")

        type_id = get(structure, 'type_id')
        print(f"  structure type   {type_id.name if type_id else '-'}")
        print(f"  schedule pay     {get(structure, 'schedule_pay', '-')}")
        unpaid = get(structure, 'unpaid_work_entry_type_ids')
        if unpaid:
            print(f"  unpaid entries   {', '.join(unpaid.mapped('name'))}")

        for rule in rules:
            category = get(rule, 'category_id')
            print("\n  " + "-" * (RULE_WIDTH - 2))
            print(f"  {get(rule, 'sequence', 0):>4}  {rule.code:<16} {rule.name}")
            print(f"        category   {category.code if category else '-'}"
                  f" ({category.name if category else '-'})")
            print(f"        on payslip {'yes' if get(rule, 'appears_on_payslip') else 'NO'}"
                  f"   active {'yes' if rule.active else 'NO'}")

            condition = get(rule, 'condition_select', 'none')
            if condition == 'none':
                print("        applies    always")
            elif condition == 'range':
                low = get(rule, 'condition_range_min', 0)
                high = get(rule, 'condition_range_max', 0)
                print(f"        applies    when {get(rule, 'condition_range', '?')}"
                      f" between {low} and {high}")
            elif condition == 'python':
                print("        applies    when (python):")
                block(get(rule, 'condition_python'))
            else:
                print(f"        applies    {condition}")

            amount = get(rule, 'amount_select', '?')
            if amount == 'fix':
                print(f"        amount     fixed {get(rule, 'amount_fix', 0)}"
                      f"  x quantity {get(rule, 'quantity', 1)}")
            elif amount == 'percentage':
                print(f"        amount     {get(rule, 'amount_percentage', 0)}%"
                      f" of {get(rule, 'amount_percentage_base', '?')}"
                      f"  x quantity {get(rule, 'quantity', 1)}")
            elif amount == 'code':
                print("        amount     (python):")
                block(get(rule, 'amount_python_compute'))
            else:
                print(f"        amount     {amount}")

        # --- one real employee on this structure ------------------------------

        Contract = env[contract_model].sudo()
        domain = [('structure_type_id', '=', get(structure, 'type_id').id)] \
            if get(structure, 'type_id') else []
        example = Contract.search(domain + [('employee_id', '!=', False)],
                                  order='id desc', limit=1) if domain else Contract.browse()
        if example:
            print("\n  " + "-" * (RULE_WIDTH - 2))
            print(f"  worked example: {example.employee_id.name}")
            for field in money:
                if field.name in example._fields:
                    print(f"        {field.name:<44} {example[field.name]}")

    # --- the constants the rules read ----------------------------------------

    if 'hr.rule.parameter' in env:
        Parameter = env['hr.rule.parameter'].sudo()
        parameters = Parameter.search([], order='code')
        if ONLY:
            countries = {get(s, 'country_id').id for s in structures if get(s, 'country_id')}
            parameters = parameters.filtered(
                lambda p: not get(p, 'country_id') or get(p, 'country_id').id in countries)

        title(f"2. rule parameters ({len(parameters)})")
        for parameter in parameters:
            country = get(parameter, 'country_id')
            print(f"\n  {parameter.code:<44} {parameter.name}"
                  f"{'  /  ' + country.code if country else ''}")
            versions = get(parameter, 'parameter_version_ids', Parameter.browse())
            for value in versions.sorted(lambda v: str(v.date_from or '')):
                print(f"        from {value.date_from}   {value.parameter_value}")

env.cr.rollback()
print("\nread only - nothing written.")
