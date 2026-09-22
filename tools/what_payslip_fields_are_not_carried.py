"""Everything on the Studio payslip that ssc.payslip does not carry.

    odoo-bin shell --no-http --shell-interface=python < tools/what_payslip_fields_are_not_carried.py

Reads only. The mirror was built to carry the money, and it carries it exactly:
four figures on 4,565 records with no difference at all. It was never built to
carry the rest, because the Studio master was going to stay.

It is not staying. So everything else on that record has to come across too -
who approved it and when, what state it is in, the chatter around it, and the
attachments with their own details rather than a name and a value.

This lists what is there, what is already carried, and what is not, with the
number of rows that actually hold a value in each - because a field nobody ever
filled is not work, and a field 4,000 rows hold is not optional. The line models
underneath are listed the same way, and the chatter counted.

Nothing is decided here. The next thing to write is the list of fields to add to
ssc.payslip, and this is what it should be written from.
"""
SOURCE = 'x_all_payslips'

# What _studio_payslip_vals reads today, and the two line sets it walks.
CARRIED = {
    'x_studio_employee_id', 'x_studio_employee', 'x_studio_batch',
    'x_studio_attendance_sheet', 'x_studio_from_date', 'x_studio_to_date',
    'x_studio_days', 'x_studio_month', 'x_studio_year', 'x_studio_cash',
    'x_studio_staff_1', 'x_studio_designation', 'x_studio_basic_salary',
    'x_studio_house_allowance', 'x_studio_travelling_allownce',
    'x_studio_other_allowances', 'x_studio_total_gross_salary',
    'x_studio_overtime_hr_on_reg_days', 'x_studio_overtime_hr_on_off_days',
    'x_studio_total_attendance_for_this_month_1',
    'x_studio_overtime_reg', 'x_studio_overtime_off',
    'x_studio_total_salary_of_this_month',
    'x_studio_total_overtime_salary_of_this_month',
    'x_studio_salary_adjustment', 'x_studio_net_amount',
    'x_studio_salary_attachments', 'x_studio_projectsss_sum',
}

# Odoo's own plumbing: present on every model, carried by being ours already.
PLUMBING = {
    'id', 'create_uid', 'create_date', 'write_uid', 'write_date',
    'display_name', '__last_update', 'message_ids', 'message_follower_ids',
    'message_partner_ids', 'website_message_ids', 'rating_ids',
    'activity_ids', 'activity_state', 'activity_user_id', 'activity_type_id',
    'activity_type_icon', 'activity_date_deadline', 'my_activity_date_deadline',
    'activity_summary', 'activity_exception_decoration', 'has_message',
    'activity_exception_icon', 'activity_calendar_event_id',
    'message_is_follower', 'message_has_error', 'message_has_error_counter',
    'message_needaction', 'message_needaction_counter', 'message_attachment_count',
    'message_has_sms_error', 'rating_last_value', 'rating_avg', 'rating_count',
    'rating_avg_text', 'rating_last_feedback', 'rating_last_image',
    'rating_percentage_satisfaction', 'rating_last_text',
}

cr = env.cr                                                      # noqa: F821
Source = env[SOURCE].sudo().with_context(active_test=False)      # noqa: F821
Slip = env['ssc.payslip']                                        # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def column_exists(table, column):
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = %s AND column_name = %s""", (table, column))
    return bool(cr.fetchone())


def filled(table, column):
    if not column_exists(table, column):
        return None
    cr.execute('SELECT COUNT(*) FROM "%s" WHERE "%s" IS NOT NULL' % (table, column))
    return cr.fetchone()[0]


rows = Source.search_count([])

title("0. the record")
print("  %s row(s) on %s" % (rows, SOURCE))
print("  %s field(s) declared on it" % len(Source._fields))
print("  %s payslip(s) on ssc.payslip" % Slip.sudo().search_count([]))


# --- 1. not carried -----------------------------------------------------------

title("1. what is not carried, and how much of it is filled")

table = Source._table
missing = []
for name, field in Source._fields.items():
    if name in PLUMBING or name in CARRIED:
        continue
    count = filled(table, name)
    missing.append((name, field, count))

# The ones holding something come first: that is the order the work is in.
missing.sort(key=lambda m: (-(m[2] or 0), m[0]))
for name, field, count in missing:
    if count is None:
        continue
    label = field.string or ''
    extra = ''
    if field.type in ('many2one', 'many2many', 'one2many'):
        extra = '-> %s' % field.comodel_name
    print("  %-46s %-11s %5s  %-24s %s"
          % (name[:46], field.type, count, label[:24], extra))

nothing = [m for m in missing if m[2] == 0]
relational = [m for m in missing if m[2] is None]
print("\n  %s field(s) not carried" % len(missing))
print("  %s of them are filled on at least one row" % len([m for m in missing if m[2]]))
print("  %s are empty on every row" % len(nothing))
print("  %s have no column - one2many and computed" % len(relational))

if relational:
    print("\n  the ones with no column of their own:")
    for name, field, _c in relational:
        extra = getattr(field, 'comodel_name', '') or ''
        print("      %-46s %-11s %s" % (name[:46], field.type, extra))


# --- 2. the lines underneath --------------------------------------------------

title("2. the line models it owns")

for name, field in sorted(Source._fields.items()):
    if field.type != 'one2many':
        continue
    Child = env.get(field.comodel_name)                          # noqa: F821
    if Child is None:
        continue
    cr.execute('SELECT COUNT(*) FROM "%s"' % Child._table)
    total = cr.fetchone()[0]
    print("\n  %s   ->   %s   %s row(s)   %s"
          % (name, field.comodel_name, total,
             'CARRIED' if name in CARRIED else 'not carried'))
    for sub_name, sub in sorted(Child._fields.items()):
        if sub_name in PLUMBING or sub_name.startswith('x_studio_sequence'):
            continue
        count = filled(Child._table, sub_name)
        if count is None or not count:
            continue
        extra = ('-> %s' % sub.comodel_name) if sub.type in (
            'many2one', 'many2many', 'one2many') else ''
        print("      %-40s %-11s %5s  %-20s %s"
              % (sub_name[:40], sub.type, count, (sub.string or '')[:20], extra))


# --- 3. the conversation ------------------------------------------------------

title("3. the chatter")

Message = env['mail.message'].sudo()                             # noqa: F821
messages = Message.search_count([('model', '=', SOURCE)])
tracking = Message.search_count([('model', '=', SOURCE),
                                 ('message_type', '=', 'notification')])
print("  %s message(s) on %s" % (messages, SOURCE))
print("      %s of them are tracked field changes" % tracking)
print("  %s message(s) on ssc.payslip" % Message.search_count([('model', '=', 'ssc.payslip')]))

Attachment = env['ir.attachment'].sudo()                         # noqa: F821
print("  %s file attachment(s) on %s"
      % (Attachment.search_count([('res_model', '=', SOURCE)]), SOURCE))


title("what to do with this")
print("""  Everything in section 1 with a number beside it is a fact the Studio payslip
  holds and ours does not. The approvals and their dates are in there, under
  whatever Studio called them, and they are the reason this list was asked for.

  Section 2 is the detail on the attachment and project lines: the mirror
  carries a name, a value and a type today, and the rest of those columns is
  what "with all the details" means.

  Section 3 is the history - who changed what and when - which does not move by
  copying fields and needs the messages themselves repointed.""")
