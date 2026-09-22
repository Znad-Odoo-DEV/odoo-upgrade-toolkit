"""Every email the requests application can send, and every one it cannot.

    odoo-bin shell -d DB < tools/audit_request_emails.py

Run it against production to compare the two sides. Against the local test
database it can only report our half, and it says so rather than printing
"none" for Studio - the first version of this tool searched for templates on
a model that is not in the test database at all, and reported the empty result
as though it had looked.

Studio sends an email by four different routes, each stored somewhere else: a
mail.template on the model, a server action of type mail, an automation rule
whose action does the same, and a follower notification nobody wrote. All four
are read, because a rule pointing at a template that is not in our modules is
an email production sends today and staging would stop sending.

The last section is the one worth reading twice: an address the application
stores, displays, and never writes to. That is not a missing template, it is a
promise on a form.
"""


def title(text):
    print()
    print(text)
    print("-" * len(text))


def show(template, indent="  "):
    print("%s%s" % (indent, template.name or ''))
    print("%s  to      %s" % (indent, template.email_to or template.partner_to
                              or '(the record)'))
    if template.email_cc:
        print("%s  cc      %s" % (indent, template.email_cc))
    print("%s  from    %s" % (indent, template.email_from or '(default)'))
    print("%s  subject %s" % (indent, (template.subject or '')[:70]))


Model = env['ir.model']                                            # noqa: F821
Template = env['mail.template']                                    # noqa: F821
Data = env['ir.model.data']                                        # noqa: F821

studio = Model.search([('model', '=', 'x_all_requests')])
ours = Model.search([('model', '=', 'ssc.request')])

# ---------------------------------------------------------------- ours ------
title("OURS - mail.template on ssc.request")
mine = Template.search([('model_id', '=', ours.id)]) if ours else Template
if not mine:
    print("  none")
for template in mine:
    data = Data.search([('model', '=', 'mail.template'),
                        ('res_id', '=', template.id)], limit=1)
    print()
    print("  [%s]" % (data.complete_name if data
                      else "NOT IN ANY MODULE - lives only on this database"))
    show(template)

# -------------------------------------------------------------- Studio ------
title("STUDIO - x_all_requests")
if not studio:
    print("  THE MODEL IS NOT ON THIS DATABASE.")
    print("  Nothing below this line has been checked. Run this against")
    print("  production to compare the two sides; on the test harness there")
    print("  is no Studio half to read.")
else:
    theirs = Template.search([('model_id', '=', studio.id)])
    print("  %s template(s)" % len(theirs))
    for template in theirs:
        print()
        show(template)

    Server = env['ir.actions.server']                               # noqa: F821
    mailers = Server.search([('model_id', '=', studio.id)]).filtered(
        lambda a: a.state in ('mail_post', 'followers') or a.template_id)
    print()
    print("  server actions that send mail: %s" % len(mailers))
    for action in mailers:
        print("    %-42s state=%-12s template=%s"
              % (action.name[:42], action.state, action.template_id.name or '-'))

    if 'base.automation' in env:                                    # noqa: F821
        rules = env['base.automation'].with_context(                # noqa: F821
            active_test=False).search([('model_id', '=', studio.id)])
        print()
        print("  automation rules: %s" % len(rules))
        for rule in rules:
            sends = rule.action_server_ids.filtered(
                lambda a: a.state in ('mail_post', 'followers') or a.template_id)
            if sends:
                print("    %-38s %-4s trigger=%-20s sends=%s"
                      % (rule.name[:38], "ON" if rule.active else "off",
                         rule.trigger,
                         ", ".join(a.template_id.name or a.state for a in sends)))

# ------------------------------------------------------- what ours sends ----
Request = env['ssc.request']                                        # noqa: F821
Type = env['ssc.request.type']                                      # noqa: F821

title("OURS - which approval sends which")
templates = getattr(Request, 'APPROVAL_TEMPLATES', None)
if templates is None:
    print("  ssc_requests_payroll is not installed - no approval mail at all")
else:
    for key, xmlid in templates.items():
        template = env.ref(xmlid, raise_if_not_found=False)          # noqa: F821
        print("  approval_type=%-14s -> %s"
              % (key, template.name if template else "MISSING  %s" % xmlid))
    advance = env.ref(                                               # noqa: F821
        'ssc_requests_payroll.mail_template_advance_approved',
        raise_if_not_found=False)
    print("  ASR approved     -> %s"
          % (advance.name if advance else "MISSING"))

title("TYPES AND THEIR APPROVAL EMAIL")
# Measured, not deduced. Two earlier versions of this section were wrong in
# two different ways: the first hardcoded the three codes I remembered, and
# the second called _send_approval_email on a bare record and read its False
# as "this type sends nothing" - when the False came from the record having no
# approval_type yet. A guard that fires for a record reason and a guard that
# fires for a type reason return the same value.
#
# So a real request is made for every type, given everything the guards ask
# for, and the mails it produces are counted. The transaction is rolled back
# at the end and nothing is put on the queue: send_mail is called with
# force_send=False, so a mail.mail row is written and never transmitted.
Mail = env['mail.mail']                                             # noqa: F821
rows = []
for request_type in Type.search([]):
    request = Request.create({'request_type_id': request_type.id})
    if 'approval_type' in request._fields:
        # What the four leave templates choose between. Any of them proves the
        # type sends; which one is the office's decision, not this tool's.
        request.approval_type = 'none'
    before = Mail.search_count([('model', '=', 'ssc.request'),
                                ('res_id', '=', request.id)])
    for method in ('_send_approval_email', '_send_advance_email'):
        if hasattr(request, method):
            getattr(request, method)()
    sent = Mail.search([('model', '=', 'ssc.request'),
                        ('res_id', '=', request.id)])
    rows.append((request_type, len(sent) - before,
                 ", ".join(sent.mapped('subject'))))

for request_type, count, subjects in sorted(rows, key=lambda row: -row[1]):
    print("  %-5s %-34s %s"
          % (request_type.code, request_type.name,
             "%s email" % count if count else "-"))

print()
print("  The leave types are shown with approval_type set, because without it")
print("  no email is sent at all - the four templates differ in what they say")
print("  about the air ticket and the code refuses to guess between them. A")
print("  leave approved with that field left empty sends nothing and says so")
print("  in the chatter.")

title("ADDRESSES THE APPLICATION STORES AND NEVER WRITES TO")
# A field that holds an email address and has no sender is worse than a
# missing feature: the form asks somebody to keep it up to date, and the
# keeping is for nothing.
suspects = []
for model_name in ('ssc.request', 'ssc.request.certificate', 'project.project'):
    if model_name not in env:                                        # noqa: F821
        continue
    for name, field in env[model_name]._fields.items():              # noqa: F821
        if 'email' in name and field.type == 'char':
            suspects.append((model_name, name, field.string))
if not suspects:
    print("  none")
for model_name, name, label in suspects:
    print("  %-26s %-22s %s" % (model_name, name, label))
print()
print("  Each of these is a destination on a form. Check it against the")
print("  templates above: any that appears in no email_to, no email_cc and")
print("  no send call is an address the office maintains for nothing.")

env.cr.rollback()                                                  # noqa: F821
print()
print("rolled back - nothing was created and nothing was sent")
