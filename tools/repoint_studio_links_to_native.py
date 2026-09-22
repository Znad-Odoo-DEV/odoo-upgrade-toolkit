"""Point the links that survive a deletion at the record that replaced it.

    odoo-bin shell --no-http --shell-interface=python < tools/repoint_studio_links_to_native.py
    SSC_WRITE=1 odoo-bin shell --no-http < tools/repoint_studio_links_to_native.py

account.move carries x_studio_salary_batch, x_studio_advance_salary,
x_studio_leave_allowance and x_studio_eos: the journal entry naming the payroll
record it came from. Delete the Studio models and those links are dropped with
them - the field goes off the form and the entry stops saying where it came
from, on documents nobody re-reads.

Every one of those Studio models has been mirrored onto ours, and the mirror
records which row it came from in studio_ref_id. So the link does not have to be
lost: the field stays exactly where it is, on the same form, under the same
label, and is pointed at the native record instead.

This is the same operation the employee repoint does, one field at a time: drop
the foreign key, translate the ids through the mirror, change what the field
says it points at, put the foreign key back against the native table.

Only many2one fields, and by default only on models a module declares -
account.move, account.payment - because a Studio model holding one of these
links is either going itself or is a decision of its own. SSC_ALL=1 widens it.
A one2many is the inverse of somebody else's many2one and has no column of its
own; a many2many keeps its ids in a table of its own. Both are reported and left,
because neither is what account.move is holding.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'
BATCH = 500

# Studio model -> ours. The mirrors ssc_payroll installs, and nothing else: a
# link can only be carried where the record itself was carried.
# x_employeeslist is deliberately not here. The employee links go to
# hr.employee, not to ssc.employee, and that is the employee migration's job -
# doing it here as well would point half the database at the wrong side of the
# same person.
MIRRORS = {
    'x_advance_salaries': 'ssc.advance',
    'x_staff_loan': 'ssc.staff.loan',
    'x_leave_expenses': 'ssc.leave.expense',
    'x_fines_deductions': 'ssc.fine',
    'x_end_of_service': 'ssc.end.of.service',
    'x_on_hold_amounts': 'ssc.on.hold',
    'x_attendance_per_month': 'ssc.attendance.sheet',
    'x_salary_batches': 'ssc.salary.batch',
    'x_all_payslips': 'ssc.payslip',
    'x_staff_payslips': 'ssc.payslip',
    'x_attachments_list': 'ssc.attachment',
}

cr = env.cr                                                      # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821


def title(text):
    print("\n" + "=" * 92)
    print(text)
    print("=" * 92)


def table_exists(table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


def id_map(native_model):
    """studio row id -> our id, for one mirror."""
    Native = env.get(native_model)                               # noqa: F821
    if Native is None or 'studio_ref_id' not in Native._fields:
        return None
    cr.execute("""SELECT studio_ref_id, MIN(id) FROM "%s"
                   WHERE studio_ref_id IS NOT NULL
                GROUP BY studio_ref_id""" % Native._table)
    return {row[0]: row[1] for row in cr.fetchall()}


title("1. links into a mirrored Studio model, from models that stay")

plans, skipped = [], []
for field in IrField.search([('relation', 'in', list(MIRRORS))]):
    if field.model in MIRRORS:
        continue                          # inside the family, going anyway
    # Only the models a module declares. A Studio model holding one of these
    # links is either going itself or will be looked at on its own; translating
    # half a million rows in tables that are about to be deleted is work that
    # buys nothing and can only go wrong. SSC_ALL=1 to include them.
    if field.model.startswith('x_') and os.environ.get('SSC_ALL') != '1':
        skipped.append((field, MIRRORS[field.relation], 'a Studio model itself'))
        continue
    native = MIRRORS[field.relation]
    if field.ttype != 'many2one':
        skipped.append((field, native, field.ttype))
        continue
    Model = env.get(field.model)                                 # noqa: F821
    if Model is None or not table_exists(Model._table) \
            or not column_exists(Model._table, field.name):
        skipped.append((field, native, 'no column'))
        continue
    table = Model._table
    cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL' % (table, field.name))
    held = cr.fetchone()[0]
    mapping = id_map(native)
    if mapping is None:
        skipped.append((field, native, 'no studio_ref_id on ours'))
        continue
    cr.execute('SELECT DISTINCT "%s" FROM "%s" WHERE "%s" IS NOT NULL'
               % (field.name, table, field.name))
    values = [row[0] for row in cr.fetchall()]
    unmapped = [v for v in values if v not in mapping]
    plans.append((field, native, table, held, mapping, unmapped))

print("  %-30s %-42s %-22s %7s %s"
      % ('model', 'field', 'becomes', 'rows', 'unmapped'))
for field, native, _table, held, _mapping, unmapped in sorted(
        plans, key=lambda p: -p[3]):
    print("  %-30s %-42s %-22s %7s %s"
          % (field.model, field.name, native, held,
             len(unmapped) or ''))
print("\n  %s field(s), %s row(s) that keep their link"
      % (len(plans), sum(p[3] for p in plans)))

if skipped:
    title("2. left alone")
    for field, native, why in skipped:
        print("  %-30s %-42s %-22s %s" % (field.model, field.name, native, why))
    print("""
  A one2many is the inverse of somebody else's many2one and has no column to
  translate; a many2many keeps its ids in a table of its own. Neither is what
  the accounting entries are holding, so neither is guessed at here.""")

unmapped_any = [(f, u) for f, _n, _t, _h, _m, u in plans if u]
if unmapped_any:
    title("3. values naming a Studio row that has no mirror")
    for field, unmapped in unmapped_any:
        print("  %-30s %-42s %s: %s"
              % (field.model, field.name, len(unmapped), sorted(unmapped)[:8]))
    print("""
  These are set to nothing rather than left pointing at a row that will not
  exist. The alternative is a foreign key that cannot be created and a column
  full of ids naming a deleted table.""")

if DRY_RUN:
    print("\n" + "=" * 92)
    print("  DRY RUN - nothing changed. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


title("4. repointing")

for field, native, table, held, mapping, unmapped in plans:
    column = field.name
    Native = env[native]                                         # noqa: F821
    label = '%s.%s' % (field.model, column)
    try:
        with cr.savepoint():
            # the foreign key first: it names the old table
            cr.execute("""SELECT con.conname
                            FROM pg_constraint con
                            JOIN pg_class rel ON rel.oid = con.conrelid
                            JOIN pg_attribute att
                              ON att.attrelid = con.conrelid
                             AND att.attnum = con.conkey[1]
                           WHERE con.contype = 'f'
                             AND rel.relname = %s
                             AND att.attname = %s""", (table, column))
            for (name,) in cr.fetchall():
                cr.execute('ALTER TABLE "%s" DROP CONSTRAINT "%s"' % (table, name))

            if unmapped:
                cr.execute('UPDATE "%s" SET "%s" = NULL WHERE "%s" IN %%s'
                           % (table, column, column), (tuple(unmapped),))

            pairs = sorted(mapping.items())
            for start in range(0, len(pairs), BATCH):
                chunk = pairs[start:start + BATCH]
                values = ', '.join(cr.mogrify('(%s,%s)', pair).decode()
                                   for pair in chunk)
                cr.execute('UPDATE "%s" t SET "%s" = m.new '
                           'FROM (VALUES %s) AS m(old, new) '
                           'WHERE t."%s" = m.old'
                           % (table, column, values, column))

            cr.execute("""UPDATE ir_model_fields SET relation = %s
                           WHERE model = %s AND name = %s""",
                       (native, field.model, column))

            cr.execute('ALTER TABLE "%s" ADD CONSTRAINT "%s_%s_fkey" '
                       'FOREIGN KEY ("%s") REFERENCES "%s"(id) '
                       'ON DELETE SET NULL NOT VALID'
                       % (table, table[:40], column[:24], column, Native._table))
            cr.execute('ALTER TABLE "%s" VALIDATE CONSTRAINT "%s_%s_fkey"'
                       % (table, table[:40], column[:24]))
        print("  > %-58s %s row(s) -> %s" % (label, held, native))
    except Exception as exc:
        print("  ! %-58s %s" % (label, str(exc).strip().splitlines()[0][:60]))

cr.commit()

title("summary")
print("""  The fields are where they were, on the same forms, under the same labels.
  What they open is our record now.

  Restart before checking - a field's comodel is read when the registry is
  built - and then open a journal entry that had one and click through.""")
