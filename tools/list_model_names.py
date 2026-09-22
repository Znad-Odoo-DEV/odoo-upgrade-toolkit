"""Just the model names, one per line, for a shell loop to read.

    SSC_MATCH='^x_[0-9]' odoo-bin shell --no-http --shell-interface=python \\
        < tools/list_model_names.py 2>/dev/null | grep '^x_' > ~/family.txt

Reads only, and prints nothing but names. tools/list_models_by_prefix.py is for
reading; this is for piping - deleting fifty-eight models one command at a time
is not a thing anybody should do by hand, and the list has to come out of the
database rather than out of a terminal scrollback that was truncated.

Children before parents, because a line model whose parent is still there is a
line model that refuses. Within that, alphabetical, so two runs produce the same
order and a re-run is a re-run rather than a different attempt.
"""
import os
import re

MATCH = os.environ.get('SSC_MATCH') or ''

IrModel = env['ir.model'].sudo()                                 # noqa: F821

if not MATCH:
    raise SystemExit("Set SSC_MATCH, e.g. SSC_MATCH='^x_[0-9]'")

wanted = re.compile(MATCH)
names = sorted(r.model for r in IrModel.search([]) if wanted.search(r.model))

# A Studio line model is named after its parent, so the longer name is the
# child of the shorter one it starts with. Deepest first.
names.sort(key=lambda name: (-name.count('_line'), -len(name), name))

for name in names:
    print(name)
