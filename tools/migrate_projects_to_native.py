"""Move the project master off the Studio model x_projects_list onto the native
project.project. Run on 18.0, BEFORE deploying the code that switches the
project_id fields over:

    odoo-bin shell -d <database> --no-http < tools/migrate_projects_to_native.py

What it does, in order:

 1. creates the seven project stages, one per value the Studio selection held
 2. creates one project.project per x_projects_list record
 3. repoints the 29 attachments (avatar, BOQ, site layout, ...) at the new record
 4. links each project to its analytic account, creating one only where a
    project is On-Going and has none
 5. records the old -> new id map in a config parameter, which is what the
    pre-migrate scripts of ssc_payroll / ssc_attendance read to repoint their
    nine project_id columns

Nothing is deleted. x_projects_list keeps every row and every field: about a
hundred Studio fields on other Studio models still point at it, and they must
go on working untouched.

Safe to run twice - projects are matched by name, attachments by their new
owner, analytic accounts by name, and the stages by name.

No fields are added to project.project. Only the data with a native home moves:
name, active, description, sequence, stage and documents. Everything else stays
readable on x_projects_list.
"""
import json

from markupsafe import escape

# --- what to run -----------------------------------------------------------
# Leave False to actually write. True prints the same report and rolls back,
# which is worth doing once on a database you care about.
DRY_RUN = False

# --- the Studio side -------------------------------------------------------
STUDIO_MODEL = 'x_projects_list'
STATUS_FIELD = 'x_studio_selection_field_841_1ifp8eo32'
ONGOING_STATUS = 'status3'

# Studio selection value -> (stage name, sequence, folded). Deliberately 1:1
# with what is in the database today: reorganising the pipeline is a business
# decision, and mixing it into a technical migration makes it impossible to
# tell a data problem from a design change. Rename or merge from the interface
# afterwards. Sequences start at 110 so these sit underneath project's own
# To Do / In Progress / Done / Cancelled, which are left alone.
STAGE_SPEC = [
    ('status1',            "New Project",           110, False),
    ('status2',            "Approvals Stage",       120, False),
    ('status3',            "On-Going Construction", 130, False),
    ('On-Hold (Redesign)', "On-Hold (Redesign)",    140, False),
    ('On-Hold',            "On-Hold",               150, False),
    ('Completed',          "Completed",             160, True),
    # Was "Main Store". Not really a pipeline step, but kept as one so that the
    # single project in it stays outside the staff cost distribution, exactly
    # as it is today.
    ('Main Store',         "Store / Operating",     170, False),
]

# --- the analytic side -----------------------------------------------------
ANALYTIC_PLAN = 'Project'
# Most of the analytic chart belongs to SAUD SHEHATHA. Where a site has an
# account in more than one company (both SSC and Royal Arrow work some of
# them), this is the one the project points at; the other company's account is
# resolved from (project, paying company) when cost is actually posted.
PREFERRED_COMPANY_ID = 1

# --- handover to the pre-migrate scripts -----------------------------------
ID_MAP_KEY = 'ssc.project_migration.id_map'
ONGOING_STAGE_KEY = 'ssc_payroll.ongoing_project_stage_id'


# ---------------------------------------------------------------------------

# env(context=...) and not with_context: the latter is a recordset method, the
# Environment itself is called to rebind its context.
env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
param = env['ir.config_parameter'].sudo()
Project = env['project.project'].sudo()
Stage = env['project.project.stage'].sudo()
Analytic = env['account.analytic.account'].sudo()

report = {'stages': 0, 'projects': 0, 'existing': 0, 'attachments': 0,
          'analytic_linked': 0, 'analytic_created': 0, 'analytic_none': 0}


def title(text):
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


# --- 1. stages -------------------------------------------------------------

title("1. project stages")

stage_by_status = {}
for status, name, sequence, fold in STAGE_SPEC:
    stage = Stage.search([('name', '=', name), ('company_id', '=', False)], limit=1)
    if stage:
        print(f"  = {name!r} already exists (id {stage.id})")
    else:
        stage = Stage.create({'name': name, 'sequence': sequence, 'fold': fold})
        report['stages'] += 1
        print(f"  + {name!r} created (id {stage.id})")
    stage_by_status[status] = stage

ongoing_stage = stage_by_status[ONGOING_STATUS]
param.set_param(ONGOING_STAGE_KEY, str(ongoing_stage.id))
print(f"\n  {ONGOING_STAGE_KEY} = {ongoing_stage.id} ({ongoing_stage.name})")
print("  NOTE: stages only show in the interface once Project > Configuration >"
      " Settings > Project Stages is ticked.")


# --- 2. projects -----------------------------------------------------------

title("2. projects")

Studio = env[STUDIO_MODEL].sudo()
studio_projects = Studio.search([], order='id')
print(f"  {len(studio_projects)} record(s) on {STUDIO_MODEL}\n")

id_map = {}
for src in studio_projects:
    name = (src.x_name or '').strip()
    if not name:
        print(f"  ! {STUDIO_MODEL} id {src.id} has no name - skipped")
        continue

    existing = Project.search([('name', '=', name)], limit=1)
    if existing:
        id_map[src.id] = existing.id
        report['existing'] += 1
        print(f"  = {name}  ->  project {existing.id} (already there)")
        continue

    status = src[STATUS_FIELD]
    stage = stage_by_status.get(status)
    if stage is None:
        print(f"  ! {name}: unknown status {status!r} - left without a stage")

    # project.description is Html where the Studio one was plain text, so the
    # line breaks have to be carried over explicitly or the whole note collapses
    # into a single paragraph.
    note = (src.x_studio_description or '').strip()
    description = f"<p>{escape(note)}</p>".replace('\n', '<br/>') if note else False

    project = Project.create({
        'name': name,
        'active': bool(src.x_active),
        'description': description,
        'sequence': src.x_studio_sequence or 10,
        'stage_id': stage.id if stage else False,
        # No company on purpose. x_projects_list has no company field, so every
        # project is visible to all four companies today; giving them one here
        # would quietly take that access away.
        'company_id': False,
    })
    id_map[src.id] = project.id
    report['projects'] += 1
    flag = '' if src.x_active else '  [archived]'
    print(f"  + {name}  ->  project {project.id}  [{stage.name if stage else '-'}]{flag}")


# --- 3. attachments --------------------------------------------------------

title("3. attachments")

# Raw SQL on purpose: these rows carry res_field, which the ORM treats as
# internal field storage rather than as documents.
env.cr.execute("""
    SELECT name, field_description->>'en_US'
      FROM ir_model_fields
     WHERE model = %s
""", (STUDIO_MODEL,))
field_label = dict(env.cr.fetchall())

env.cr.execute("""
    SELECT id, res_id, res_field, name
      FROM ir_attachment
     WHERE res_model = %s
     ORDER BY res_id, id
""", (STUDIO_MODEL,))
attachments = env.cr.fetchall()
print(f"  {len(attachments)} attachment(s) on {STUDIO_MODEL}\n")

for att_id, res_id, res_field, att_name in attachments:
    new_id = id_map.get(res_id)
    if not new_id:
        print(f"  ! attachment {att_id} points at {STUDIO_MODEL} {res_id}, "
              f"which was not migrated - left alone")
        continue

    # res_field is cleared so the file becomes a normal document on the
    # project instead of the hidden storage of a Studio binary field. The
    # field label goes into the name, otherwise nobody can tell a soil report
    # from a site layout once they are all sitting in one list.
    label = field_label.get(res_field or '')
    new_name = att_name
    if label and label.lower() not in (att_name or '').lower():
        new_name = f"{label} - {att_name}"

    env.cr.execute("""
        UPDATE ir_attachment
           SET res_model = 'project.project', res_id = %s, res_field = NULL, name = %s
         WHERE id = %s
    """, (new_id, new_name, att_id))
    report['attachments'] += 1
    print(f"  > {new_name}  ->  project {new_id}")

env.invalidate_all()


# --- 4. analytic accounts --------------------------------------------------

title("4. analytic accounts")

plan = env['account.analytic.plan'].sudo().search(
    [('name', '=', ANALYTIC_PLAN), ('parent_id', '=', False)], limit=1)
if not plan:
    raise RuntimeError(f"no root analytic plan named {ANALYTIC_PLAN!r}")
print(f"  plan {ANALYTIC_PLAN!r} = id {plan.id}\n")


def pick_account(name):
    """Existing account for this project, preferring the main company.

    Sites worked by two companies have one account each; the project points at
    the main company's and the other is resolved at posting time.
    """
    candidates = Analytic.search([('plan_id', '=', plan.id), ('name', '=', name)])
    if not candidates:
        return Analytic.browse()
    return (candidates.filtered(lambda a: a.company_id.id == PREFERRED_COMPANY_ID)
            or candidates.filtered(lambda a: not a.company_id)
            or candidates)[:1]


for old_id, new_id in sorted(id_map.items()):
    project = Project.browse(new_id)
    if project.account_id:
        print(f"  = {project.name}: already on {project.account_id.name!r}")
        continue

    account = pick_account(project.name)
    if account:
        project.account_id = account.id
        report['analytic_linked'] += 1
        company = account.company_id.name or 'no company'
        print(f"  > {project.name}  ->  analytic {account.id} "
              f"({account.code or 'no code'}, {company})")
        continue

    # Only sites that actually receive cost get an account. Creating one for
    # every project on the list would put fifteen dead accounts into a chart
    # that is currently well kept; a project gets its account when it starts.
    if project.stage_id == ongoing_stage:
        account = Analytic.create({
            'name': project.name,
            'plan_id': plan.id,
            # No company: both companies must be able to post to it.
            'company_id': False,
        })
        project.account_id = account.id
        report['analytic_created'] += 1
        print(f"  + {project.name}  ->  analytic {account.id} CREATED (no company)")
    else:
        report['analytic_none'] += 1
        print(f"  . {project.name}: no account, not On-Going - left empty")


# --- 5. hand the map to the pre-migrate scripts ----------------------------

title("5. id map")

param.set_param(ID_MAP_KEY, json.dumps({str(k): v for k, v in sorted(id_map.items())}))
print(f"  {ID_MAP_KEY} holds {len(id_map)} pair(s)")
print("  the pre-migrate scripts of ssc_payroll and ssc_attendance read this "
      "to repoint their project_id columns")


# --- done ------------------------------------------------------------------

title("summary")
for key, value in report.items():
    print(f"  {key:<18} {value}")

if DRY_RUN:
    env.cr.rollback()
    print("\nDRY_RUN - everything above was rolled back.")
else:
    env.cr.commit()
    print("\ncommitted.")
