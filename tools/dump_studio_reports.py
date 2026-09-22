"""The print-outs the Studio models produce, in full, with their templates.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/dump_studio_reports.py

    SSC_MODELS=x_all_requests,x_boq_s     which models' reports to read
    SSC_OUT=~/studio_reports.md

Reads only.

Four buttons print something today - Print MR, Print SPC, Print NOR, Print
Request - and what comes out of them is a piece of paper somebody signs, files
and sends to a client. Rewriting that layout from a description of it would
produce a document that is not the one the office uses, and the difference
would be found by whoever receives it rather than by us.

So this prints the report the way dump_mail_templates.py printed the emails:
the action, the paper format, and the QWeb arch exactly as it stands, plus
every sub-template the arch calls into, because a report that t-calls a header
is only half a report on the page.

The last section is the one to read first. It lists every field the arch
touches, which is the part that has to be re-pointed when the report moves to
ssc.request - and a t-field naming a column that no longer exists does not
raise, it prints a blank space on a document nobody re-reads before signing.
"""
import os
import re

MODELS = [m.strip() for m in (os.environ.get('SSC_MODELS') or '').split(',')
          if m.strip()]
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/studio_reports.md')

DEFAULT_MODELS = [
    'x_all_requests',
    'x_site_payment_certifi',
    'x_contractor_agreement',
    'x_boq_s',
    'x_project_time_schedul',
]

Report = env['ir.actions.report'].sudo()                         # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821
IrModelData = env['ir.model.data'].sudo()                        # noqa: F821

report_lines = []


def say(line=''):
    print(line)
    report_lines.append(line)


def title(text, rule='='):
    say()
    say(rule * 96)
    say(text)
    say(rule * 96)


def xmlid_of(record):
    data = IrModelData.search([('model', '=', record._name),
                               ('res_id', '=', record.id)], limit=1)
    return "%s.%s" % (data.module, data.name) if data else "(no xml id)"


def template_for(report_name):
    """The qweb view a report_name points at, however it is written.

    A report_name is usually module.template, but Studio writes some of them
    as the bare key, and a view can also carry the name without the module.
    Missing it means printing "no template" for a report that has one, so all
    three spellings are tried.
    """
    view = View.search([('type', '=', 'qweb'), ('key', '=', report_name)],
                       limit=1)
    if view:
        return view
    bare = report_name.split('.')[-1]
    return View.search([('type', '=', 'qweb'), ('key', 'like', '%%.%s' % bare)],
                       limit=1)


CALL = re.compile(r't-call=["\']([^"\']+)["\']')


def with_called_templates(view, seen=None):
    """A view and everything it calls, depth first, without looping."""
    seen = seen if seen is not None else set()
    if not view or view.id in seen:
        return View.browse()
    seen.add(view.id)
    found = view
    for key in CALL.findall(view.arch_db or ''):
        called = template_for(key)
        if called:
            found |= with_called_templates(called, seen)
        else:
            say("      t-call %-46s NOT ON THIS DATABASE" % key)
    return found


wanted = Report.browse()
for model in (MODELS or DEFAULT_MODELS):
    wanted |= Report.search([('model', '=', model)])

title("the reports these models print")
say("  %s report(s) across %s model(s)"
    % (len(wanted), len(MODELS or DEFAULT_MODELS)))
say()
for report in wanted:
    say("  %-30s %-24s %s" % (report.name, report.model, report.report_name))
if not wanted:
    say()
    say("  None. Either the print buttons call a server action rather than a")
    say("  report, or these models are not on this database.")

# ------------------------------------------------------------------ each one
for report in wanted:
    title("%s   -   %s" % (xmlid_of(report), report.name), '-')
    say("  model            %s" % report.model)
    say("  report_name      %s" % report.report_name)
    say("  type             %s" % report.report_type)
    say("  paper format     %s" % (report.paperformat_id.name or "(the company's)"))
    say("  printed name     %s" % (report.print_report_name or "(the record's)"))
    say("  saved as attachment  %s" % (report.attachment or "no"))
    say("  reuse saved copy     %s" % report.attachment_use)
    say("  on the print menu of  %s"
        % (report.binding_model_id.model or "(nothing - called from a button)"))

    root = template_for(report.report_name)
    if not root:
        say()
        say("  NO TEMPLATE FOUND for %s - this report cannot render"
            % report.report_name)
        continue

    say()
    say("  --- the arch, %s and everything it calls ---" % root.key)
    for view in with_called_templates(root):
        say()
        say("  ......... %s   (%s)" % (view.key, xmlid_of(view)))
        for line in (view.arch_db or '').split('\n'):
            say("      %s" % line)

# --------------------------------------------------- what the arch reads off
title("the fields the paper actually prints")
say("""  Each of these has to be pointed at a field on the new model. A t-field
  or t-out naming a column that is not there prints a blank - the report
  renders, the page comes out, and the line that should carry the amount is
  simply empty. That is the failure this list exists to prevent.
""")

FIELD = re.compile(r"""(?:t-field|t-out|t-esc)=["']([^"']+)["']""")
DOTTED = re.compile(r"\b(?:o|doc|object)\.((?:x_)?[A-Za-z_][\w.]*)")

for report in wanted:
    root = template_for(report.report_name)
    if not root:
        continue
    referenced = set()
    for view in with_called_templates(root):
        arch = view.arch_db or ''
        for expression in FIELD.findall(arch):
            referenced.add(expression.strip())
        for path in DOTTED.findall(arch):
            referenced.add(path)
    if not referenced:
        continue
    say()
    say("  %s  (%s)" % (report.name, report.model))
    for expression in sorted(referenced):
        say("      %s" % expression[:110])

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report_lines))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
