"""Ask the blocking views to validate themselves, and say what they answer.

    SSC_VIEWS="Default form view for x_attachments_list,..." odoo-bin shell --no-http < tools/validate_named_views.py

Reads only. Odoo refuses to delete a field with "still present in views", and
names a view - but the check behind that message is blunt: it removes the field
from the registry, finds every view whose arch mentions the name, and asks each
one to validate. Any failure at all, for any reason, is reported as the field
still being present.

So a view that has been quietly broken for months blames whatever field is being
removed the day somebody tries. x_attachments_list has its own x_studio_value,
and its form was named as the reason x_to_pay.x_studio_value could not go - which
is either a real reference or a view that was already failing.

This asks the view directly, with nothing removed from anything, and prints what
it actually says.
"""
import os

NAMES = [n.strip() for n in (os.environ.get('SSC_VIEWS') or '').split(',') if n.strip()]

cr = env.cr                                                      # noqa: F821
View = env['ir.ui.view'].sudo()                                  # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


if not NAMES:
    print("  No SSC_VIEWS given - checking every view of the models in question.")
    NAMES = []

views = View.search([('name', 'in', NAMES)]) if NAMES else View.browse()

title("1. the views")

for view in views:
    print("  %-6s %-30s %s" % (view.id, view.model or '-', (view.name or '')[:44]))
print("\n  %s view(s)" % len(views))


title("2. what each one says when asked to validate")

healthy, broken = 0, []
for view in views:
    try:
        with cr.savepoint():
            view._check_xml()
        healthy += 1
        print("\n  %-6s ok" % view.id)
    except Exception as exc:
        broken.append(view)
        lines = [l.rstrip() for l in str(exc).strip().splitlines() if l.strip()]
        print("\n  %-6s %s" % (view.id, (view.name or '')[:50]))
        for line in lines[:8]:
            print("         %s" % line[:110])

print("\n  %s validate, %s do not" % (healthy, len(broken)))


title("what this means")
print("""  A view that fails here fails without anything having been deleted. It was
  already broken, and the deletion only asked the question that made it say so.
  Fixing or removing that view is its own piece of work, and unrelated to the
  model going - but nothing can be deleted past it until it is done.

  A view that validates cleanly here really is holding a reference to the field,
  and the node has to come out of it.""")
