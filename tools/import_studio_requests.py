"""Carry x_all_requests onto ssc.request, with its lines and its history.

    odoo-bin shell --no-http --shell-interface=python < tools/import_studio_requests.py
    SSC_WRITE=1 odoo-bin shell --no-http < tools/import_studio_requests.py
    SSC_CHUNK=200   how many to commit at a time (default 200)

Idempotent: keyed on studio_ref_id, so running it again picks up what is new
and touches nothing else.

Two things it deliberately does not do:

  It does not call action_approve. An approved request produces a leave
  allowance, an advance or a settlement, and every one of those already exists -
  ssc_payroll has been mirroring them for months. Calling the approval on
  import would make nine hundred duplicates. The state is written as data,
  because that is what it is: a fact about the past, not an event happening now.

  It does not assign new numbers. The number a request already has is the
  number on the paper somebody signed. The sequences are moved up afterwards so
  the next new request carries on from the highest one carried across, rather
  than starting at 1 and colliding.

The status is taken from x_studio_status, the S1..S6 one, and not from the other
status field. There were two, both filled, and the other one holds a mixture of
'status3' and free text - it is the one that was edited by hand when a rule went
wrong.
"""
import os
import re

DRY_RUN = os.environ.get('SSC_WRITE') != '1'
CHUNK = int(os.environ.get('SSC_CHUNK') or 200)

SOURCE = 'x_all_requests'
MATERIAL_LINES = 'x_all_requests_line_1eb41'
INSTALLMENT_LINES = 'x_all_requests_line_acb74'

cr = env.cr                                                      # noqa: F821
Request = env['ssc.request'].sudo().with_context(                # noqa: F821
    active_test=False, tracking_disable=True,
    mail_create_nolog=True, mail_create_nosubscribe=True)
Type = env['ssc.request.type'].sudo()                            # noqa: F821
Source = env.get(SOURCE)                                         # noqa: F821

if Source is None:
    raise SystemExit("%s is not in this database." % SOURCE)
Source = Source.sudo().with_context(active_test=False)


def title(text):
    print("\n" + "=" * 90)
    print(text)
    print("=" * 90)


def g(record, name, default=False):
    """Read a Studio field that may not exist on this database."""
    if not record or name not in record._fields:
        return default
    value = record[name]
    return value if value is not False and value is not None else default


# The clean status field. S1..S6, one meaning each.
STATE = {
    'S1': 'draft',
    'S2': 'pe_review',
    'S3': 'hr_review',
    'S4': 'to_approve',
    'S5': 'approved',
    'S6': 'rejected',
}

LEAVE_TYPE = {'Local Leave': 'local', 'Overseas Leave': 'overseas'}
REPAYMENT = {'Salary Deduction': 'salary', 'Paid Separately': 'separately',
             'Paid separately': 'separately'}


# ---------------------------------------------------------------- employees
def employee_of(studio_employee):
    """The hr.employee behind a Studio employee, whichever way it points.

    Before the employee repoint, x_studio_requested_for is an x_employeeslist.
    After it, the same field is an hr.employee. Both are answered here so this
    can be run on either side of that migration.
    """
    if not studio_employee:
        return False
    if studio_employee._name == 'hr.employee':
        return studio_employee.id
    mirror = env['ssc.employee'].sudo().with_context(             # noqa: F821
        active_test=False).search(
        [('studio_ref_id', '=', studio_employee.id)], limit=1)
    if mirror and mirror.hr_employee_id:
        return mirror.hr_employee_id.id
    return False


types = {t.code: t for t in Type.search([])}
if not types:
    raise SystemExit("No request types are installed. Install ssc_requests first.")


# the fields the bridge module (ssc_requests_payroll) adds. auto_install, so
# it is there whenever payroll is - but the first pass on test_2 ran before it
# was carried onto the tree, and wrote 1,150 requests without a single leave
# date, ticket, resignation reason or repayment method. Section 2b finds the
# carried requests whose bridge fields are all still empty and fills them in.
def bridge_values(record):
    ticket_amount = (g(record, 'x_studio_quotation_amount', 0.0)
                     or g(record, 'x_studio_reimbursement_amount', 0.0))
    return {
        'leave_type': LEAVE_TYPE.get(g(record, 'x_studio_leave_type')),
        'is_paid_leave': g(record, 'x_studio_paid_leave_1') == 'Paid Leave',
        'last_day_of_duty': g(record, 'x_studio_last_day_of_duty') or False,
        'first_day_of_leave': g(record, 'x_studio_first_day_of_leave') or False,
        'last_day_of_leave': g(record, 'x_studio_last_day_of_leave') or False,
        'next_day_of_duty': g(record, 'x_studio_next_day_of_duty_1') or False,
        'leave_days': g(record, 'x_studio_total_days_of_leave', 0),
        'leave_salaries_count': g(
            record, 'x_studio_how_many_leave_salaries_will_be_given', 0),
        'leave_allowance_amount': g(record, 'x_studio_total_amount_to_be_paid', 0.0),
        'ticket_provided': bool(g(record, 'x_studio_ticket')),
        'ticket_reimbursed': bool(g(record, 'x_studio_ticket_reimbursement')),
        'ticket_amount': ticket_amount,
        'airport_destination': g(record, 'x_studio_airport_destination') or False,
        'city_country': g(record, 'x_studio_city_country') or False,
        'contact_name': g(record, 'x_studio_contact_name') or False,
        'contact_phone': g(record, 'x_studio_contact_phone_no') or False,
        'leave_reason': g(record, 'x_studio_reason_of_leave') or False,
        'hold_500': bool(g(record, 'x_studio_hold_500aed')),
        'resignation_reason': g(record, 'x_studio_reason_of_resigning') or False,
        'end_of_service_date': g(record, 'x_studio_last_day_of_duty_1') or False,
        'hr_note': g(record, 'x_studio_hr_review') or False,
        'advance_reason': g(record, 'x_studio_advance_reason') or False,
        'repayment_method': REPAYMENT.get(
            g(record, 'x_studio_type_of_repayment'), 'salary'),
        'supporting_notes': g(record, 'x_studio_other_supporting_notes') or False,
    }


BRIDGE_EMPTY = ('leave_type', 'first_day_of_leave', 'resignation_reason',
                'advance_reason', 'leave_reason', 'end_of_service_date')


def bridge_is_empty(request):
    return not any(request[name] for name in BRIDGE_EMPTY)


title("1. what is there and what is already carried")

rows = Source.search([], order='id')
done = set(Request.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
todo = rows.filtered(lambda r: r.id not in done)

print("  %s request(s) in Studio" % len(rows))
print("  %s already carried" % (len(rows) - len(todo)))
print("  %s to carry" % len(todo))

by_type, no_type, no_employee = {}, [], []
for record in todo:
    code = g(record, 'x_studio_type_of_request_1')
    if not code or code not in types:
        no_type.append((record, code))
        continue
    by_type.setdefault(code, []).append(record)

print("\n  %-8s %-34s %s" % ('code', 'type', 'to carry'))
for code in sorted(by_type, key=lambda c: -len(by_type[c])):
    print("  %-8s %-34s %s" % (code, types[code].name, len(by_type[code])))
if no_type:
    seen = {}
    for record, code in no_type:
        seen.setdefault(code or '(none)', 0)
        seen[code or '(none)'] += 1
    print("\n  %s name a type that is not installed, and are skipped:" % len(no_type))
    for code, count in sorted(seen.items(), key=lambda kv: -kv[1]):
        print("      %-10s %s" % (code, count))


title("2. the status they carry")

counts = {}
for record in todo:
    counts.setdefault(g(record, 'x_studio_status') or '(empty)', 0)
    counts[g(record, 'x_studio_status') or '(empty)'] += 1
for value, count in sorted(counts.items(), key=lambda kv: -kv[1]):
    print("  %-10s %-24s %s" % (value, STATE.get(value, 'DRAFT (unknown)'), count))
print("""
  An approved request is written as approved and nothing is produced from it:
  its allowance, advance or settlement already exists on our side. Approving
  them here would make nine hundred duplicates.""")


title("2b. carried before the bridge module was there")
refill = []
if 'leave_type' in Request._fields:
    by_ref = {r.id: r for r in rows}
    for request in Request.search([('studio_ref_id', 'in', list(done))]):
        record = by_ref.get(request.studio_ref_id)
        if record is None or not bridge_is_empty(request):
            continue
        fresh = bridge_values(record)
        if (any(fresh[name] for name in BRIDGE_EMPTY) or fresh.get('leave_allowance_amount')
                or fresh.get('ticket_amount') or fresh.get('repayment_method') != 'salary'):
            refill.append((request, fresh))
    print("  %s carried request(s) have every bridge field empty while Studio has a value;"
          " they get the leave, ticket, resignation and repayment facts written in" % len(refill))
else:
    print("  ssc_requests_payroll is not installed here, so there is nothing to fill in")

if DRY_RUN:
    print("\n" + "=" * 90)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# ---------------------------------------------------------------- the values
DUPLICATES = []


def request_values(record, code):
    company = g(record, 'x_studio_company') or g(record, 'x_studio_company_id')
    number = g(record, 'x_studio_request_id_1') or g(record, 'x_name') or ''
    revision = g(record, 'x_studio_no_rev', 0) or 0
    name = str(number)
    if revision and not name.endswith('-R%s' % revision):
        name = "%s-R%s" % (name, revision)

    approval = g(record, 'x_studio_approval_date_1')
    ticket_amount = (g(record, 'x_studio_quotation_amount', 0.0)
                     or g(record, 'x_studio_reimbursement_amount', 0.0))

    # Studio issued the same number twice on forty-three of these. Both are
    # real, so both are carried and the second says so in its number rather
    # than being dropped or overwriting the first. A number that is not unique
    # is a fact about the old system, and losing the request is a worse answer
    # to it than marking it.
    if name:
        base, suffix = name, 1
        here = company.id if company else env.company.id           # noqa: F821
        while Request.search_count([('name', '=', name), ('company_id', '=', here)]):
            suffix += 1
            name = "%s (%s)" % (base, suffix)
        if suffix > 1:
            DUPLICATES.append((record.id, base, name))

    values = {
        'studio_ref_id': record.id,
        'name': name or False,
        'reference': str(number) or False,
        'revision': revision,
        'description': (g(record, 'x_name') or name or 'Request')[:255],
        'request_type_id': types[code].id,
        'company_id': company.id if company else env.company.id,   # noqa: F821
        'project_id': (g(record, 'x_studio_which_project_') or
                       env['project.project'].browse([])).id or False,  # noqa: F821
        'employee_id': employee_of(g(record, 'x_studio_requested_for')),
        'requested_by_id': (g(record, 'x_studio_requested_by_1') or
                            env['res.users'].browse([])).id or False,  # noqa: F821
        'date_request': g(record, 'x_studio_date_of_request') or False,
        'state': STATE.get(g(record, 'x_studio_status'), 'draft'),
        'active': bool(g(record, 'x_active', True)),

        'pe_reviewer_id': (g(record, 'x_studio_approved_by') or
                           env['res.users'].browse([])).id or False,   # noqa: F821
        'pe_review_date': g(record, 'x_studio_approval_date') or False,
        'approver_id': (g(record, 'x_studio_approved_by_1') or
                        env['res.users'].browse([])).id or False,      # noqa: F821
        'approval_date': approval or False,
        'rejected_by_id': (g(record, 'x_studio_rejected_by') or
                           env['res.users'].browse([])).id or False,   # noqa: F821
        'notes': g(record, 'x_studio_notes_1') or g(record, 'x_studio_notes') or False,

        'amount': g(record, 'x_studio_amount_needed_1', 0.0),
        'installment_count': g(record, 'x_studio_on_how_many_installments', 0) or 1,
    }

    if 'leave_type' in Request._fields:
        values.update(bridge_values(record))
    return values


title("3. carrying them")

Material = env.get(MATERIAL_LINES)                               # noqa: F821
Installment = env.get(INSTALLMENT_LINES)                         # noqa: F821
Line = env['ssc.request.material.line'].sudo()                   # noqa: F821
Repay = env['ssc.request.installment'].sudo()                    # noqa: F821

wanted = [record for group in by_type.values() for record in group]
wanted.sort(key=lambda r: r.id)

carried, refused = 0, []
for start in range(0, len(wanted), CHUNK):
    batch = wanted[start:start + CHUNK]
    for record in batch:
        code = g(record, 'x_studio_type_of_request_1')
        try:
            with cr.savepoint():
                Request.create(request_values(record, code))
        except Exception as exc:
            refused.append((record.id, str(exc).strip().splitlines()[0][:90]))
            continue
        carried += 1
    cr.commit()
    print("  %s / %s" % (carried, len(wanted)))

if refill:
    filled = 0
    for start in range(0, len(refill), CHUNK):
        for request, fresh in refill[start:start + CHUNK]:
            with cr.savepoint():
                request.with_context(tracking_disable=True, mail_notrack=True).write(fresh)
            filled += 1
        cr.commit()
    print("  %s carried request(s) filled in with the bridge fields" % filled)

if DUPLICATES:
    print("")
    print("  %s carried under a number Studio had already issued:" % len(DUPLICATES))
    for ref_id, base, given in DUPLICATES[:12]:
        print("      studio %-8s %-30s -> %s" % (ref_id, base, given))
    if len(DUPLICATES) > 12:
        print("      ... and %s more" % (len(DUPLICATES) - 12))

if refused:
    print("\n  %s refused:" % len(refused))
    seen = {}
    for ref_id, message in refused:
        seen.setdefault(message, []).append(ref_id)
    for message, ids in sorted(seen.items(), key=lambda kv: -len(kv[1])):
        print("      %4s  %s" % (len(ids), message))
        print("            %s" % sorted(ids)[:8])


title("4. the lines")

carried_map = {r.studio_ref_id: r for r in Request.search(
    [('studio_ref_id', '!=', False)])}

made = 0
if Material is not None:
    existing = set(Line.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
    for source_line in Material.sudo().with_context(active_test=False).search([]):
        if source_line.id in existing:
            continue
        parent = g(source_line, 'x_all_requests_id')
        request = parent and carried_map.get(parent.id)
        if not request:
            continue                      # an orphan line, or a request not carried
        template = g(source_line, 'x_studio_material_code_1')
        product = template and template.product_variant_id or False
        if not product:
            continue
        try:
            with cr.savepoint():
                Line.create({
                    'request_id': request.id,
                    'studio_ref_id': source_line.id,
                    'item_no': g(source_line, 'x_studio_item_num', 0),
                    'sequence': g(source_line, 'x_studio_sequence', 10) or 10,
                    'product_id': product.id,
                    'description': template.display_name,
                    'quantity': g(source_line, 'x_studio_quantity_required', 0.0),
                    'quantity_project': (
                        g(source_line, 'x_studio_project_quantity_1', 0.0)
                        or g(source_line, 'x_studio_project_quantity', 0.0)),
                    'quantity_sector': (
                        g(source_line, 'x_studio_sector_quantity_1', 0.0)
                        or g(source_line, 'x_studio_sector_quantity', 0.0)),
                })
            made += 1
        except Exception:
            pass
    cr.commit()
print("  %s material line(s)" % made)

made = 0
if Installment is not None:
    existing = set(Repay.search([('studio_ref_id', '!=', False)]).mapped('studio_ref_id'))
    for source_line in Installment.sudo().with_context(active_test=False).search([]):
        if source_line.id in existing:
            continue
        parent = g(source_line, 'x_all_requests_id')
        request = parent and carried_map.get(parent.id)
        if not request:
            continue
        month = g(source_line, 'x_studio_month')
        year = g(source_line, 'x_studio_year')
        if not month or not year:
            continue
        try:
            due = '%s-%02d-01' % (int(year), int(month))
            with cr.savepoint():
                Repay.create({
                    'request_id': request.id,
                    'studio_ref_id': source_line.id,
                    'name': g(source_line, 'x_name') or 'Installment',
                    'due_date': due,
                    'amount': g(source_line, 'x_studio_amount', 0.0),
                })
            made += 1
        except Exception:
            pass
    cr.commit()
print("  %s installment(s)" % made)


title("5. moving the sequences past what was carried")

# A new request must not be handed a number that is already on a piece of paper.
NUMBER = re.compile(r'(\d+)\s*$')
moved = 0
for request_type in Type.search([]):
    carried_here = Request.search([('request_type_id', '=', request_type.id),
                                   ('reference', '!=', False)])
    if not carried_here:
        continue
    if request_type.numbering == 'global':
        highest = 0
        for one in carried_here:
            match = NUMBER.search(one.reference or '')
            highest = max(highest, int(match.group(1)) if match else 0)
        if not highest:
            continue
        # The sequence of a globally numbered type is made on first use, so one
        # that has never numbered anything here has none - and skipping it, as
        # this did, left the counter at one. The next leave request would have
        # been handed ALR/0001, a number on a document somebody signed.
        if not request_type.sequence_id:
            request_type._next_number()
        request_type.sequence_id.sudo().number_next_actual = highest + 1
        moved += 1
        print("  %-6s next number -> %s" % (request_type.code, highest + 1))
        continue
    for project in carried_here.mapped('project_id'):
        theirs = carried_here.filtered(lambda r: r.project_id == project)
        highest = 0
        for one in theirs:
            match = NUMBER.search(one.reference or '')
            highest = max(highest, int(match.group(1)) if match else 0)
        if not highest:
            continue
        row = env['ssc.request.sequence'].sudo()._for(            # noqa: F821
            request_type, theirs[:1].company_id, project)
        row._next()                       # make the sequence if it is not there
        row.sequence_id.sudo().number_next_actual = highest + 1
        moved += 1
        print("  %-6s %-24s next number -> %s"
              % (request_type.code, project.name or '', highest + 1))
cr.commit()
print("\n  %s sequence(s) moved" % moved)


title("after")

print("  %s request(s) on ssc.request, %s of them carried from Studio"
      % (Request.search_count([]), Request.search_count([('studio_ref_id', '!=', False)])))
print("""
  Nothing was approved by this: the states were written as the facts they are.
  What an approved request produces already exists - ssc_payroll has been
  mirroring the allowances, the advances and the settlements for months, and
  those are what the reports read.

  Check a number from last year, and check that a new request of the same type
  gets the next one and not a number somebody already has.""")
