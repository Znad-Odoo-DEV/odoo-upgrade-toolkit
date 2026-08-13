# Odoo 18.0 → 19.0 upgrade toolkit

Scripts for taking a heavily customised Odoo.sh database from 18.0 to 19.0
without finding out what broke by opening screens one at a time.

They were written against a database with a large Studio layer (hundreds of
manual models, thousands of manual fields) and two custom modules that inherit
core models. That is the case they are useful for. On a plain database the
upgrade platform does the whole job on its own and none of this is needed.

Nothing here uploads, deletes on its own, or talks to anything outside the
database it is pointed at. The read-only scripts say so in their header; the
two that write are deactivation-only and each has a companion that reverses it.

## Why any of it is necessary

`upgrade.odoo.com` runs **standard** Odoo. While the database is being upgraded,
your custom modules are not installed, so their models and fields do not exist.
Every Studio field, view, menu, automation or record rule that points at one of
them is, for the duration, a reference to nothing — and a single inherited view
that fails to apply invalidates the whole tree it hangs from, which is enough to
fail the post-upgrade crawler and sink the run.

The fix is not to remove those customisations. It is to switch them off for the
length of the upgrade, record exactly what was switched off, and switch it back
on afterwards.

## Order of operations

### 1. Look before touching anything

```sh
odoo-bin shell -d "$DB" --no-http < probe_custom_dependencies.py
psql -P pager=off -f report_studio_models.sql
```

`probe_custom_dependencies.py` lists everything that depends on your custom
Python. `report_studio_models.sql` finds Studio models with no access rules —
on 19.0 those are unreadable to everyone but the superuser, which is a common
way for a menu to fail the crawler.

### 2. Take the "before" inventory

```sh
odoo-bin shell -d "$DB" --no-http 2>/dev/null < upgrade_snapshot.py > before_18.txt
```

One sorted `key<TAB>value` line per model count, amount total, per-user group
count and custom-object tally. Models Odoo renamed between the series are
counted under one key, so `hr.contract` and `hr.version` line up instead of
reading as a loss and a gain.

Keep this file somewhere that survives the upgrade. Storing it inside the
database as an attachment works well — it then travels with the backup by
itself and can be read back out on the upgraded copy.

### 3. Prepare, back up, revert

```sh
psql -P pager=off -f prepare_production_v19.sql   # deactivation only, ids recorded
# take the backup now
psql -P pager=off -f revert_production_prep.sql   # production is itself again
```

Production stays on 18.0 the whole time — it is prepared, not upgraded. The
window where anything is switched off is the length of one backup.

`pre_upgrade_v19.py` does the same job through the ORM. Use the `.sql` version
when the 19.0 port is already on the branch: an 18.0 server cannot import it
(`models.Constraint`, `res.groups.privilege` and `all_group_ids` do not exist
there), the registry never loads, and `odoo-bin shell` is unusable.

### 4. Upgrade a copy, never production

Restore the backup onto a staging branch and upgrade that. Before starting,
check the copy is actually the one you prepared — a staging branch restored
from last night's automatic backup does not contain today's work.

### 5. Repair what 19.0 rejected

```sh
psql -f fix_studio_v19_breakage.sql
odoo-bin shell -d "$DB" --no-http < post_upgrade_v19.py
odoo-bin shell -d "$DB" --no-http < cleanup_studio_orphans.py   # dry run
```

`fix_studio_v19_breakage.sql` handles the customisations the upgrade log
complained about, chiefly inherited views whose xpath no longer resolves.
`post_upgrade_v19.py` switches back on what step 3 switched off.
`cleanup_studio_orphans.py` removes Studio menus and actions pointing at
things that no longer exist — it prints and changes nothing until you opt in
for that one run.

### 6. Compare

```sh
odoo-bin shell -d "$DB" --no-http 2>/dev/null < upgrade_snapshot.py > after_19.txt
diff before_18.txt after_19.txt
```

This is the acceptance test. A line that changed is data the upgrade moved; a
line that disappeared is data it lost.

Expect module versions to change and the counts of `ir.ui.view`,
`ir.model.fields` and `mail.message` to move — 19.0 adds views and fields of
its own. Nothing else should.

## What is not here

Scripts that move business data (project masters, contract analytic
distribution, employee hourly cost, badge normalisation) are specific to one
company's data model and are kept out on purpose. This repository is only the
upgrade mechanics.

## Notes

- Every script names the database explicitly. None of them guesses.
- The SQL ones run under `psql`; the Python ones under `odoo-bin shell`.
- Read the header of a file before running it. Each one states what it writes,
  what it only reads, and what reverses it.
