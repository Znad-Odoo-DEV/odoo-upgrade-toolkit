"""Cut the last three threads from live logic to x_projects_list.

    cd ~/src/user
    odoo-bin shell -d <database> --no-http < tools/retire_projects_list.py

    APPLY=1   change. Without it, show every change and touch nothing.

x_projects_list was replaced by project.project. Nothing points at it any
more - no column, no related field, no view outside it - but three pieces of
Studio logic still call env['x_projects_list'] by name, and a name lookup is
not a foreign key: it survives the delete and raises KeyError the first time
it runs.

  Set Approver (server action 3141, on x_all_requests)
      Looks six projects up in x_projects_list by name, then compares their
      ids with record.x_studio_which_project_.id - which has pointed at
      project.project since the projects migration. So it has been comparing
      ids across two models for as long as that: right when two numbers
      happen to coincide, silently wrong otherwise. Rewritten to look the same
      six names up in project.project. Every name is verified to resolve to
      exactly one project before the code is touched.

  Project Approval Stage / Project on Hold (automations on x_new_projects,
  server actions 2357 and 2358)
      Each searches x_projects_list by name and writes a status into it.
      That is their whole job. With the list gone they have none, and left
      in place they crash every status change on x_new_projects. Removed,
      with their server actions.

  Filter 2 "Projects" on x_projects
      Saved filter on x_studio_statustags - a many2many to a tag model that is
      going. Stale after the delete; removed.

Nothing else. No model, no column, no view.
"""
import os

APPLY = os.environ.get('APPLY') == '1'
WIDTH = 100

env = env(context=dict(env.context, lang='en_US', active_test=False))  # noqa: F821
env = env['base'].sudo().env
Server = env['ir.actions.server'].sudo()
Auto = env['base.automation'].sudo().with_context(active_test=False)
Project = env['project.project'].sudo().with_context(active_test=False)

OLD = "env['x_projects_list'].search([('x_name', '=',"
NEW = "env['project.project'].search([('name', '=',"

print()
print("=" * WIDTH)
print("1. Set Approver - server action 3141 on x_all_requests")
print("=" * WIDTH)
approver = Server.browse(3141).exists()
rewrite_ok = False
if not approver:
    print("  not on this database")
elif OLD not in (approver.code or ''):
    print("  does not contain the lookup any more - nothing to rewrite")
else:
    # Every project name the code looks up must resolve, once, in project.project.
    import re
    names = re.findall(r"\('x_name', '=', '([^']+)'\)", approver.code)
    print("  %s project name(s) looked up:" % len(names))
    unresolved = []
    for name in names:
        hits = Project.search([('name', '=', name)])
        print("      %-48s -> project.project %s" % (name[:48], hits.ids or "NOT FOUND"))
        if len(hits) != 1:
            unresolved.append(name)
    if unresolved:
        print("  !! %s name(s) do not resolve to exactly one project - NOT rewritten." % len(unresolved))
    else:
        rewrite_ok = True
        print("  all resolve. The change is one substitution, %s occurrence(s):"
              % approver.code.count(OLD))
        print("      %s  ->  %s" % (OLD, NEW))

print()
print("=" * WIDTH)
print("2. Automations on x_new_projects that only write into the list")
print("=" * WIDTH)
doomed = Auto.search([('name', 'in', ['Project Approval Stage', 'Project on Hold'])])
for a in doomed:
    acts = a.action_server_ids
    print("  automation %-5s %-28s on %-16s %s  -> server action(s) %s"
          % (a.id, a.name, a.model_id.model, "" if a.active else "(inactive)", acts.ids))
    for act in acts:
        if "x_projects_list" not in (act.code or ''):
            print("      !! server action %s does NOT name x_projects_list - left alone" % act.id)
if not doomed:
    print("  none found")

print()
print("=" * WIDTH)
print("3. Saved filter on x_projects using the status tags")
print("=" * WIDTH)
Filters = env['ir.filters'].sudo().with_context(active_test=False)
stale = Filters.search([('model_id', '=', 'x_projects'), ('domain', 'ilike', 'x_studio_statustags')])
for f in stale:
    print("  filter %-5s %-20s domain: %s" % (f.id, f.name, (f.domain or '')[:60]))
if not stale:
    print("  none")

print()
if not APPLY:
    print("  DRY RUN - nothing was touched. Re-run with APPLY=1.")
    env.cr.rollback()
else:
    if rewrite_ok:
        approver.write({'code': approver.code.replace(OLD, NEW)})
        print("  Set Approver rewritten.")
    for a in doomed:
        acts = a.action_server_ids.filtered(lambda s: "x_projects_list" in (s.code or ''))
        name = a.name
        a.unlink()
        acts.unlink()
        print("  automation '%s' removed with server action(s) %s." % (name, acts.ids))
    if stale:
        ids = stale.ids
        stale.unlink()
        print("  filter(s) %s removed." % ids)
    env.cr.commit()
    print("  Committed.")
print("=" * WIDTH)
