"""Move the payslip chatter onto our payslips, so the trail outlives the model.

    SSC_WRITE=1 odoo-bin shell --no-http < tools/move_payslip_chatter.py

A message is not attached to a record the way a line is. It carries the model's
name and the record's id in two ordinary columns, which is why it survives
nothing: delete x_all_payslips and 4,584 messages are left pointing at a model
that is not there, invisible in every interface and dead weight in the table.

So they are repointed rather than copied - the same message, the same author,
the same date, the same body, now naming ssc.payslip and the payslip we made
from that row. Nothing is rewritten except where it lives.

The id map is studio_ref_id, which is the same map everything else in this
migration ran on. A message whose payslip never came across is left alone and
counted: repointing it at nothing would be worse than leaving it where it is.

Followers move with them. An approval read by somebody who was following the
record is only half a trail if the following is gone.
"""
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'
BATCH = 2000

SOURCE = 'x_all_payslips'
TARGET = 'ssc.payslip'

cr = env.cr                                                      # noqa: F821
Slip = env[TARGET].sudo().with_context(active_test=False)        # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# --- the map ------------------------------------------------------------------

id_map = {}
for slip in Slip.search([('studio_ref_id', '!=', False)]):
    id_map[slip.studio_ref_id] = slip.id

title("1. what is there")

print("  %s payslip(s) carry a Studio reference" % len(id_map))

for table, label in (('mail_message', 'messages'),
                     ('mail_followers', 'followers'),
                     ('mail_activity', 'activities')):
    cr.execute("""SELECT to_regclass(%s)""", (table,))
    if not cr.fetchone()[0]:
        continue
    column = 'model' if table == 'mail_message' else 'res_model'
    cr.execute('SELECT COUNT(*), COUNT(*) FILTER (WHERE res_id = ANY(%%s)) '
               '  FROM "%s" WHERE "%s" = %%s' % (table, column),
               (list(id_map), SOURCE))
    total, movable = cr.fetchone()
    print("  %-12s %6s on %s   %s can be moved, %s point at a payslip we do not have"
          % (label, total, SOURCE, movable, total - movable))

cr.execute("SELECT COUNT(*) FROM mail_message WHERE model = %s", (TARGET,))
print("\n  %s message(s) already on %s" % (cr.fetchone()[0], TARGET))

# What one of them actually says, because "4,584 messages" is not a description.
cr.execute("""SELECT id, res_id, message_type, subject, body, date
                FROM mail_message WHERE model = %s ORDER BY id DESC LIMIT 3""",
           (SOURCE,))
print("\n  the most recent three, as they read:")
for message_id, res_id, kind, subject, body, when in cr.fetchall():
    text = (body or '')
    for tag in ('<p>', '</p>', '<br>', '<br/>', '<span>', '</span>'):
        text = text.replace(tag, ' ')
    text = ' '.join(text.split())[:90]
    print("      %-8s record %-8s %-14s %s" % (message_id, res_id, kind, when))
    print("        %s" % (subject or ''))
    print("        %s" % text)

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing moved. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- move ---------------------------------------------------------------------

title("2. moving")

old_ids = list(id_map)
new_ids = [id_map[k] for k in old_ids]

for table, column, label in (('mail_message', 'model', 'messages'),
                             ('mail_followers', 'res_model', 'followers'),
                             ('mail_activity', 'res_model', 'activities')):
    cr.execute("SELECT to_regclass(%s)", (table,))
    if not cr.fetchone()[0]:
        continue
    moved = 0
    while True:
        cr.execute(
            'UPDATE "%s" AS t SET "%s" = %%s, res_id = m.new_id'
            '  FROM (SELECT * FROM unnest(%%s::int[], %%s::int[])'
            '        AS x(old_id, new_id)) AS m'
            ' WHERE t.id IN (SELECT id FROM "%s" WHERE "%s" = %%s'
            '                  AND res_id = ANY(%%s) LIMIT %%s)'
            '   AND t.res_id = m.old_id'
            % (table, column, table, column),
            (TARGET, old_ids, new_ids, SOURCE, old_ids, BATCH))
        if not cr.rowcount:
            break
        moved += cr.rowcount
        cr.commit()
        print("  %-12s %s" % (label, moved))
    if not moved:
        print("  %-12s nothing to move" % label)

# mail.activity also keeps the model as a link, not only as a name.
cr.execute("SELECT to_regclass('mail_activity')")
if cr.fetchone()[0]:
    cr.execute("SELECT id FROM ir_model WHERE model = %s", (TARGET,))
    row = cr.fetchone()
    if row:
        cr.execute("""UPDATE mail_activity SET res_model_id = %s
                       WHERE res_model = %s""", (row[0], TARGET))
        cr.commit()

# --- after --------------------------------------------------------------------

title("3. after")

for table, column, label in (('mail_message', 'model', 'messages'),
                             ('mail_followers', 'res_model', 'followers'),
                             ('mail_activity', 'res_model', 'activities')):
    cr.execute("SELECT to_regclass(%s)", (table,))
    if not cr.fetchone()[0]:
        continue
    cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" = %%s' % (table, column), (SOURCE,))
    left = cr.fetchone()[0]
    cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" = %%s' % (table, column), (TARGET,))
    here = cr.fetchone()[0]
    print("  %-12s %6s still on %s   %6s on %s" % (label, left, SOURCE, here, TARGET))

title("summary")
print("""  What is left on %s belongs to the payslips that never came across - the
  nineteen naming no employee. They go with the model, and there is nothing
  else they could have gone to.

  Open a payslip and read its chatter before trusting this: a message that
  moved but renders empty is worse than one that did not move.""" % SOURCE)
