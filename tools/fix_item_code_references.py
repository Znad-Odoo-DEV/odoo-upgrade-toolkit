"""Teach the automations to read an item the way a product reads.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/fix_item_code_references.py

Server actions all over the legacy estate reach through an item link and read
what the item used to carry: ``materials.x_studio_item.x_name``. The link is a
product now, and a product has no x_name - so the action raises the moment it
runs, which is how the material type came to be written on no product at all:
an automation fired on the write and died.

Every piece of stored code is rewritten, but only where the attribute follows a
field that actually points at a product. ``record.x_name`` on a legacy line is
the line's own name and is left exactly as it is; only ``<item field>.x_name``
becomes ``<item field>.name``.

Reported line by line before anything is written, because code is not data and
a bad rewrite here is a silent wrong answer later.
"""
import os
import re

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

TARGET_MODEL = 'product.template'

# what the item called it -> what the product calls it
ATTRS = {
    'x_name': 'name',
    'x_active': 'active',
    'x_studio_item_serial_no': 'x_item_serial_no',
    'x_studio_unit': 'x_unit',
    'x_studio_type': 'x_item_type',
    'x_studio_type_of_material': 'x_type_of_material',
    'x_studio_quantifiable': 'x_quantifiable',
    'x_studio_description_specifications': 'x_specifications',
    'x_studio_html': 'x_item_notes',
}

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# --- 1. which field names lead to a product --------------------------------

item_fields = sorted({
    f.name for f in IrField.search([('relation', '=', TARGET_MODEL)])
    if f.name.startswith('x_')
}, key=len, reverse=True)          # longest first, so x_studio_item_name wins
                                   # over x_studio_item

title("1. fields that now lead to a product")
print("  %s name(s): %s%s" % (len(item_fields), ', '.join(item_fields[:8]),
                              ' ...' if len(item_fields) > 8 else ''))


def rewrite(code):
    """Turn <item field>.<old attribute> into <item field>.<new attribute>."""
    changed = []
    for field_name in item_fields:
        for old, new in ATTRS.items():
            pattern = re.compile(r'(\b%s\s*\.\s*)%s\b' % (re.escape(field_name),
                                                          re.escape(old)))
            def swap(match):
                changed.append('%s.%s -> %s.%s' % (field_name, old, field_name, new))
                return match.group(1) + new
            code = pattern.sub(swap, code)
    return code, changed


# --- 2. what would change ---------------------------------------------------

title("2. code that reads an item the old way")

targets = []
for record in env['ir.actions.server'].sudo().search([('state', '=', 'code')]):  # noqa: F821
    new_code, changed = rewrite(record.code or '')
    if changed:
        targets.append(('ir.actions.server', record, new_code, changed))
for record in env['ir.cron'].sudo().search([]):                  # noqa: F821
    new_code, changed = rewrite(record.code or '')
    if changed:
        targets.append(('ir.cron', record, new_code, changed))

for model, record, _new_code, changed in targets:
    print("\n  %s %-6s %-26s %s"
          % (model.split('.')[-1], record.id,
             getattr(record, 'model_id', False) and record.model_id.model or '',
             (record.name or '')[:36]))
    for line in sorted(set(changed)):
        print("      %s" % line)
print("\n  %s piece(s) of code to rewrite" % len(targets))

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 3. rewrite -------------------------------------------------------------

title("3. rewriting")

for model, record, new_code, changed in targets:
    cr.execute("UPDATE %s SET code = %%s WHERE id = %%s"
               % ('ir_act_server' if model == 'ir.actions.server' else 'ir_cron'),
               (new_code, record.id))
    print("  %s %s rewritten (%s change(s))"
          % (model.split('.')[-1], record.id, len(changed)))
cr.commit()

title("summary")
print("  %s piece(s) of code now read the product" % len(targets))
print("""
  What is NOT covered: code that names a field by string - a domain like
  [('x_name', '=', ...)] built against a model this cannot see through. Run the
  screens that matter once before trusting them.""")
