"""The fourteen server actions that still name x_employeeslist: rewritten or retired.

    SSC_WRITE=1 odoo-bin shell --no-http --shell-interface=python < tools/retire_employee_list_actions.py

Every link to the Studio employee list was repointed at hr.employee, every
reader of an attribute that did not move was removed, and what is left is
code: fourteen server actions that call env['x_employeeslist'] by name. Each
one was read, and each one is one of two things.

RETIRED - the action's whole purpose was to maintain something on the Studio
list, and the list is going:

    3325  Check Canceled employee   flags x_studio_cancelled past the end of
                                    service; cancelled employees are archived
                                    in hr.employee, which is the native shape
    1887  Set on leave              flags x_studio_on_leave between two dates;
                                    hr.leave carries the leave itself
    3151  Workers                   fills x_workers from the list; x_workers
                                    is itself being deleted (decided
                                    2026-09-05), so nothing feeds it any more
    1138  1114  1139  2384          keep the per-employee "all CPC" list (the
                                    laptop / vehicle / software a person holds)
                                    on the Studio record; the asset records
                                    still say who holds them through
                                    x_studio_alloc_to, which is an hr.employee

REWRITTEN - the action does something else too, or does something worth
keeping and can do it against hr.employee:

    1062  1136  1137               the previous-owner bookkeeping and the
                                    x_all_assets flag stay; the CPC mirror goes
    1399  Submit ALR to HR          two lines stamped x_studio_datesss on the
                                    employee - the Studio list's private
                                    "today" - and go; the rest is untouched
    1792  monthly performance       the labour list comes from hr.employee
                                    (ssc_is_office_staff, company_id,
                                    contract_date_start, name); the absence
                                    deduction read x_attendance_per_emplo,
                                    deleted on 2026-09-03, so every line starts
                                    at the four days the code already assumed
                                    when no absence record existed
    3608  Add To Date Traker        the cron moves onto hr.employee and reads
                                    visa_expire and work_permit_expiration_date
                                    against the real today (the Studio version
                                    read a per-record date that only a leave
                                    request ever set); passport expiry has no
                                    native field and is not tracked
    1308  Add To HR                 the seven document scans become
                                    ir.attachment rows on the hr.employee found
                                    by registration_number; only binary fields
                                    are copied

The three automations triggered BY the model (150, 151 petty cash, 630 the
payroll mirror) are printed at the end and not touched: they go with the
model, and 150/151 are the next decision.

Dry run by default: the diff of every rewrite, the list of every retirement,
nothing written.
"""
import difflib
import os

DRY_RUN = os.environ.get('SSC_WRITE') != '1'

cr = env.cr                                                      # noqa: F821
Server = env['ir.actions.server'].sudo()                         # noqa: F821
Automation = env['base.automation'].sudo()                       # noqa: F821
# active_test off: the crons on the Studio list are switched off, and a
# search that skips them found nothing to unlink before the action - and the
# FK from ir_cron then refused the action. Cron 92 (Workers) was that.
Cron = env['ir.cron'].sudo().with_context(active_test=False)     # noqa: F821
IrModel = env['ir.model'].sudo()                                 # noqa: F821
IrField = env['ir.model.fields'].sudo()                          # noqa: F821


def title(text):
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


RETIRE = {
    3325: "flags x_studio_cancelled; cancelled employees are archived in hr.employee",
    1887: "flags x_studio_on_leave; hr.leave carries the leave",
    1138: "maintains the CPC list on the Studio record only",
    1114: "maintains the CPC list on the Studio record only",
    1139: "maintains the CPC list on the Studio record only",
    2384: "maintains the CPC list on the Studio record only",
    3151: "fills x_workers, which is itself being deleted",
}

# action id -> (model the action runs on after the change, new code)
REWRITE = {
    1062: ('x_1_1_3_vehicles', """\
prev_employee_name = env['x_1_1_3_vehicles'].browse(record.id).x_studio_previous_owner
employee_name = record.x_studio_allocated_to.name
record.update({'x_studio_previous_owner' : employee_name })
"""),
    1136: ('x_1_1_6_computer_devic', """\
if record.x_studio_type == 'Laptop':
    prev_employee_name = env['x_1_1_6_computer_devic'].browse(record.id).x_studio_previous_owner
    employee_name = record.x_studio_allocated_to.name
    record.update({'x_studio_previous_owner' : employee_name })
"""),
    1137: ('x_1_1_6_computer_devic', """\
if record.x_studio_type == 'Software' and record.x_studio_license_expiry_date :
    related_rec = env['x_all_assets'].search([('x_name', '=', record.x_name)], limit=1)
    if related_rec:
        related_rec.write ({'x_studio_deleted' : True})
"""),
    1792: ('x_monthly_performance', """\
if record.x_studio_start and not record.x_studio_stop and not record.x_studio_submitted and not record.x_studio_submit:
    month_map = {1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN',
                 7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'}
    current_month = record.x_studio_date.month
    current_year = record.x_studio_date.year
    month_name = month_map[current_month]
    new_name = f"{month_name} {current_year}'s Assessment for {record.x_studio_company.name}"
    employees = env['hr.employee'].search([('ssc_is_office_staff', '!=', True), ('company_id', '=', record.x_studio_company.id)])
    attendance_lines = []
    for employee in employees:
        if employee.contract_date_start and record.x_studio_date:
            if employee.contract_date_start < record.x_studio_date:
                # The absence deduction read x_attendance_per_emplo, deleted 2026-09-03.
                # Every line starts at the four days the code assumed when no record existed.
                total_days_present = '4'
                attendance_lines.append((0, 0, {'x_name': employee.name, 'x_studio_employee': employee.id, 'x_studio_attendance': total_days_present}))
    record.write({'x_name': new_name, 'x_studio_assessment': attendance_lines, 'x_studio_stop': True})
elif record.x_studio_start and record.x_studio_stop and not record.x_studio_submitted and record.x_studio_submit:
    month_map = {1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN',
                    7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'}
    current_month = datetime.datetime.now().month
    current_year = datetime.datetime.now().year
    month_name = month_map[current_month]
    name = f"{month_name} {current_year}"
    for employee in record.x_studio_assessment:
        performance = {0: 0, 1: 0.1, 2: 0.2, 3: 0.3, 4: 0.4, 5: 0.5}
        ethics = {0: 0, 1: 0.04, 2: 0.07, 3: 0.1}
        attendance = {0: 0, 1: 0.05, 2: 0.1, 3: 0.15, 4: 0.2}
        comm = {0: 0, 1: 0.02, 2: 0.03, 3: 0.05}
        inci = {0: 0, 1: 0.05, 2: 0.1, 3: 0.15}
        performance_i = int(employee.x_studio_performance)
        ethics_i = int(employee.x_studio_ethics)
        attendance_i = int(employee.x_studio_attendance)
        comm_i = int(employee.x_studio_commitments)
        inci_i = int(employee.x_studio_incidents_warnings)
        total = performance[performance_i] + ethics[ethics_i] + attendance[attendance_i] + comm[comm_i] + inci[inci_i]
        line_kpi = [(0,0, {'x_name' : name, 'x_studio_kpi' : total})]
        rec_check = env['x_kpi_of_workers'].search([('x_name', '=', employee.x_studio_employee.name)], limit=1)
        if not rec_check:
            env['x_kpi_of_workers'].create({'x_name' : employee.x_studio_employee.name, 'x_studio_employee' : employee.x_studio_employee.id, 'x_studio_previous_months' : line_kpi})
        else:
            line_check = rec_check.x_studio_previous_months.filtered(lambda l: l.x_name == name)
            if not line_check:
                rec_check.write({'x_studio_previous_months' : line_kpi})
    record.write({'x_studio_submitted' : True})
"""),
    3608: ('hr.employee', """\
today = datetime.date.today()
for record in env['hr.employee'].search([]):
    soon = [expiry for expiry in (record.visa_expire, record.work_permit_expiration_date)
            if expiry and (expiry - today).days < 20]
    if soon:
        check_rec = env['x_date_tracker'].search([('x_name', '=', record.name)], limit=1)
        if not check_rec:
            env['x_date_tracker'].create({'x_name': record.name, 'x_studio_employee': record.id, 'x_studio_update': True})
"""),
    1308: ('x_document_sender', """\
emp = env['hr.employee'].with_context(active_test=False).search([('registration_number', '=', record.x_studio_employee_id_1)], limit=1)
if emp:
    Field = env['ir.model.fields']
    for field_name in ('x_studio_copy_of_entry_permit_1', 'x_studio_copy_of_entry_permit',
                       'x_studio_copy_of_cancellation_paper', 'x_studio_copy_of_noc_paper',
                       'x_studio_copy_of_eid', 'x_studio_copy_of_residence_visa',
                       'x_studio_copy_of_labour_card'):
        field = Field._get(record._name, field_name)
        data = record[field_name]
        if not data or field.ttype != 'binary':
            continue
        env['ir.attachment'].create({
            'name': '%s - %s' % (field.field_description, record.x_name or emp.name),
            'res_model': 'hr.employee',
            'res_id': emp.id,
            'datas': data,
        })
"""),
}

# 1399 loses two lines and keeps the rest verbatim.
DROP_LINES = {
    1399: (
        "    emp_hr = env['x_employeeslist'].search([('id', '=', record.x_studio_requested_for.id)], limit = 1)\n"
        "    emp_hr.write({'x_studio_datesss' : datetime.datetime.now().date()})\n",
    ),
}

ON_THE_MODEL = [150, 151, 630]


def where(action):
    """How the action is reached: a cron, an automation, or a button."""
    cron = Cron.search([('ir_actions_server_id', '=', action.id)], limit=1)
    if cron:
        return 'cron %s (%s)' % (cron.id, 'active' if cron.active else 'inactive')
    if action.base_automation_id:
        auto = action.base_automation_id
        return 'automation %s on %s (%s)' % (auto.id, auto.model_id.model,
                                             'active' if auto.active else 'inactive')
    return '%s / %s' % (action.usage, action.binding_model_id.model if action.binding_model_id else '-')


# --- 1. what changes -------------------------------------------------------

title("1. rewritten")
plans = []
for action_id, (model_name, new_code) in sorted(REWRITE.items()):
    action = Server.browse(action_id).exists()
    if not action:
        print("  %-6s gone already" % action_id)
        continue
    plans.append((action, model_name, new_code))
for action_id, lines in sorted(DROP_LINES.items()):
    action = Server.browse(action_id).exists()
    if not action:
        print("  %-6s gone already" % action_id)
        continue
    code = action.code or ''
    for line in lines:
        if line not in code:
            print("  %-6s the line to drop is not in the code any more:" % action_id)
            print("         %s" % line.strip()[:90])
            code = None
            break
        code = code.replace(line, '')
    if code is not None:
        plans.append((action, action.model_id.model, code))

for action, model_name, new_code in plans:
    old_model = action.model_id.model
    print("\n  %-6s %-30s %s" % (action.id, (action.name or '')[:30], where(action)))
    if old_model != model_name:
        print("         model: %s -> %s" % (old_model, model_name))
    for line in difflib.unified_diff((action.code or '').splitlines(), new_code.splitlines(),
                                     lineterm='', n=1):
        if line.startswith(('---', '+++')):
            continue
        print("         %s" % line[:110])

title("2. retired")
retiring = []
for action_id, why in sorted(RETIRE.items()):
    action = Server.browse(action_id).exists()
    if not action:
        print("  %-6s gone already" % action_id)
        continue
    retiring.append(action)
    print("  %-6s %-30s %s" % (action.id, (action.name or '')[:30], where(action)))
    print("         %s" % why)

title("3. what x_date_tracker is, for the cron that feeds it")
for model_name in ('x_date_tracker',):
    model = env.get(model_name)                                  # noqa: F821
    if model is None:
        print("  %-16s NOT in the registry - its cron cannot be rewritten to feed it" % model_name)
        continue
    cr.execute("SELECT count(*) FROM %s" % model._table)
    print("  %-16s %s row(s)" % (model_name, cr.fetchone()[0]))
    for name in ('x_studio_employee', 'x_studio_company', 'x_studio_employee_id'):
        field = model._fields.get(name)
        if field is not None:
            print("      %-24s %-10s -> %s" % (name, field.type, getattr(field, 'comodel_name', '') or ''))

title("4. the document scans 1308 would attach - field types on x_document_sender")
for name in ('x_studio_copy_of_entry_permit_1', 'x_studio_copy_of_entry_permit',
             'x_studio_copy_of_cancellation_paper', 'x_studio_copy_of_noc_paper',
             'x_studio_copy_of_eid', 'x_studio_copy_of_residence_visa', 'x_studio_copy_of_labour_card'):
    field = IrField.search([('model', '=', 'x_document_sender'), ('name', '=', name)], limit=1)
    print("  %-40s %-8s %s" % (name, field.ttype if field else 'MISSING',
                               (field.field_description or '') if field else ''))

title("5. triggered by the model itself - not touched here, printed for the next decision")
for auto in Automation.with_context(active_test=False).browse(ON_THE_MODEL).exists():
    print("\n  automation %-4s %-40s on %s  trigger=%s  %s"
          % (auto.id, (auto.name or '')[:40], auto.model_id.model, auto.trigger,
             'active' if auto.active else 'inactive'))
    for action in auto.action_server_ids:
        print("    action %s  state=%s" % (action.id, action.state))
        for line in (action.code or '').splitlines():
            print("      %s" % line[:110])

if DRY_RUN:
    print("\n" + "=" * 78)
    print("  DRY RUN - nothing written. Run again with SSC_WRITE=1.")
    cr.rollback()
    raise SystemExit()


# --- 6. write --------------------------------------------------------------

title("6. writing")
done = 0
for action, model_name, new_code in plans:
    vals = {'code': new_code}
    if action.model_id.model != model_name:
        model = IrModel.search([('model', '=', model_name)], limit=1)
        vals['model_id'] = model.id
    with cr.savepoint():
        action.write(vals)
    done += 1
    print("  > %-6s rewritten" % action.id)
cr.commit()

gone = 0
for action in retiring:
    with cr.savepoint():
        cron = Cron.search([('ir_actions_server_id', '=', action.id)])
        auto = action.base_automation_id
        if cron:
            cron.unlink()
        if auto:
            auto.unlink()
        if action.exists():
            action.unlink()
    gone += 1
    print("  - %-6s retired" % action.id)
cr.commit()

title("summary")
print("  %s rewritten, %s retired." % (done, gone))
print("""
  The web workers hold the old code until they restart: odoosh-restart http.
  Then what_still_needs_the_employee_list should list no server action.""")
