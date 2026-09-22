"""The views of a Studio model, as the screen actually shows them.

    SSC_MODELS=x_all_requests,x_requesttypes \
        odoo-bin shell --no-http --shell-interface=python < tools/dump_studio_views.py
    SSC_OUT=~/views     where to write them (default ~/studio_views)

Reads only. Writes files and nothing else.

A Studio screen is never one view. There is the default Odoo generates from the
model, and then a customisation that inherits it and moves half of it around,
and sometimes a third inheriting that. Reading the first one tells you almost
nothing about what people see.

So both are written: every view's own arch, and - for the ones that are the top
of a chain - the combined arch, which is the XML the client is actually given.
The combined one is what to read when you are rebuilding a screen and want it to
come out looking like the screen people are used to.

One file per view, named so they sort into something you can walk through:

    x_all_requests/form-2208-combined.xml
    x_all_requests/form-2208-own.xml
    x_all_requests/form-2210-own.xml        (the Studio customisation)
"""
import os

MODELS = [m.strip() for m in (os.environ.get('SSC_MODELS') or '').split(',') if m.strip()]
OUT = os.path.expanduser(os.environ.get('SSC_OUT') or '~/studio_views')

View = env['ir.ui.view'].sudo()                                  # noqa: F821

if not MODELS:
    raise SystemExit("Set SSC_MODELS=x_all_requests,x_requesttypes")


def safe(text):
    keep = "-_."
    return "".join(c if c.isalnum() or c in keep else '_' for c in (text or ''))[:60]


def pretty(arch):
    """Indent the arch so it can be read, without changing it."""
    try:
        from lxml import etree
        tree = etree.fromstring(arch.encode())
        etree.indent(tree, space="    ")
        return etree.tostring(tree, encoding='unicode', pretty_print=True)
    except Exception:
        return arch


written, index = 0, []
for model_name in MODELS:
    folder = os.path.join(OUT, safe(model_name))
    os.makedirs(folder, exist_ok=True)
    views = View.search([('model', '=', model_name)], order='type, id')
    if not views:
        print("  %s has no views" % model_name)
        continue

    print("\n%s" % model_name)
    for view in views:
        # its own arch, which is a diff when it inherits something
        own = os.path.join(folder, "%s-%s-own.xml" % (view.type, view.id))
        with open(own, 'w', encoding='utf-8') as handle:
            handle.write("<!-- %s\n     id %s   type %s   inherits %s\n"
                         "     xmlid %s -->\n"
                         % (view.name or '', view.id, view.type,
                            view.inherit_id.id or '-',
                            view.get_external_id().get(view.id) or '-'))
            handle.write(pretty(view.arch or ''))
        written += 1

        # the combined arch, for the ones nothing inherits: that is the screen
        children = View.search_count([('inherit_id', '=', view.id)])
        combined_path = ''
        if not view.inherit_id or not children:
            try:
                combined = view.get_combined_arch()
            except Exception as exc:
                combined = "<!-- could not combine: %s -->" % exc
            top = view
            while top.inherit_id:
                top = top.inherit_id
            if top == view or not children:
                combined_path = os.path.join(
                    folder, "%s-%s-combined.xml" % (view.type, view.id))
                with open(combined_path, 'w', encoding='utf-8') as handle:
                    handle.write("<!-- %s - as the screen shows it -->\n"
                                 % (view.name or ''))
                    handle.write(pretty(combined))
                written += 1

        print("  %-8s %-6s %-46s %s"
              % (view.type, view.id, (view.name or '')[:46],
                 "inherits %s" % view.inherit_id.id if view.inherit_id
                 else ("%s child view(s)" % children if children else "standalone")))
        index.append((model_name, view.type, view.id, view.name or '',
                      own, combined_path))

print("\n%s file(s) written under %s" % (written, OUT))
print("""
  The -combined.xml of the top view is the screen. The -own.xml of a Studio
  customisation is the diff it applies, which is worth reading when you want to
  know what somebody changed and why the default looks nothing like the form.

  Read them with:

      ls -R %s
      cat %s/x_all_requests/form-*-combined.xml
""" % (OUT, OUT))
