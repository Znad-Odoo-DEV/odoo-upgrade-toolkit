"""What the employee repoint left reading an attribute hr.employee does not have.

    odoo-bin shell --no-http --shell-interface=python < tools/find_broken_employee_paths.py

Reads only. Every field that named x_employeeslist names hr.employee now, and
the two models do not carry the same attributes: the badge and the passport
moved across, the allowances and the gratuity and the document expiry dates did
not. So anything that reached one of those through an employee link is reading
a field that is no longer at the end of the path.

The earlier count of such readers fell from thirty-nine to two, and not because
thirty-seven were fixed. The stocktake only counts a path that lands on
x_employeeslist, and after the repoint they land on hr.employee instead - broken
now rather than broken later. This finds them by walking the path and asking
whether the last step exists.

Two kinds:

 * related fields, where Odoo resolves the path itself and drops the field when
   it cannot - silently, so the screen fails on open rather than on save
 * server actions, where the path is written in code and fails at run time, in
   the middle of whatever the action was doing

The server actions are read with the same walk rather than by looking for
x_studio_ and hoping: a name is not evidence, and ninety-five candidates found
by keyword are mostly employees who are fine.
"""
import re

TARGET_MODEL = 'hr.employee'

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def resolve(model_name, parts):
    """Walk a dotted path. Returns (ok, where_it_broke)."""
    current = env.get(model_name)                                # noqa: F821
    if current is None:
        return True, None                    # not our business
    for index, part in enumerate(parts):
        if part not in current._fields:
            return False, '%s has no %s' % (current._name, part)
        field = current._fields[part]
        if index == len(parts) - 1:
            return True, None
        if not field.relational:
            return False, '%s.%s is not a link' % (current._name, part)
        current = env.get(field.comodel_name)                    # noqa: F821
        if current is None:
            return True, None
    return True, None


# --- 1. related fields --------------------------------------------------------

title("1. related fields whose path no longer resolves")

broken_related = []
for field in IrField.search([('related', '!=', False)]):
    parts = (field.related or '').split('.')
    ok, why = resolve(field.model, parts)
    if ok:
        continue
    # Only the ones broken by this move: the path has to step onto an employee.
    touches_employee = False
    current = env.get(field.model)                               # noqa: F821
    for part in parts[:-1]:
        if current is None or part not in current._fields:
            break
        sub = current._fields[part]
        if not sub.relational:
            break
        if sub.comodel_name == TARGET_MODEL:
            touches_employee = True
        current = env.get(sub.comodel_name)                      # noqa: F821
    broken_related.append((field, why, touches_employee))

ours = [row for row in broken_related if row[2]]
theirs = [row for row in broken_related if not row[2]]

print("  %s broken related field(s) in total" % len(broken_related))
print("  %s of them step through an employee - ours to answer for" % len(ours))
print("  %s were already broken before any of this" % len(theirs))

by_model = {}
for field, why, _ in ours:
    by_model.setdefault(field.model, []).append((field, why))
for model in sorted(by_model):
    print("\n  %s" % model)
    for field, why in sorted(by_model[model], key=lambda p: p[0].name):
        print("      %-36s %-40s %s" % (field.name, field.related, why))


# --- 2. server actions --------------------------------------------------------

title("2. server actions reading an attribute off an employee")

# Every field anywhere that points at an employee: these are the names a piece
# of code steps through to reach one.
employee_fields = {}
for field in IrField.search([('relation', '=', TARGET_MODEL)]):
    employee_fields.setdefault(field.name, set()).add(field.model)

Employee = env[TARGET_MODEL]                                     # noqa: F821
Server = env['ir.actions.server'].sudo()                         # noqa: F821

pattern = re.compile(r'\.(' + '|'.join(sorted(map(re.escape, employee_fields)))
                     + r')\.([A-Za-z_][A-Za-z_0-9]*)')

hits = {}
for action in Server.search([]):
    code = action.code or ''
    if not code:
        continue
    for link, attribute in pattern.findall(code):
        if attribute in Employee._fields:
            continue
        if attribute in ('ids', 'id', 'sudo', 'exists', 'mapped', 'filtered',
                         'browse', 'search', 'write', 'create', 'unlink',
                         'display_name', 'env', '_name'):
            continue
        hits.setdefault(action, set()).add((link, attribute))

print("  %s action(s) read something hr.employee does not have" % len(hits))
counts = {}
for action, pairs in hits.items():
    for link, attribute in pairs:
        counts[attribute] = counts.get(attribute, 0) + 1

print("\n  the attributes they reach for, most-used first:")
for attribute, count in sorted(counts.items(), key=lambda kv: -kv[1]):
    on_native = 'name' if attribute == 'x_name' else '-'
    print("      %-42s %3s action(s)   native: %s" % (attribute, count, on_native))

print("\n  action by action:")
for action in sorted(hits, key=lambda a: a.id):
    pairs = sorted(hits[action])
    print("  %-6s %-44s %s" % (action.id, (action.name or '')[:44],
                               ', '.join('%s.%s' % p for p in pairs[:3])
                               + (' ...' if len(pairs) > 3 else '')))


# --- 3. verdict ---------------------------------------------------------------

title("verdict")
print("""  %s related field(s) and %s server action(s) reach an attribute the native
  employee does not carry. x_name is the ordinary one and becomes name; the rest
  are attributes that deliberately did not move - the allowances, the gratuity,
  the document dates - and each one is a decision: read it off ssc.employee,
  which has it, or stop reading it at all.""" % (len(ours), len(hits)))
