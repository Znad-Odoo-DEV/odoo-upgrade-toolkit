"""Print a comparable inventory of the database, so an upgrade can be checked.

    # on production, still on 18, before anything:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/upgrade_snapshot.py > before.txt

    # on the upgraded staging, on 19:
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/upgrade_snapshot.py > after.txt

    diff before.txt after.txt

Every line is ``key<TAB>value`` and the whole thing is sorted, so the diff is
the answer: a line that changed is data the upgrade moved, and a line that
disappeared is data it lost.

Models Odoo renamed between the two series are counted under ONE key - the 18.0
name, whichever series is running - so hr.contract and hr.version line up
instead of reading as a loss and a gain. Same for the fields that moved.

Reads only. It opens no transaction it does not roll back.
"""

# Renamed in 19.0. Key is the name used in the output, values are the names to
# look for; the first one that exists on this database is the one counted.
ALIASES = {
    'hr.contract': ('hr.contract', 'hr.version'),
}

# The models worth watching by name. Everything ssc.* and every Studio x_ model
# with rows is added automatically below.
CORE = [
    'res.company', 'res.users', 'res.groups', 'res.partner',
    'hr.employee', 'hr.department', 'hr.job', 'hr.contract',
    'hr.attendance', 'hr.attendance.overtime', 'hr.leave', 'hr.leave.allocation',
    'hr.payslip', 'hr.payslip.line', 'hr.payslip.run', 'hr.payslip.worked_days',
    'hr.salary.rule', 'hr.payroll.structure', 'hr.work.entry', 'hr.work.entry.type',
    'resource.calendar', 'resource.calendar.attendance',
    'project.project', 'project.task', 'project.project.stage',
    'account.analytic.account', 'account.analytic.plan', 'account.analytic.line',
    'account.move', 'account.move.line', 'account.journal', 'account.account',
    'ir.attachment', 'ir.cron', 'ir.rule', 'ir.ui.view', 'ir.model', 'ir.model.fields',
    'mail.message', 'mail.activity',
]

# Sums that would expose a silent conversion: a count can stay the same while
# every amount is wrong. (model, field) - the column is read straight off the
# table, because read_group changed signature between the two series.
SUMS = [
    ('hr.payslip.line', 'total'),
    ('hr.payslip.worked_days', 'number_of_days'),
    ('hr.payslip.worked_days', 'number_of_hours'),
    ('hr.attendance', 'worked_hours'),
    ('hr.attendance', 'overtime_hours'),
    ('account.analytic.line', 'unit_amount'),
    ('account.analytic.line', 'amount'),
    ('account.move.line', 'balance'),
    ('hr.contract', 'wage'),
]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
cr = env.cr

lines = {}


def resolve(name):
    """The name this database actually carries for a model, or None."""
    for candidate in ALIASES.get(name, (name,)):
        if candidate in env:
            return candidate
    return None


def table_of(model_name):
    model = env[model_name]
    return getattr(model, '_table', model_name.replace('.', '_'))


def has_column(table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return bool(cr.fetchone())


def count(table):
    cr.execute(f'SELECT count(*) FROM "{table}"')
    return cr.fetchone()[0]


# --- models -----------------------------------------------------------------
watched = list(CORE)
for model_name in env.registry:
    if model_name.startswith('ssc.') or model_name.startswith('x_'):
        watched.append(model_name)

for name in sorted(set(watched)):
    actual = resolve(name)
    if not actual:
        lines[f'model {name}'] = 'ABSENT'
        continue
    table = table_of(actual)
    if not has_column(table, 'id'):
        lines[f'model {name}'] = 'NO TABLE'
        continue
    rows = count(table)
    # A Studio model with no rows is noise; a watched one is not.
    if rows or name in CORE or name.startswith('ssc.'):
        lines[f'model {name}'] = rows

# --- sums -------------------------------------------------------------------
for name, column in SUMS:
    actual = resolve(name)
    if not actual:
        lines[f'sum  {name}.{column}'] = 'ABSENT'
        continue
    table = table_of(actual)
    if not has_column(table, column):
        lines[f'sum  {name}.{column}'] = 'NO COLUMN'
        continue
    cr.execute(f'SELECT round(COALESCE(sum("{column}"), 0)::numeric, 2) FROM "{table}"')
    lines[f'sum  {name}.{column}'] = cr.fetchone()[0]

# --- the customisation surface ----------------------------------------------
cr.execute("SELECT count(*) FROM ir_model_fields WHERE state = 'manual'")
lines['custom manual fields'] = cr.fetchone()[0]
cr.execute("SELECT count(*) FROM ir_model WHERE state = 'manual'")
lines['custom manual models'] = cr.fetchone()[0]
cr.execute("""
    SELECT count(*) FROM ir_ui_view
    WHERE id NOT IN (SELECT res_id FROM ir_model_data WHERE model = 'ir.ui.view')
""")
lines['custom manual views'] = cr.fetchone()[0]
cr.execute("""
    SELECT count(*) FROM ir_rule
    WHERE id NOT IN (SELECT res_id FROM ir_model_data WHERE model = 'ir.rule')
""")
lines['custom manual rules'] = cr.fetchone()[0]

# Our own modules, by version, so a half-applied upgrade shows up.
cr.execute("""
    SELECT name, state, latest_version FROM ir_module_module
    WHERE name LIKE 'ssc%%' ORDER BY name
""")
for name, state, version in cr.fetchall():
    lines[f'module {name}'] = f'{state} {version}'

cr.execute("""
    SELECT count(*) FROM ir_module_module
    WHERE state NOT IN ('installed', 'uninstalled', 'uninstallable')
""")
lines['module states unclean'] = cr.fetchone()[0]

# --- access, per user, because a group rename silently drops rights ----------
Users = env['res.users'].with_context(active_test=True)
members = 'all_group_ids' if 'all_group_ids' in Users._fields else 'groups_id'
for user in Users.search([('share', '=', False)], order='login'):
    lines[f'user {user.login}'] = len(user[members])

# --- our timesheet output ----------------------------------------------------
cr.execute("""
    SELECT count(*), round(COALESCE(sum(unit_amount), 0)::numeric, 1),
           round(COALESCE(sum(amount), 0)::numeric, 2)
    FROM account_analytic_line WHERE name LIKE '[BIO]%%'
""")
bio_count, bio_hours, bio_amount = cr.fetchone()
lines['bio timesheet lines'] = bio_count
lines['bio timesheet hours'] = bio_hours
lines['bio timesheet amount'] = bio_amount

for key in sorted(lines):
    print(f'{key}\t{lines[key]}')

cr.rollback()
