"""The two boards, checked as arch rather than looked at.

Every assertion here exists because the thing it checks was wrong once and
nothing said so. A view has no tests: it loads, it renders, and a field nobody
can reach or a card anyone can drag through the approval chain looks exactly
like a working screen.

Read the final arch, not the file - get_view applies the inherited views, and
half of what is checked here (the subcontractor line) only exists after a
bridge module has had its say.
"""
from lxml import etree

Request = env['ssc.request']                                      # noqa: F821
Type = env['ssc.request.type']                                    # noqa: F821

ok, bad = [], []


def check(label, condition, detail=''):
    (ok if condition else bad).append("%-70s %s" % (label, detail))


def arch(model, xmlid, view_type):
    """The arch as the browser gets it, inherited views and all."""
    view = env.ref(xmlid)                                          # noqa: F821
    return etree.fromstring(
        env[model].get_view(view.id, view_type)['arch'])           # noqa: F821


card = arch('ssc.request', 'ssc_requests.view_ssc_request_kanban', 'kanban')
board = arch('ssc.request.type', 'ssc_requests.view_ssc_request_type_kanban',
             'kanban')

# --- the drag ---------------------------------------------------------------
# A kanban grouped by a field lets you drag a card between columns, and the
# drop writes that field. Grouped by state, that is the whole approval chain
# reduced to a mouse gesture: draft to approved, no number, no approver, no
# mail. Studio blocked it in the view and was right to.
kanban = card if card.tag == 'kanban' else card.find('.//kanban')
check("the board is grouped by state",
      kanban.get('default_group_by') == 'state', kanban.get('default_group_by'))
check("and a card cannot be dragged between its columns",
      kanban.get('records_draggable') in ('false', '0'),
      kanban.get('records_draggable') or "MISSING - draft can be dragged to approved")

# Said plainly, because the line above is a view attribute and a view attribute
# is not a guard. The server still takes the write; this records that it does
# rather than leaving somebody to find out.
draft = Request.create({
    'request_type_id': Type.search([('code', '=', 'MR')], limit=1).id,
    'description': "Cement, and a test of the back door",
})
draft.write({'state': 'approved'})
check("the SERVER still accepts a bare state write - the view is a lid, not a lock",
      draft.state == 'approved' and not draft.name,
      "approved with no number: %r" % (draft.name,))
draft.write({'state': 'draft'})

# --- the colour nobody could set --------------------------------------------
# highlight_color only adds a class. It does not add the picker. And
# web.KanbanRecordMenu renders nothing at all unless the arch carries a
# template called "menu" - so the colour was declared, read on every card, and
# unreachable by any user.
menu = kanban.find('.//templates/t[@t-name="menu"]')
if kanban.get('highlight_color'):
    check("highlight_color comes with a menu template, or nothing can set it",
          menu is not None, "menu template present" if menu is not None
          else "MISSING - the colour is decorative and unreachable")
    pickers = [f for f in (menu.findall('.//field') if menu is not None else [])
               if f.get('widget') == 'kanban_color_picker']
    check("and the picker in it points at the field highlight_color reads",
          len(pickers) == 1
          and pickers[0].get('name') == kanban.get('highlight_color'),
          kanban.get('highlight_color'))

# --- the ribbon -------------------------------------------------------------
# .ribbon span sets color to white at a higher specificity than any text-bg-*
# utility. text-bg-light is therefore white on near-white - which is the state
# of one of Studio's five ribbons.
ribbon = kanban.find('.//div[@class="ribbon ribbon-top-right"]')
check("the ribbon is Odoo's, not forty lines of scss doing the same thing",
      ribbon is not None, "web/views/widgets/ribbon")
classes = [f.get('class') for f in (ribbon.findall('.//field') if ribbon is not None else [])]
check("no ribbon uses text-bg-*, which .ribbon span overrides to white on light",
      all('text-bg' not in (c or '') for c in classes),
      ', '.join(c for c in classes if c))
states = dict(Request._fields['state'].selection)
covered = set()
for field in (ribbon.findall('.//field') if ribbon is not None else []):
    condition = field.get('t-if') or ''
    for key in states:
        if "'%s'" % key in condition:
            covered.add(key)
check("every state but draft has a ribbon colour",
      covered == set(states) - {'draft'},
      "missing: %s" % sorted(set(states) - {'draft'} - covered) if covered != set(states) - {'draft'}
      else "%s states" % len(covered))

# --- the labelled lines -----------------------------------------------------
# "Ahmed" on a line of its own is a name. "Submitted by: Ahmed" is a fact.
text = etree.tostring(kanban, encoding='unicode')
for label in ("Company:", "Submitted by:", "Request Date:", "For:", "Project:"):
    check("the card says %r, not a bare value" % label, label in text, "labelled")
# The base arch, before any bridge has spoken. Read from the database rather
# than the file: a relative path resolves against wherever the shell was
# started, which is not this repository.
base_arch = env.ref('ssc_requests.view_ssc_request_kanban').arch_db          # noqa: F821
check("and the subcontractor line arrives from the bridge, not the base module",
      "Subcontractor:" in text and 'partner_id' not in base_arch,
      "added by ssc_requests_subcontract")

# --- the dashboard ----------------------------------------------------------
check("the dashboard makes no Create button - a request starts from a card",
      board.get('create') in ('0', 'false'), board.get('create'))
check("and its cards do not open a type record when clicked",
      board.get('can_open') in ('0', 'false'),
      board.get('can_open') or "MISSING - clicking a card opens the settings")

board_text = etree.tostring(board, encoding='unicode')
# On the class attributes, not the raw text - the first version of this check
# matched the word "alert" in the comment that explains why there isn't one.
alerts = [element.get('class') for element in board.iter()
          if 'alert' in (element.get('class') or '')]
check("the counts box claims no alert role it cannot honour",
      not alerts, ', '.join(alerts) or "bg-light and a border")
check("nought is green and anything above it is red",
      board_text.count('#d4edda') == 3 and board_text.count('#f8d7da') == 3,
      "3 rows, both shades")

rows = {'pe_review': 'needs_pe_review', 'hr_review': 'needs_hr_review'}
for state, flag in rows.items():
    buttons = [b for b in board.findall('.//button')
               if "'%s'" % state in (b.get('context') or '')]
    check("the %s row is hidden on types that skip it" % state,
          len(buttons) == 1
          and flag in (buttons[0].getparent().get('invisible') or ''),
          buttons[0].getparent().get('invisible') if buttons else "NO ROW")

new_buttons = [b for b in board.findall('.//button')
               if b.get('name') == 'action_new_request']
check("one New button, and it is an object call rather than a hardcoded action",
      len(new_buttons) == 1 and new_buttons[0].get('type') == 'object',
      "action_new_request")

# Studio wrote thirteen copies of this card, one per type, each naming its own
# action and its own default. Thirteen copies is thirteen places to forget.
check("the board draws one card, not one per type",
      len(board.findall('.//templates/t[@t-name="card"]')) == 1,
      "1 template for %s types" % Type.search_count([]))

# --- what the buttons actually do -------------------------------------------
for request_type in Type.search([]):
    action = request_type.action_new_request()
    check("New %s opens a form with the type already chosen" % request_type.code,
          action['context'].get('default_request_type_id') == request_type.id,
          request_type.name)
    check("%s has an icon on its card" % request_type.code,
          bool(request_type.image), "drawn")

# --- the menus --------------------------------------------------------------
check("To Review is gone, action and all",
      not env.ref('ssc_requests.action_ssc_request_to_review',              # noqa: F821
                  raise_if_not_found=False), "removed")
all_requests = env.ref('ssc_requests.action_ssc_request')                   # noqa: F821
check("All Requests carries no domain",
      all_requests.domain in (False, '', '[]'), repr(all_requests.domain))
check("and no default filter - drafts, rejected and cancelled all show",
      'search_default' not in (all_requests.context or ''),
      repr(all_requests.context))
check("the dashboard action shows the board only",
      env.ref('ssc_requests.action_ssc_request_type').view_mode == 'kanban',  # noqa: F821
      "kanban")
check("and the settings action is the list, under Configuration",
      env.ref(                                                              # noqa: F821
          'ssc_requests.action_ssc_request_type_config').view_mode == 'list,form',
      "list,form")

# --- fields per type, which is what the form is for -------------------------
form = arch('ssc.request', 'ssc_requests.view_ssc_request_form', 'form')
form_text = etree.tostring(form, encoding='unicode')
check("the form carries type_code, or every per-type rule silently shows",
      form.find('.//field[@name="type_code"]') is not None, "present")
for code in ('ASR', 'SPC', 'MR', 'RES', 'ALR'):
    check("the form hides or shows something on %s" % code,
          "'%s'" % code in form_text, "has a rule")

print()
print("PASS  %s" % len(ok))
for row in ok:
    print("   ok   %s" % row)
if bad:
    print()
    print("FAIL  %s" % len(bad))
    for row in bad:
        print("   XX   %s" % row)
else:
    print()
    print("nothing failed")

env.cr.rollback()                                                  # noqa: F821
print("rolled back")
