"""The mail templates a request sends, in full, with their xml ids.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/dump_mail_templates.py

    SSC_XMLIDS=confirm_alr.w_ticket,confirm_asr.send_email   only these
    SSC_MODELS=x_all_requests    every template on these models
    SSC_OUT=~/templates_full.md

Reads only.

The request workflow sends six emails, and the Studio actions name them by xml
id: confirm_alr.w_ticket, confirm_alr.w_ticket_reim, confirm_alr.rev_ticket,
confirm_alr.no_ticket, confirm_asr.send_email, ir_email.ssc. Those modules are
not in the repository - they were installed straight onto the database - so the
only copy of what those emails say is the database itself.

Rewriting the words would be the easy part and the wrong one. Hundreds of
employees have had these, somebody signed them off, and an approval email that
suddenly reads differently is a support call. So this prints them exactly:
subject, sender, recipients, language, attachments, and the body as it stands.

Anything with a {{ }} in it is a placeholder Odoo fills in when the mail is
sent. Those are listed on their own at the end, because they are the part that
has to keep working when the template moves to a new model - a body that says
object.x_studio_requested_for has to become object.employee_id, and a body that
quietly says nothing at all is how an email goes out addressed to no one.
"""
import os
import re

XMLIDS = [x.strip() for x in (os.environ.get('SSC_XMLIDS') or '').split(',')
          if x.strip()]
MODELS = [m.strip() for m in (os.environ.get('SSC_MODELS') or '').split(',')
          if m.strip()]
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/templates_full.md')

# what the request workflow actually sends, from the server action code
DEFAULT_XMLIDS = [
    'confirm_alr.w_ticket',
    'confirm_alr.w_ticket_reim',
    'confirm_alr.rev_ticket',
    'confirm_alr.no_ticket',
    'confirm_asr.send_email',
    'ir_email.ssc',
]

Template = env['mail.template'].sudo()                           # noqa: F821
IrModelData = env['ir.model.data'].sudo()                        # noqa: F821

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say()
    say(rule * 96)
    say(text)
    say(rule * 96)


def by_xmlid(ref):
    module, _sep, name = ref.partition('.')
    data = IrModelData.search([('module', '=', module), ('name', '=', name),
                               ('model', '=', 'mail.template')], limit=1)
    return Template.browse(data.res_id).exists() if data else Template.browse()


def xmlid_of(template):
    data = IrModelData.search([('model', '=', 'mail.template'),
                               ('res_id', '=', template.id)], limit=1)
    return "%s.%s" % (data.module, data.name) if data else "(no xml id)"


def strip_tags(html):
    """The body as words, so it can be read here as well as rendered."""
    text = re.sub(r'<br\s*/?>|</p>|</div>|</tr>', '\n', html or '')
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\n{3,}', '\n\n', text).strip()


wanted = Template.browse()
missing = []

for ref in (XMLIDS or DEFAULT_XMLIDS):
    found = by_xmlid(ref)
    if found:
        wanted |= found
    else:
        missing.append(ref)

for model in MODELS:
    wanted |= Template.search([('model', '=', model)])

title("the templates the request workflow sends")
say("  %s found, %s named in the code but not on this database"
    % (len(wanted), len(missing)))
if missing:
    say()
    for ref in missing:
        say("      %-34s NOT HERE - the action that names it would fail"
            % ref)

for template in wanted:
    title("%s   -   %s" % (xmlid_of(template), template.name), '-')
    say("  model        %s" % template.model)
    say("  subject      %s" % (template.subject or "(none)"))
    say("  from         %s" % (template.email_from or "(the company's default)"))
    say("  to           %s" % (template.email_to or ''))
    say("  partner_to   %s" % (template.partner_to or ''))
    say("  cc           %s" % (template.email_cc or ''))
    say("  reply-to     %s" % (template.reply_to or ''))
    say("  default recipients   %s" % template.use_default_to)
    say("  language     %s" % (template.lang or ''))
    say("  auto delete  %s" % template.auto_delete)
    if template.report_template_ids:
        say("  attaches     %s"
            % ", ".join(template.report_template_ids.mapped('name')))
    say()
    say("  --- the body, as words ---")
    for line in strip_tags(template.body_html).split('\n'):
        say("      %s" % line)
    say()
    say("  --- the body, as it is stored ---")
    for line in (template.body_html or '').split('\n'):
        say("      %s" % line)

title("the placeholders, which are the part that has to keep working")
say("""  A placeholder reads a field off the record the mail is about. When these
  templates move to ssc.request, every one of them has to be pointed at the
  new field - and a placeholder that names a field which no longer exists
  renders as nothing at all, so the email goes out with a blank where the
  employee's name should be and nobody is told.
""")

pattern = re.compile(r'\{\{(.*?)\}\}|\$\{(.*?)\}', re.S)
for template in wanted:
    found = set()
    for source in (template.subject or '', template.body_html or ''):
        for match in pattern.finditer(source):
            found.add((match.group(1) or match.group(2) or '').strip())
    if not found:
        continue
    say()
    say("  %s" % xmlid_of(template))
    for placeholder in sorted(found):
        say("      %s" % placeholder[:110])

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
