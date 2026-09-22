"""Undo what tools/pre_upgrade_v19.py switched off. Run once the database is on
19.0 and ssc_payroll / ssc_attendance are installed again:

    odoo-bin shell -d <database> --no-http < tools/post_upgrade_v19.py

Our own two core-inheriting views need nothing here - they declare active in
their XML, so the module update already turned them back on. What this restores
is the other set: views built in the interface or by Studio on top of our models,
which belong to studio_customization or to nobody, and which therefore have
nothing to switch them back on.

Section 1b of the pre-upgrade script recorded their ids in a config parameter,
so exactly that set comes back - no guessing from names, and views that were
already inactive before the upgrade stay inactive.
"""

VIEW_KEY = 'ssc.pre_upgrade.deactivated_view_ids'
MENU_KEY = 'ssc.pre_upgrade.deactivated_menu_ids'

param = env['ir.config_parameter'].sudo()


def recorded(key):
    return [int(i) for i in (param.get_param(key) or '').split(',') if i.strip()]


totals = {'restored': 0, 'gone': 0, 'broken': 0}


def describe(rec):
    if rec._name == 'ir.ui.menu':
        return rec.complete_name
    return f"{rec.xml_id or rec.id} [{rec.model}/{rec.type}]"


def restore(key, model_name, label, check=None):
    ids = recorded(key)
    if not ids:
        print(f"=== nothing recorded under {key}")
        return
    print(f"\n=== restoring {len(ids)} {label}(s) recorded before the upgrade")
    for rec_id in ids:
        rec = env[model_name].with_context(active_test=False).browse(rec_id).exists()
        if not rec:
            totals['gone'] += 1
            print(f"  .. id={rec_id}: gone (dropped during the upgrade)")
            continue
        try:
            # One savepoint each: something that no longer validates on 19.0
            # must not take the rest of the batch down with it.
            with env.cr.savepoint():
                rec.active = True
                if check:
                    check(rec)
            totals['restored'] += 1
            print(f"  OK {describe(rec)}")
        except Exception as exc:
            totals['broken'] += 1
            print(f"  !! id={rec_id}: left inactive - "
                  f"{str(exc).splitlines()[0][:140]}")
    param.set_param(key, '')


restore(VIEW_KEY, 'ir.ui.view', 'view', check=lambda v: v._check_xml())
restore(MENU_KEY, 'ir.ui.menu', 'menu')

print(f"\n=== {totals['restored']} restored, {totals['gone']} gone, "
      f"{totals['broken']} still broken")
if totals['broken']:
    print("    The broken ones are customisations that do not survive 19.0.")
    print("    Rebuild them in Studio, or leave them off.")
env.cr.commit()
print("=== committed, parameters cleared")
