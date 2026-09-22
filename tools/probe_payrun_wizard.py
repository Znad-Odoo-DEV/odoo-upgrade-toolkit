"""Read Odoo's own Select Employees filter, instead of guessing at it.

    cd ~/src/user
    SSC_COMPANIES="ROYAL ARROW" odoo-bin shell -d <database> --no-http \
        2>/dev/null < tools/probe_payrun_wizard.py

probe_payrun_eligibility.py says sixty Royal Arrow employees should be offered
and the dialog offers two. So the dialog filters on something that probe does
not model, and hr_payroll is Enterprise - its source is on the server and
nowhere else. This reads it from the registry rather than reasoning about it.

  * the pay runs that exist for the period, with the structure each one is tied
    to. A run created against the wrong structure offers the wrong people, and
    that alone would explain two out of sixty;
  * every model in the registry that could be the wizard - Odoo 19 rebuilt
    this flow and the old names are gone, so the registry is asked rather than
    guessed at;
  * every method on hr.payslip.run that mentions employees or generation, with
    its source printed whole - that is where the filter lives;
  * and the run's own fields, in case Odoo 19 keeps the employee list there
    instead of in a wizard at all.

Read-only. Nothing is created and the transaction is rolled back.
"""
import inspect
import os

WIDTH = 116
FROM = os.environ.get('SSC_FROM') or '2026-08-01'
TO = os.environ.get('SSC_TO') or '2026-08-25'
ONLY = [n.strip().upper() for n in
        (os.environ.get('SSC_COMPANIES') or '').split(',') if n.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821


def title(text, char='='):
    print("\n" + char * WIDTH)
    print(text)
    print(char * WIDTH)


def show_source(obj, name, limit=60):
    try:
        lines = inspect.getsource(obj).splitlines()
    except Exception as error:  # noqa: BLE001
        print("    (%s: source not available - %s)" % (name, error))
        return
    for line in lines[:limit]:
        print("    " + line)
    if len(lines) > limit:
        print("    ... %s more line(s)" % (len(lines) - limit))


# ------------------------------------------------------------------- pay runs
title("1. the pay runs for %s .. %s, and what each is tied to" % (FROM, TO))

Run = env.get('hr.payslip.run')
runs = Run.sudo().search([('date_start', '<=', TO), ('date_end', '>=', FROM)]) \
    if Run is not None else []
if not runs:
    print("  no pay run in the period")
for run in runs:
    company = run.company_id
    if ONLY and not any(p in (company.name or '').upper() for p in ONLY):
        continue
    bits = []
    for field in ('struct_id', 'structure_type_id', 'state', 'slip_ids'):
        if field not in run._fields:
            continue
        value = run[field]
        if field == 'slip_ids':
            bits.append("payslips=%s" % len(value))
        elif hasattr(value, 'name'):
            bits.append("%s=%s" % (field, value.name or '-'))
        else:
            bits.append("%s=%s" % (field, value))
    print("  [%s] %s" % (run.id, run.name or '?'))
    print("       company=%s   %s" % (company.name or '-', "   ".join(bits)))

# ------------------------------------------------- where the button actually goes
title("2. actions whose name or model mentions a payslip or a pay run")
print("""  Odoo 19 has no Generate Payslips wizard - hr.payslip.run carries no
  employee list and no generation method. The Select Employees dialog comes
  from the Pay Run button above the payslip list, so it is an action, and an
  action's DOMAIN is the filter. That is what to read.
""")

Action = env['ir.actions.act_window'].sudo()
for action in Action.search([]):
    text = "%s %s" % (action.name or '', action.res_model or '')
    if not any(word in text.lower()
               for word in ('payslip', 'pay run', 'payrun', 'payroll')):
        continue
    print("  [%s] %s" % (action.id, action.name or '?'))
    print("       model=%s  view=%s" % (action.res_model or '-',
                                        action.view_mode or '-'))
    if action.domain:
        print("       DOMAIN  %s" % action.domain)
    if action.context:
        print("       context %s" % action.context)

title("3. methods on hr.payslip that could open it", '-')
Slip = env['hr.payslip'].sudo()
for name in sorted(n for n in dir(Slip)
                   if n.startswith(('action_', '_get_', '_compute_'))
                   and any(w in n for w in ('run', 'batch', 'employee',
                                            'generate', 'wizard', 'cycle'))):
    member = getattr(type(Slip), name, None)
    if not callable(member):
        continue
    print("")
    print("  hr.payslip.%s" % name)
    show_source(member, name, limit=45)

title("4. server actions and buttons on the payslip list", '-')
Server = env.get('ir.actions.server')
if Server is not None:
    for action in Server.sudo().search([]):
        text = "%s %s" % (action.name or '', action.model_id.model or '')
        if not any(word in text.lower()
                   for word in ('payslip', 'pay run', 'payrun')):
            continue
        print("  [%s] %s   model=%s   state=%s"
              % (action.id, action.name or '?',
                 action.model_id.model or '-', action.state))
        if action.state == 'code' and action.code:
            for line in (action.code or '').strip().splitlines()[:20]:
                print("       " + line)

env.cr.rollback()
title("read only - the transaction was rolled back")
