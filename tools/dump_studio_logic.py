"""Everything a Studio model does: its automations and its server actions, in full.

    SSC_MODELS=x_advance_salaries,x_staff_loan \
        odoo-bin shell --no-http --shell-interface=python < tools/dump_studio_logic.py

Reads only. Writes nothing.

Before a Studio model is deleted, the behaviour attached to it has to be read -
not summarised. An automation is a trigger, a filter and a list of server
actions, and a server action is a piece of Python with the whole rule inside it.
The name never says what it does: half of them are called Execute Code.

So this prints all of it, verbatim, for the models named. What it is for is the
comparison: read it beside ssc_payroll and decide, rule by rule, whether the
native module already does it, does it differently, or does not do it at all.

Also printed: server actions belonging to other models whose code names one of
these, because that is where the cross-model rules live and they will break the
moment the model is gone.
"""
import os
import re

MODELS = [m.strip() for m in (os.environ.get('SSC_MODELS') or '').split(',') if m.strip()]

cr = env.cr                                                      # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
Server = env['ir.actions.server'].sudo()                         # noqa: F821
Automation = env.get('base.automation')                          # noqa: F821

if not MODELS:
    raise SystemExit("Set SSC_MODELS=x_advance_salaries,x_staff_loan,...")


def title(text, rule='='):
    print("\n" + rule * 96)
    print(text)
    print(rule * 96)


def get(record, name, default=''):
    return record[name] if name in record._fields else default


def block(text, indent='      '):
    if not text:
        return
    for line in str(text).rstrip().splitlines():
        print(indent + line)


def describe_action(action, indent='    '):
    print("%s--- action %s  %s" % (indent, action.id, action.name or ''))
    owner = get(action, 'model_id')
    print("%s    on model    %s" % (indent, owner.model if owner else '-'))
    print("%s    kind        %s" % (indent, get(action, 'state')))
    for name, label in (('crud_model_id', 'creates'),
                        ('link_field_id', 'links through'),
                        ('update_path', 'updates'),
                        ('update_field_id', 'updates field'),
                        ('value', 'value'),
                        ('evaluation_type', 'value is'),
                        ('selection_value', 'selection'),
                        ('resource_ref', 'record'),
                        ('webhook_url', 'posts to'),
                        ('activity_summary', 'activity'),
                        ('groups_id', 'groups')):
        value = get(action, name)
        if not value:
            continue
        try:
            value = value.display_name if hasattr(value, 'display_name') else value
        except Exception:
            value = str(value)
        print("%s    %-11s %s" % (indent, label, str(value)[:80]))
    code = get(action, 'code')
    if code:
        print("%s    code:" % indent)
        block(code, indent + '        ')
    children = get(action, 'child_ids')
    if children:
        print("%s    then:" % indent)
        for child in children:
            describe_action(child, indent + '    ')


for model_name in MODELS:
    record = IrModel.search([('model', '=', model_name)], limit=1)
    title("%s   %s" % (model_name,
                       (record.name or '') if record else 'NOT A MODEL HERE'))
    if not record:
        continue

    Model = env.get(model_name)                                  # noqa: F821
    rows = 0
    if Model is not None:
        cr.execute("SELECT to_regclass(%s)", (Model._table,))
        if cr.fetchone()[0]:
            cr.execute('SELECT COUNT(*) FROM "%s"' % Model._table)
            rows = cr.fetchone()[0]
    print("  %s row(s)" % rows)

    rules = Automation.sudo().search([('model_id', '=', record.id)]) if Automation else []
    title("  %s automation(s)" % len(rules), '-')
    called = Server.browse([])
    for rule in rules:
        print("\n  RULE %s  %s   [%s]"
              % (rule.id, rule.name or '', 'on' if rule.active else 'off'))
        for name, label in (('trigger', 'trigger'),
                            ('trigger_field_ids', 'when these change'),
                            ('filter_pre_domain', 'before'),
                            ('filter_domain', 'only when'),
                            ('trg_date_id', 'date field'),
                            ('trg_date_range', 'delay'),
                            ('trg_date_range_type', 'delay unit'),
                            ('on_change_field_ids', 'on change of')):
            value = get(rule, name)
            if not value:
                continue
            try:
                value = ', '.join(value.mapped('name')) if hasattr(value, 'mapped') \
                    else value
            except Exception:
                value = str(value)
            print("      %-18s %s" % (label, str(value)[:100]))
        actions = get(rule, 'action_server_ids') or Server.browse([])
        called |= actions
        for action in actions:
            describe_action(action)

    own = Server.search([('model_id', '=', record.id)])
    standalone = own - called
    title("  %s server action(s) on it, %s not called by an automation"
          % (len(own), len(standalone)), '-')
    for action in standalone:
        describe_action(action)

    # cross-model rules: somebody else's code that names this model
    pattern = re.compile(r"(?<![\w.])%s(?![\w])" % re.escape(model_name))
    elsewhere = [a for a in Server.search([])
                 if a.model_id != record and pattern.search(a.code or '')]
    title("  %s action(s) on OTHER models whose code names it" % len(elsewhere), '-')
    for action in elsewhere:
        describe_action(action)


title("what to do with this")
print("""  Read each rule beside ssc_payroll and put it in one of three piles: the
  native module already does it, it does it differently, or nothing does it.

  The third pile is the only one that matters, and it is the reason this is
  printed in full rather than counted. A rule nobody notices is a rule that
  stops happening on the day the model goes, silently, and is found a month
  later by somebody wondering why a deduction never appeared.""")
