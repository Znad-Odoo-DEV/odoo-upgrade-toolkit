"""Cancel the notification mail the migrations queued up.

    odoo-bin shell -d <database> --no-http < tools/cancel_stale_notifications.py
    SSC_APPLY=1 odoo-bin shell -d <database> --no-http < tools/cancel_stale_notifications.py

Approving a leave tells Odoo to write to the person it belongs to. That is the
right behaviour for a request somebody files tomorrow and the wrong behaviour
for a hundred and sixty absences that finished months ago, and the server said
so itself: daily email limit exceeded, retry later. Retrying is exactly what a
queued mail does, once an hour, until somebody stops it.

So the queue is emptied of anything the migrations put there. Cancelled, not
deleted - the record stays and says it was cancelled, which is a truer account
than a row that vanished.

Only mail still trying to go out is touched. Anything already sent is history
and nothing here can reach it. Mail belonging to models the migrations never
wrote to is listed and left alone, because a stuck invoice is somebody's
problem and not this script's business.
"""
import os
from collections import Counter

APPLY = os.environ.get('SSC_APPLY') == '1'

# what the migrations wrote to, and therefore what they notified about
OURS = ['hr.leave', 'hr.leave.allocation']

# Anything else has to be named on the command line. A leave migration has no
# standing to decide that somebody's purchase notifications are worthless:
#
#     SSC_ALSO=x_items_ordered odoo-bin shell ...
#
OURS += [name.strip() for name in os.environ.get('SSC_ALSO', '').split(',')
         if name.strip()]

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
Mail = env['mail.mail'].sudo()


def title(text):
    print("\n" + "=" * 84)
    print(text)
    print("=" * 84)


queued = Mail.search([('state', 'in', ('outgoing', 'exception'))])

title("what is sitting in the queue")
print(f"  {len(queued)} mail(s) still trying to go out\n")
by_model = Counter(mail.model or '(none)' for mail in queued)
for model, number in by_model.most_common():
    mark = "ours" if model in OURS else ""
    print(f"  {model:<34} {number:>5}   {mark}")

ours = queued.filtered(lambda m: m.model in OURS)
theirs = queued - ours

title("to cancel")
print(f"  {len(ours)} mail(s)")
print()
for model in OURS:
    group = ours.filtered(lambda m: m.model == model)
    if not group:
        continue
    dates = sorted(str(m.create_date)[:10] for m in group)
    print(f"  {model:<26} {len(group):>5}   oldest {dates[0]}   newest {dates[-1]}")
print()
for mail in ours[:8]:
    print(f"      {str(mail.create_date)[:16]}  {(mail.subject or '')[:62]}")
if len(ours) > 8:
    print(f"      ... and {len(ours) - 8} more")

if theirs:
    title("left alone - nothing to do with the migrations")
    for model, number in Counter(m.model or '(none)' for m in theirs).most_common():
        print(f"  {model:<34} {number:>5}")
    print("\n  If these are stuck too it is the same daily limit, and they will")
    print("  go out on their own once it resets. A person should look before")
    print("  anything cancels them.")

if APPLY:
    ours.write({'state': 'cancel', 'failure_reason': 'Historic data migration'})
    env.cr.commit()
    title("APPLIED")
    print(f"  {len(ours)} mail(s) cancelled")
    print(f"  {len(theirs)} left in the queue")
else:
    env.cr.rollback()
    title("DRY RUN - nothing written")
    print("  Re-run with SSC_APPLY=1 to cancel.")
