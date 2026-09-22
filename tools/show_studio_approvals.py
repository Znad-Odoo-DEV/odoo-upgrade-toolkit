"""Where Studio keeps the approvals, and what it knows about each one.

    SSC_MODEL=x_all_payslips odoo-bin shell --no-http --shell-interface=python < tools/show_studio_approvals.py

Reads only. There is no approved-by field on the Studio payslip and no approval
date: 77 fields and not one of them is an approval. That is because Studio does
not keep approvals on the record. It keeps them in studio.approval.rule and
studio.approval.entry - a rule saying which button on which model needs
approving and by whom, and an entry per record saying who pressed it and when.

Which means the approvals are not carried by copying fields, and would not have
been noticed by looking for them there. They are their own records, pointing at
the payslip by id, and they go when the model goes exactly as the chatter does.

This shows what exists for one model: the rules, how many entries answer to
them, who gave them and over what period. It is the shape the new fields on
ssc.payslip have to fit.
"""
import os

MODEL = os.environ.get('SSC_MODEL') or 'x_all_payslips'

cr = env.cr                                                      # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


record = env['ir.model'].sudo().search([('model', '=', MODEL)], limit=1)  # noqa: F821
if not record:
    raise SystemExit("%s is not a model here." % MODEL)

Rule = env.get('studio.approval.rule')                           # noqa: F821
Entry = env.get('studio.approval.entry')                         # noqa: F821
Request = env.get('studio.approval.request')                     # noqa: F821

if Rule is None:
    raise SystemExit("Studio approvals are not installed in this database.")

Rule = Rule.sudo()
Entry = Entry.sudo() if Entry is not None else None
Request = Request.sudo() if Request is not None else None


title("1. the rules on %s" % MODEL)

rules = Rule.search([('model_id', '=', record.id)])
print("  %s rule(s)" % len(rules))
for rule in rules:
    groups = ', '.join(rule.group_id.mapped('name')) if rule.group_id else 'anybody'
    users = ', '.join(rule.users_to_notify.mapped('name')) if 'users_to_notify' in rule._fields and rule.users_to_notify else '-'
    entries = Entry.search_count([('rule_id', '=', rule.id)]) if Entry else 0
    print("\n  rule %s" % rule.id)
    print("      method/action  %s / %s"
          % (rule.method or '-', rule.action_id.name if rule.action_id else '-'))
    print("      message        %s" % (rule.message or '-')[:60])
    print("      group          %s" % groups)
    print("      exclusive      %s" % rule.exclusive_user)
    print("      notify         %s" % users)
    print("      entries        %s" % entries)


title("2. the entries - who approved what, and when")

if Entry is None:
    print("  studio.approval.entry is not available")
else:
    entries = Entry.search([('model', '=', MODEL)]) if 'model' in Entry._fields \
        else Entry.search([('rule_id', 'in', rules.ids)])
    print("  %s entry(ies) against %s" % (len(entries), MODEL))
    if entries:
        approved = entries.filtered(lambda e: e.approved)
        print("      %s approved, %s rejected"
              % (len(approved), len(entries) - len(approved)))
        dates = sorted(e.write_date for e in entries if e.write_date)
        if dates:
            print("      %s  ->  %s" % (dates[0], dates[-1]))
        by_user = {}
        for entry in entries:
            name = entry.user_id.name if entry.user_id else '-'
            by_user[name] = by_user.get(name, 0) + 1
        print("\n      who gave them:")
        for name, count in sorted(by_user.items(), key=lambda kv: -kv[1]):
            print("        %-36s %s" % (name[:36], count))
        print("\n      a few, in full:")
        for entry in entries[:10]:
            print("        record %-8s rule %-6s %-26s %-9s %s"
                  % (entry.res_id, entry.rule_id.id,
                     (entry.user_id.name or '-')[:26],
                     'approved' if entry.approved else 'rejected',
                     entry.write_date))
        # How many distinct payslips carry one
        records_with = len({e.res_id for e in entries})
        print("\n      %s distinct record(s) carry at least one entry" % records_with)


title("3. requests still open")

if Request is None:
    print("  studio.approval.request is not available")
else:
    requests = Request.search([('rule_id', 'in', rules.ids)]) if rules else Request.browse()
    print("  %s open request(s) on %s" % (len(requests), MODEL))
    for req in requests[:10]:
        print("      record %-8s rule %-6s %s"
              % (req.res_id, req.rule_id.id,
                 ', '.join(req.mail_activity_id.mapped('user_id.name'))
                 if 'mail_activity_id' in req._fields else ''))


title("4. and the chatter, which is the other half of the trail")

Message = env['mail.message'].sudo()                             # noqa: F821
messages = Message.search([('model', '=', MODEL)])
print("  %s message(s) on %s" % (len(messages), MODEL))
kinds = {}
for message in messages:
    kinds[message.message_type] = kinds.get(message.message_type, 0) + 1
for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
    print("      %-20s %s" % (kind, count))

Tracking = env.get('mail.tracking.value')                        # noqa: F821
if Tracking is not None and messages:
    values = Tracking.sudo().search_count([('mail_message_id', 'in', messages.ids)])
    print("  %s tracked field change(s) behind them" % values)
    if messages:
        sample = messages[0]
        tracked = Tracking.sudo().search([('mail_message_id', '=', sample.id)])
        print("\n  what one message tracks (message %s on record %s):"
              % (sample.id, sample.res_id))
        for value in tracked[:8]:
            print("      %-40s" % (value.field_id.field_description
                                   if value.field_id else '-'))


title("what has to move")
print("""  An approval here is a studio.approval.entry: a rule, a user, an approved
  flag and the moment it was written. It points at the payslip by id and by
  model name, so it moves the same way the chatter does - by translating the id
  through studio_ref_id and rewriting the model - or it is read once and copied
  onto fields of our own.

  Copying is the better answer for a record that has to outlive the model it
  describes: an entry pointing at a model that no longer exists is not a record
  of anything.""")
