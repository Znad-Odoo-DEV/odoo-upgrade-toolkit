"""Which ssc.employee field already has a home on hr.employee or hr.version.

    odoo-bin shell -d <database> --no-http < tools/probe_employee_field_map.py

Read only. Nothing is written, ever.

ssc.employee is to be replaced by hr.employee, and the question is which of its
34 fields need adding at all. Guessing from the community source answers it
wrongly: this database runs enterprise too, so hr_payroll and the localisation
have put fields on hr.employee and hr.version that a community checkout cannot
see. So ask the registry instead of reading code.

For every ssc.employee field this prints the native candidates - matched on the
name, on the words in the label, and on the type - and says which module put
each one there, so a field that is already ours is not mistaken for a native
one. It also counts how many employees actually carry a value in each ssc
field: a field nobody ever filled needs no home anywhere.
"""
import re
from collections import defaultdict

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env

IrField = env['ir.model.fields']
Ssc = env['ssc.employee']
Hr = env['hr.employee']

TARGETS = ['hr.employee', 'hr.version']

STOP = {'the', 'and', 'for', 'per', 'of', 'id', 'no', 'date'}


def words(text):
    return {w for w in re.findall(r'[a-z]+', (text or '').lower())
            if len(w) > 2 and w not in STOP}


def title(text):
    print()
    print("=" * 108)
    print(text)
    print("=" * 108)


# ----------------------------------------------------------------------
# Everything the target models offer, with the module that defined it.
# ----------------------------------------------------------------------
native = []
for model in TARGETS:
    for rec in IrField.search([('model', '=', model)]):
        native.append({
            'model': model,
            'name': rec.name,
            'label': rec.field_description,
            'ttype': rec.ttype,
            'module': rec.modules or '',
            'words': words(rec.name.replace('_', ' ')) | words(rec.field_description),
        })
print("%s field(s) on hr.employee + hr.version" % len(native))

# ----------------------------------------------------------------------
title("1. EVERY ssc.employee FIELD, AND WHAT COULD ALREADY HOLD IT")
# ----------------------------------------------------------------------
total_employees = Ssc.search_count([])
print("%s ssc.employee record(s)\n" % total_employees)

for rec in IrField.search([('model', '=', 'ssc.employee')], order='name'):
    # Skip the plumbing: ids, audit columns and everything mail.thread and
    # mail.activity.mixin bring along. None of it is a business field, and
    # hr.employee inherits the same mixins anyway.
    if rec.name in ('id', 'display_name', 'create_uid', 'create_date',
                    'write_uid', 'write_date', '__last_update'):
        continue
    if rec.name.startswith(('activity_', 'message_', 'rating_',
                            'website_message_', 'my_activity_', 'has_message',
                            'access_')):
        continue
    # How many employees actually carry a value. A field nobody filled needs
    # no home: it is dead weight being carried into a shared model.
    filled = '-'
    try:
        if rec.ttype in ('monetary', 'float', 'integer'):
            filled = Ssc.search_count([(rec.name, '!=', 0)])
        elif rec.ttype == 'boolean':
            filled = Ssc.search_count([(rec.name, '=', True)])
        elif rec.ttype in ('char', 'text', 'html', 'date', 'datetime',
                           'many2one', 'selection', 'binary'):
            filled = Ssc.search_count([(rec.name, '!=', False)])
    except Exception:
        filled = '-'

    mine = words(rec.name.replace('_', ' ')) | words(rec.field_description)
    scored = []
    for cand in native:
        overlap = mine & cand['words']
        if not overlap:
            continue
        score = len(overlap) * 2
        if cand['name'] == rec.name:
            score += 10
        if cand['ttype'] == rec.ttype:
            score += 2
        scored.append((score, cand))
    scored.sort(key=lambda pair: -pair[0])

    print("%-28s %-12s filled=%-5s" % (rec.name, rec.ttype, filled))
    if not scored:
        print("      -> nothing native looks like it")
    for score, cand in scored[:3]:
        print("      -> %-16s %-26s %-10s [%s]"
              % (cand['model'].replace('hr.', ''), cand['name'], cand['ttype'],
                 cand['module']))
    print()

# ----------------------------------------------------------------------
title("2. MONEY AND TIME FIELDS ALREADY ON hr.employee / hr.version")
# ----------------------------------------------------------------------
# The ones that matter for payroll, whoever put them there. This is where an
# enterprise or localisation module shows up that the source tree does not have.
INTEREST = ('wage', 'salary', 'allowance', 'housing', 'transport', 'travel',
            'overtime', 'hour', 'rate', 'basic', 'gross', 'net', 'bonus',
            'phone', 'ticket', 'leave', 'gratuity', 'end of service')
seen = set()
by_module = defaultdict(list)
for cand in native:
    hay = (cand['name'] + ' ' + (cand['label'] or '')).lower()
    if not any(k in hay for k in INTEREST):
        continue
    key = (cand['model'], cand['name'])
    if key in seen:
        continue
    seen.add(key)
    by_module[cand['module'] or '(core)'].append(cand)

for module in sorted(by_module):
    print("\n--- %s ---" % module)
    for cand in sorted(by_module[module], key=lambda c: c['name']):
        print("    %-10s %-34s %-12s %s"
              % (cand['model'].replace('hr.', ''), cand['name'], cand['ttype'],
                 (cand['label'] or '')[:40]))

# ----------------------------------------------------------------------
title("3. THE TWO CODES")
# ----------------------------------------------------------------------
# ssc.employee carries two identifiers - the payroll badge and the punch device
# id - and hr.employee has barcode, pin and registration_number. Which is free?
for name in ('barcode', 'pin', 'registration_number'):
    field = IrField.search([('model', '=', 'hr.employee'), ('name', '=', name)], limit=1)
    if not field:
        print("%-22s does not exist on hr.employee" % name)
        continue
    used = Hr.search_count([(name, '!=', False)])
    print("%-22s exists [%s], filled on %s of %s hr.employee"
          % (name, field.modules, used, Hr.search_count([])))
print()
print("ssc.employee.employee_code  filled on %s"
      % Ssc.search_count([('employee_code', '!=', False)]))
print("ssc.employee.attendance_code filled on %s"
      % Ssc.search_count([('attendance_code', '!=', False)]))
same = Ssc.search_count([('employee_code', '!=', False),
                         ('attendance_code', '!=', False)])
both = Ssc.search([('employee_code', '!=', False), ('attendance_code', '!=', False)])
identical = len([e for e in both
                 if (e.employee_code or '').strip() == (e.attendance_code or '').strip()])
print("both filled on %s, and identical on %s of those" % (same, identical))
print("(if they are always identical, one field is enough and barcode is it)")

# ----------------------------------------------------------------------
title("4. CAN THE SWITCH BE MADE AT ALL")
# ----------------------------------------------------------------------
# The two facts that decide whether ssc.employee ids can be translated to
# hr.employee ids without merging two people into one.
no_link = Ssc.search([('hr_employee_id', '=', False)])
print("ssc.employee with no hr.employee: %s" % len(no_link))
for emp in no_link[:20]:
    print("    %s [%s] %s" % (emp.name, emp.employee_code or 'no code',
                              emp.company_id.name))
if len(no_link) > 20:
    print("    ... and %s more" % (len(no_link) - 20))

shared = defaultdict(list)
for emp in Ssc.search([('hr_employee_id', '!=', False)]):
    shared[emp.hr_employee_id.id].append(emp)
clashes = {k: v for k, v in shared.items() if len(v) > 1}
print()
print("hr.employee claimed by more than one ssc.employee: %s" % len(clashes))
for hr_id, emps in list(clashes.items())[:20]:
    print("    %s <- %s" % (Hr.browse(hr_id).name,
                            ", ".join("%s [%s]" % (e.name, e.employee_code or '-')
                                      for e in emps)))
print()
print("These two numbers decide the whole thing: an ssc.employee with no")
print("hr.employee has nowhere for its payslips to go, and two of them sharing")
print("one hr.employee would merge two people's history into one record.")

print("\nDone. Read only - nothing was written.")
