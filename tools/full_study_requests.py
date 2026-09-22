"""Everything the Studio requests family is, and what of it we have.

    odoo-bin shell --no-http --shell-interface=python \
        < tools/full_study_requests.py

    SSC_SECTION=5     print one section only
    SSC_FULL=1        section 7 prints the raw arch as well as the field list
    SSC_OUT=~/full_study.md

Reads only. Nothing is summarised away.

The earlier audit compared fields and read the server actions. This is the
whole of it, because "the whole of it" is the only thing that can be checked
off - and because a Studio model keeps its behaviour in more places than
anybody remembers:

    1   the models, and how much is in them
    2   every field: stored, computed or related, its code, and ours
    3   the compute code in full, on the model and on its lines
    4   the server actions, in full
    5   the automation rules: trigger, filter, and the code they run
    6   the SCHEDULED actions - ir.cron - which nothing has looked at yet
    7   every view of every kind: form, list, kanban, search, and the rest
    8   the window actions and the menus that reach them
    9   the reports, the mail templates, the access rules and record rules
    10  the verdict: everything above with no answer on our side

Section 6 exists because a cron is the one piece of behaviour that leaves no
trace on a screen. A field nobody fills is visible. A server action is on a
button. A scheduled action runs at four in the morning, writes to records
nobody is looking at, and the only sign of it is that the numbers are
different on Tuesday. Deleting a Studio model whose cron is still scheduled
leaves a job that fails nightly into a log nobody reads.

Section 7 prints kanban and search views as well as forms and lists, because
the kanban is what people see first and the search view is what decides
whether they can find anything - and neither shows up in a field list.
"""
import os
import re

ONLY = os.environ.get('SSC_SECTION')
FULL = os.environ.get('SSC_FULL') == '1'
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/full_study.md')

STUDIO = [
    'x_all_requests',
    'x_requesttypes',
    'x_approval_requests_tag',
    'x_attachments',
    'x_requests_sequence',
]

MINE = [
    'ssc.request',
    'ssc.request.type',
    'ssc.request.sequence',
    'ssc.request.material.line',
    'ssc.request.installment',
    'ssc.request.certificate.line',
    'ssc.request.certificate.claim',
]

PLUMBING = {
    'id', 'create_uid', 'create_date', 'write_uid', 'write_date',
    'display_name', '__last_update', 'message_ids', 'message_follower_ids',
    'message_partner_ids', 'message_is_follower', 'message_unread',
    'message_unread_counter', 'message_needaction', 'message_needaction_counter',
    'message_has_error', 'message_has_error_counter', 'message_attachment_count',
    'message_main_attachment_id', 'has_message', 'rating_ids',
    'website_message_ids', 'activity_ids', 'activity_state', 'activity_user_id',
    'activity_type_id', 'activity_type_icon', 'activity_date_deadline',
    'activity_summary', 'activity_exception_decoration',
    'activity_exception_icon', 'my_activity_date_deadline',
    'activity_calendar_event_id',
}

report = []


def say(line=''):
    print(line)
    report.append(line)


def title(text, rule='='):
    say()
    say(rule * 100)
    say(text)
    say(rule * 100)


def wanted(number):
    return ONLY is None or ONLY == str(number)


def g(record, name, default=None):
    try:
        return record[name]
    except Exception:
        return default


def normalise(text):
    return re.sub(r'[^a-z0-9]', '', (text or '').lower())


IrModel = env['ir.model'].sudo()                                 # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821
IrView = env['ir.ui.view'].sudo()                                # noqa: F821
IrAction = env['ir.actions.act_window'].sudo()                   # noqa: F821
IrServer = env['ir.actions.server'].sudo()                       # noqa: F821
IrCron = env['ir.cron'].sudo()                                   # noqa: F821
IrMenu = env['ir.ui.menu'].sudo()                                # noqa: F821
IrRule = env['ir.rule'].sudo()                                   # noqa: F821
IrAccess = env['ir.model.access'].sudo()                         # noqa: F821
IrReport = env['ir.actions.report'].sudo()                       # noqa: F821
MailTemplate = env['mail.template'].sudo()                       # noqa: F821
Automation = env.get('base.automation')                          # noqa: F821

HERE = [m for m in STUDIO if m in env]                           # noqa: F821
MINE_HERE = [m for m in MINE if m in env]                        # noqa: F821

# what our side is called, in one flat set, so a Studio name can be looked for
ours_names, ours_labels = set(), set()
for model_name in MINE_HERE:
    for field in IrField.search([('model', '=', model_name)]):
        ours_names.add(normalise(field.name))
        ours_labels.add(normalise(field.field_description))

missing = []          # section 10 collects into this


# ============================================================== 1 ============
if wanted(1):
    title("1. the models, and how much is in them")
    say()
    say("      %-34s %10s %10s %s" % ("model", "rows", "fields", "description"))
    say()
    for model_name in STUDIO:
        if model_name not in env:                                # noqa: F821
            say("      %-34s %10s" % (model_name, "NOT HERE"))
            continue
        model = IrModel.search([('model', '=', model_name)], limit=1)
        rows = env[model_name].sudo().with_context(               # noqa: F821
            active_test=False).search_count([])
        count = IrField.search_count([('model', '=', model_name)])
        say("      %-34s %10s %10s %s"
            % (model_name, rows, count, model.name or ''))
    say()
    say("  and ours:")
    say()
    for model_name in MINE:
        if model_name not in env:                                # noqa: F821
            say("      %-34s %10s" % (model_name, "NOT INSTALLED"))
            continue
        rows = env[model_name].sudo().with_context(               # noqa: F821
            active_test=False).search_count([])
        count = IrField.search_count([('model', '=', model_name)])
        say("      %-34s %10s %10s" % (model_name, rows, count))


# ============================================================== 2 ============
if wanted(2):
    title("2. every field, what it is, and whether we answer to it")
    say("""  carried   a field of ours has the same name or the same label
  MISSING   rows hold a value and nothing of ours answers to it
  empty     no row ever filled it, so there was nothing to carry
""")
    for model_name in HERE:
        Model = env[model_name].sudo()                            # noqa: F821
        rows = Model.with_context(active_test=False).search([])
        title("   %s   -   %s row(s)" % (model_name, len(rows)), '-')
        say("      %-40s %-10s %-22s %6s  %s"
            % ("field", "type", "how it gets its value", "filled", "ours"))
        say()
        for field in IrField.search([('model', '=', model_name)], order='name'):
            if field.name in PLUMBING:
                continue
            filled = 0
            for row in rows:
                try:
                    if row[field.name]:
                        filled += 1
                except Exception:
                    filled = -1
                    break
            if field.compute:
                how = "computed" + (", stored" if field.store else "")
            elif field.related:
                how = "related"
            else:
                how = "typed"
            bare = re.sub(r'^x_studio_|^x_', '', field.name)
            answer = ''
            if normalise(bare) in ours_names:
                answer = "carried (name)"
            elif normalise(field.field_description) in ours_labels:
                answer = "carried (label)"
            elif filled == 0:
                answer = "empty - nothing to carry"
            else:
                answer = "MISSING"
                missing.append((model_name, field.name, field.ttype, filled,
                                field.field_description))
            say("      %-40s %-10s %-22s %6s  %s"
                % (field.name[:40], field.ttype, how, filled, answer))


# ============================================================== 3 ============
if wanted(3):
    title("3. the compute code and the related paths, in full")
    for model_name in HERE:
        fields = IrField.search(['|', ('compute', '!=', False),
                                 ('related', '!=', False),
                                 ('model', '=', model_name)], order='name')
        fields = fields.filtered(lambda f: f.model == model_name)
        if not fields:
            continue
        title("   %s" % model_name, '-')
        for field in fields:
            say()
            say("  %s   (%s)" % (field.name, field.field_description))
            if field.related:
                say("      related: %s" % field.related)
            if field.depends:
                say("      depends: %s" % field.depends)
            if field.compute:
                for line in (field.compute or '').split('\n'):
                    say("          %s" % line)


# ============================================================== 4 ============
if wanted(4):
    title("4. the server actions, in full")
    actions = IrServer.search([('model_id.model', 'in', HERE)])
    say()
    say("  %s server action(s) on these models" % len(actions))
    for action in actions:
        title("   %s   (%s)" % (action.name, action.model_id.model), '-')
        say("      state        %s" % action.state)
        say("      binding      %s" % (action.binding_model_id.model or "(none)"))
        if action.state != 'code':
            for name in ('update_path', 'value', 'crud_model_id',
                         'link_field_id'):
                value = g(action, name)
                if value:
                    say("      %-12s %s" % (name, value))
        for line in (action.code or '').split('\n'):
            say("          %s" % line)


# ============================================================== 5 ============
if wanted(5):
    title("5. the automation rules: what fires them, and what they run")
    if Automation is None:
        say("  base_automation is not installed here.")
    else:
        rules = Automation.sudo().search([('model_id.model', 'in', HERE)])
        say()
        say("  %s rule(s)" % len(rules))
        for rule in rules:
            title("   %s   (%s)" % (rule.name, rule.model_id.model), '-')
            say("      trigger          %s" % rule.trigger)
            say("      active           %s" % rule.active)
            for name in ('trigger_field_ids', 'filter_pre_domain',
                         'filter_domain', 'on_change_field_ids',
                         'trg_date_id', 'trg_date_range',
                         'trg_date_range_type', 'trg_selection_field_id'):
                value = g(rule, name)
                if not value:
                    continue
                if hasattr(value, 'mapped'):
                    value = ", ".join(value.mapped('name'))
                say("      %-16s %s" % (name, value))
            for child in rule.action_server_ids:
                say()
                say("      ---- %s   (%s)" % (child.name, child.state))
                for line in (child.code or '').split('\n'):
                    say("          %s" % line)


# ============================================================== 6 ============
if wanted(6):
    title("6. the SCHEDULED actions - the ones that leave no trace on a screen")
    say("""  A cron is the piece of behaviour nothing has looked at yet. A field
  nobody fills is visible; a server action sits on a button. A scheduled
  action runs at four in the morning, writes to records nobody is watching,
  and the only sign of it is that the numbers are different on Tuesday.

  Deleting a Studio model whose cron is still scheduled leaves a job failing
  nightly into a log nobody reads.
""")
    crons = IrCron.with_context(active_test=False).search([])
    touching = []
    for cron in crons:
        body = "%s %s" % (cron.code or '', g(cron, 'model_id').model
                          if g(cron, 'model_id') else '')
        if any(name in body for name in HERE) or (
                g(cron, 'model_id') and cron.model_id.model in HERE):
            touching.append(cron)
    say("  %s scheduled action(s) on this database, %s of them naming one of"
        % (len(crons), len(touching)))
    say("  these models")
    for cron in touching:
        title("   %s" % cron.name, '-')
        say("      model        %s" % (cron.model_id.model if cron.model_id else ''))
        say("      active       %s" % cron.active)
        say("      every        %s %s" % (cron.interval_number,
                                          cron.interval_type))
        say("      next call    %s" % cron.nextcall)
        say("      user         %s" % cron.user_id.name)
        for line in (cron.code or '').split('\n'):
            say("          %s" % line)

    say()
    say("  and every scheduled action on this database, so that one naming a")
    say("  model in a string we did not match is still visible:")
    say()
    for cron in crons:
        say("      %-52s %-22s %s %s"
            % (cron.name[:52], (cron.model_id.model if cron.model_id else '')[:22],
               "on " if cron.active else "OFF", cron.nextcall or ''))


# ============================================================== 7 ============
if wanted(7):
    title("7. every view of every kind, as it renders on this database")
    for model_name in HERE:
        views = IrView.with_context(active_test=False).search(
            [('model', '=', model_name)], order='type, priority, id')
        title("   %s   -   %s view(s)" % (model_name, len(views)), '-')
        kinds = {}
        for view in views:
            kinds[view.type] = kinds.get(view.type, 0) + 1
        say("      by kind: %s"
            % ", ".join("%s %s" % (count, kind)
                        for kind, count in sorted(kinds.items())))
        for view in views:
            say()
            say("      ......... %-10s %-40s priority %s%s"
                % (view.type, view.name[:40], view.priority,
                   "  inherits %s" % view.inherit_id.name
                   if view.inherit_id else ""))
            arch = view.arch_db or ''

            # What the screen SHOWS, in the order it shows it.
            #
            # The raw arch of a Studio form is thousands of lines of wrapper
            # divs, and the question this section asks - what is on the screen,
            # in what order, under which page - is answered by the field list
            # and buried by the XML. The first version printed the arch and the
            # output was cut off by the terminal before the second model.
            # SSC_FULL=1 prints it as well, for when a specific view has to be
            # read line by line.
            pages = re.findall(r'<page[^>]*string="([^"]*)"', arch)
            if pages:
                say("          pages:   %s" % " | ".join(pages))
            buttons = re.findall(r'<button[^>]*name="([^"]*)"', arch)
            if buttons:
                say("          buttons: %s" % ", ".join(dict.fromkeys(buttons)))
            filters = re.findall(r'<filter[^>]*string="([^"]*)"', arch)
            if filters:
                say("          filters: %s" % " | ".join(filters))
            shown = list(dict.fromkeys(
                re.findall(r'<field[^>]*name="([^"]*)"', arch)))
            if shown:
                say("          %s field(s), in order:" % len(shown))
                for index in range(0, len(shown), 4):
                    say("              %s" % "  ".join(
                        "%-32s" % name for name in shown[index:index + 4]))
            if FULL:
                say("          --- the arch ---")
                for line in arch.split('\n'):
                    say("          %s" % line)


# ============================================================== 8 ============
if wanted(8):
    title("8. the window actions and the menus that reach them")
    actions = IrAction.search([('res_model', 'in', HERE)])
    say()
    say("  %s window action(s)" % len(actions))
    for action in actions:
        say()
        say("      %s" % action.name)
        say("          model     %s" % action.res_model)
        say("          views     %s" % action.view_mode)
        say("          domain    %s" % (action.domain or ''))
        say("          context   %s" % (action.context or ''))
        say("          filter    %s" % (action.search_view_id.name or ''))
        menus = IrMenu.with_context(active_test=False).search(
            [('action', '=', 'ir.actions.act_window,%s' % action.id)])
        for menu in menus:
            say("          menu      %s" % menu.complete_name)
        if not menus:
            say("          menu      (none - opened from a button or a link)")


# ============================================================== 9 ============
if wanted(9):
    title("9. reports, mail templates, access rules and record rules")

    say()
    say("  reports:")
    for rep in IrReport.search([('model', 'in', HERE)]):
        say("      %-44s %-24s %s" % (rep.name[:44], rep.model,
                                      rep.report_name))

    say()
    say("  mail templates:")
    for template in MailTemplate.search([('model', 'in', HERE)]):
        say("      %-44s %-24s subject: %s"
            % (template.name[:44], template.model,
               (template.subject or '')[:30]))

    say()
    say("  access rules:")
    for access in IrAccess.search([('model_id.model', 'in', HERE)]):
        say("      %-40s %-30s r%s w%s c%s u%s"
            % (access.name[:40], (access.group_id.name or "(everyone)")[:30],
               int(access.perm_read), int(access.perm_write),
               int(access.perm_create), int(access.perm_unlink)))

    say()
    say("  record rules:")
    for rule in IrRule.with_context(active_test=False).search(
            [('model_id.model', 'in', HERE)]):
        # Two names read from the source rather than guessed at, both after
        # guessing them wrong: "global" is a Python keyword and is read by
        # subscript, and the many2many to groups is "groups" and not
        # "group_ids". Each raised and took this whole section down, and a
        # section that writes no file looks exactly like one with nothing to
        # say.
        #
        # And active, which was missing. Global rules are AND-ed together, and
        # two of Studio's are global: one says the record must be locked and
        # the other says it must not be. If both are on, no non-superuser sees
        # any request at all - so which is archived is the difference between
        # a working system and an unreadable one.
        say("      %-40s %-4s global=%-6s %s"
            % (rule.name[:40], "on" if rule.active else "OFF",
               rule['global'], ", ".join(rule.groups.mapped('name'))[:40]))
        say("          %s" % ((rule.domain_force or '').strip()
                              or "(no domain at all - it restricts nothing)"))

    say()
    say("  and ours, for the same four questions:")
    for model_name in MINE_HERE:
        say()
        say("      %s" % model_name)
        for access in IrAccess.search([('model_id.model', '=', model_name)]):
            say("          %-34s %-28s r%s w%s c%s u%s"
                % (access.name[:34],
                   (access.group_id.name or "(everyone)")[:28],
                   int(access.perm_read), int(access.perm_write),
                   int(access.perm_create), int(access.perm_unlink)))
        for rule in IrRule.with_context(active_test=False).search(
                [('model_id.model', '=', model_name)]):
            say("          rule: %-28s %s"
                % (rule.name[:28], (rule.domain_force or '').strip()[:50]))


# ============================================================== 10 ===========
if wanted(10):
    title("10. the verdict - everything with no answer on our side")
    if not missing and ONLY:
        say("  Run without SSC_SECTION for this: it is filled in by section 2.")
    say()
    say("  %s field(s) hold a value in Studio and have no counterpart here."
        % len(missing))
    say()
    say("      %-24s %-38s %-10s %6s %s"
        % ("model", "field", "type", "rows", "label"))
    for model_name, name, ttype, filled, label in sorted(
            missing, key=lambda row: -row[3]):
        say("      %-24s %-38s %-10s %6s %s"
            % (model_name, name[:38], ttype, filled, (label or '')[:30]))

    say("""
  A row here is one of three things and the count says which:

    thousands   a field the office uses and we do not have. Build it.
    a hundred   worth asking about before deleting the model.
    a handful   somebody's afternoon. Let it go, but say so out loud.
""")

with open(OUT, 'w', encoding='utf-8') as handle:
    handle.write("\n".join(report))
print("\nwritten to %s" % OUT)

env.cr.rollback()                                                # noqa: F821
