"""Which salary rules were overwritten that should not have been, and who uses them.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http 2>/dev/null < tools/check_overwritten_stock_rules.py

apply_salary_rules_everywhere.py matched on rule CODE and wrote the repo's body
into every rule carrying it. BASIC and NET are the most generic codes in Odoo
payroll - every structure has one, including the ones this company did not
build - so the SSC bodies went into Odoo's own structures as well as ours.

This says exactly which, and whether it matters: a rule nobody is paid through
is a mess to tidy, a rule somebody is paid through is a wrong payslip.

Read-only. It writes nothing and fixes nothing - the fix is a module upgrade,
and that is a decision to take with the damage in front of you.

WHAT IT SHOWS

  * every rule whose Python now matches a repo file, grouped by structure;
  * which of those structures the company built and which came from a module,
    read from ir_model_data rather than from the name;
  * how many contract versions and payslips sit on each structure, because that
    is what turns a tidy-up into a correction.
"""
import os
import sys

WIDTH = 96
RULES_DIR = os.path.abspath(os.environ.get('SSC_RULES_DIR') or 'payroll_rules')

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821

sys.path.insert(0, RULES_DIR)
try:
    import rule_files
except Exception as error:  # noqa: BLE001
    rule_files = None
    IMPORT_ERROR = str(error)


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def owner_module(record):
    """The module that created a record, or None when a person did."""
    data = env['ir.model.data'].sudo().search([
        ('model', '=', record._name), ('res_id', '=', record.id)], limit=1)
    return data.module if data else None


title("what the repo defines")
if rule_files is None:
    print(f"  !! cannot import rule_files: {IMPORT_ERROR}")
    repo = {}
else:
    repo, problem = rule_files.read(RULES_DIR)
    if problem:
        print(f"  !! {problem}")
        repo = {}
bodies = {code: rule_files.executable(rule_files.body_of(entry))
          for code, entry in repo.items()} if repo else {}
print("  " + (", ".join(sorted(bodies)) or "(nothing)"))


title("rules whose Python is now the repo's")

Rule = env['hr.salary.rule'].sudo() if 'hr.salary.rule' in env else None
carrying = {}
if bodies and Rule is not None:
    for rule in Rule.search([('code', 'in', list(bodies))]):
        if rule_files.executable(rule.amount_python_compute) == bodies[rule.code]:
            carrying.setdefault(rule.struct_id, []).append(rule)

Version = env['hr.version'].sudo() if 'hr.version' in env else None
Payslip = env['hr.payslip'].sudo() if 'hr.payslip' in env else None

ours, theirs = [], []
for structure, rules in carrying.items():
    module = owner_module(structure)
    versions = Version.search_count(
        [('structure_type_id', '=', structure.type_id.id)]) if Version else 0
    slips = Payslip.search_count([('struct_id', '=', structure.id)]) if Payslip else 0
    row = (structure, sorted(r.code for r in rules), module, versions, slips)
    (theirs if module else ours).append(row)

for label, rows in (("built by this company - correct to carry them", ours),
                    ("created by a module - SHOULD NOT carry them", theirs)):
    title(label, '-')
    if not rows:
        print("  (none)")
        continue
    print("  %-52s %-22s %9s %9s" % ("structure", "rules", "versions", "payslips"))
    for structure, codes, module, versions, slips in sorted(
            rows, key=lambda r: (-r[4], -r[3], r[0].name or '')):
        flag = ''
        if slips:
            flag = '  <-- payslips exist on this structure'
        elif versions:
            flag = '  <-- employees are on this structure type'
        print("  %-52s %-22s %9s %9s%s"
              % ((structure.name or '?')[:52], ", ".join(codes), versions,
                 slips, flag))
        if module:
            print("      created by module %s" % module)


title("how to put the module ones back")
print("""  A rule that a module created can be restored by upgrading that module:
  its data file is reloaded and the field written back as it shipped.

      odoo-bin -d <database> -u hr_payroll,l10n_ae_hr_payroll --stop-after-init

  Do it only for the structures listed above as created by a module, and read
  the payslip and version counts first. A structure nobody is paid through can
  wait; one with payslips on it needs those payslips recomputed afterwards.

  Read-only run. Nothing was changed.""")
