-- Prepare the production database for the 19.0 upgrade. Deactivation only.
--
--     psql -P pager=off -f ~/src/user/tools/prepare_production_v19.sql
--
-- Nothing is deleted. Every row this touches is switched off and its id recorded,
-- and tools/revert_production_prep.sql switches the same set back on. Production
-- stays on 18.0 throughout: it is prepared, not upgraded.
--
-- Odoo.sh sends "the latest daily backup" of PRODUCTION to the upgrade platform,
-- not the staging database - which is why preparing test_1 had no effect on any
-- attempt. So this runs here, and a fresh backup has to follow it, or the
-- upgrade picks up one from before it ran.
--
-- The sequence is: run this -> Backup Now -> run the revert -> request the
-- upgrade on test_1. Production only carries the switched-off state for the few
-- minutes in between; the backup keeps it.
--
-- What the upgrade log actually failed on, and what each section answers:
--
--   1. mail_mobile's settings view xpaths onto a block it cannot locate on 19.0.
--      An inherited view that fails to apply invalidates the whole tree it hangs
--      from, so that one view failed twelve Settings menus at once.
--   2. Our own two views inherit core views and add fields that do not exist
--      upgrade-side, where our Python is never loaded - same failure mode.
--   3. Views built in the interface on ssc.* models: same again, and nothing
--      restores them automatically, so their ids are recorded.
--   4. Studio menus opening a model with no access rule at all. Reading such a
--      model raises AccessError on 19.0 - that is how 'Store > Transaction' and
--      'Subcontract & Supplier > Configuration (Sub)' failed.
--   5. Studio menus whose action or model is already gone. They raise when
--      clicked today, so switching them off costs nothing.
--
-- Nothing is matched on a hard-coded id: view ids differ between databases.

CREATE TEMP TABLE off_views (id integer);
CREATE TEMP TABLE off_menus (id integer);

\echo ''
\echo '=== 1. mail_mobile settings view'

INSERT INTO off_views
SELECT v.id FROM ir_ui_view v
JOIN ir_model_data d ON d.model = 'ir.ui.view' AND d.res_id = v.id
WHERE v.active AND d.module = 'mail_mobile' AND d.name = 'res_config_settings_view_form';

\echo '=== 2. our views that inherit a core view'

INSERT INTO off_views
SELECT res_id FROM ir_model_data
WHERE model = 'ir.ui.view'
  AND ((module = 'ssc_attendance' AND name = 'res_config_settings_view_form')
    OR (module = 'ssc_payroll'    AND name = 'view_company_form_ssc_payroll'))
  AND res_id IN (SELECT id FROM ir_ui_view WHERE active);

\echo '=== 3. interface-built views on our models'

INSERT INTO off_views
SELECT v.id FROM ir_ui_view v
WHERE v.active AND v.model LIKE 'ssc.%'
  AND NOT EXISTS (
    SELECT 1 FROM ir_model_data d
    WHERE d.model = 'ir.ui.view' AND d.res_id = v.id
      AND d.module IN ('ssc_payroll', 'ssc_attendance'));

\echo '=== 4. Studio menus opening a model nobody can read'

-- Not "has no access rule" - x_items_ordered has five of them, every one with
-- perm_read false, so nobody can read it and the crawler fails exactly the same
-- way. What matters is whether any ACTIVE rule grants read, not whether rules
-- exist. (That model is misconfigured on 18.0 too; this only keeps it from
-- failing the upgrade. Granting the read properly is a separate decision.)
INSERT INTO off_menus
SELECT me.id
FROM ir_ui_menu me
JOIN ir_act_window w ON me.action = 'ir.actions.act_window,' || w.id
JOIN ir_model m ON m.model = w.res_model
WHERE me.active
  AND m.state = 'manual'
  AND NOT EXISTS (
    SELECT 1 FROM ir_model_access a
    WHERE a.model_id = m.id AND a.perm_read AND a.active);

\echo '=== 5. Studio menus whose target is gone'

-- Only menus that actually open a window action. A menu can also point at
-- ir.actions.act_url (and at client or server actions), and those have no
-- ir_act_window row by definition - checking for a missing one flagged
-- twenty-one perfectly healthy menus, Payslips and Attendance Check among them.
INSERT INTO off_menus
SELECT me.id
FROM ir_ui_menu me
JOIN ir_model_data d ON d.model = 'ir.ui.menu' AND d.res_id = me.id
WHERE me.active
  AND d.module = 'studio_customization'
  AND me.action LIKE 'ir.actions.act_window,%'
  AND (
    NOT EXISTS (SELECT 1 FROM ir_act_window w
                WHERE me.action = 'ir.actions.act_window,' || w.id)
    OR EXISTS (SELECT 1 FROM ir_act_window w
               WHERE me.action = 'ir.actions.act_window,' || w.id
                 AND NOT EXISTS (SELECT 1 FROM ir_model m WHERE m.model = w.res_model))
  );

\echo ''
\echo '=== what is about to be switched off'

SELECT v.id, v.model, v.type,
       COALESCE(d.module || '.' || d.name, '(no xml_id)') AS xml_id
FROM ir_ui_view v
LEFT JOIN ir_model_data d ON d.model = 'ir.ui.view' AND d.res_id = v.id
WHERE v.id IN (SELECT id FROM off_views)
ORDER BY v.id;

SELECT me.id, me.name->>'en_US' AS label,
       COALESCE(d.module || '.' || d.name, '(no xml_id)') AS xml_id
FROM ir_ui_menu me
LEFT JOIN ir_model_data d ON d.model = 'ir.ui.menu' AND d.res_id = me.id
WHERE me.id IN (SELECT id FROM off_menus)
ORDER BY me.id;

\echo ''
\echo '=== recording and switching off'

-- Recorded before anything moves, merged with whatever a previous run left, so
-- running this twice cannot lose the first batch.
INSERT INTO ir_config_parameter (key, value, create_uid, create_date, write_uid, write_date)
SELECT 'ssc.pre_upgrade.deactivated_view_ids',
       COALESCE((SELECT string_agg(x::text, ',' ORDER BY x) FROM (
           SELECT id AS x FROM off_views
           UNION
           SELECT unnest(string_to_array(NULLIF(value, ''), ','))::int
           FROM ir_config_parameter WHERE key = 'ssc.pre_upgrade.deactivated_view_ids'
       ) s), ''),
       1, now(), 1, now()
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = now();

INSERT INTO ir_config_parameter (key, value, create_uid, create_date, write_uid, write_date)
SELECT 'ssc.pre_upgrade.deactivated_menu_ids',
       COALESCE((SELECT string_agg(x::text, ',' ORDER BY x) FROM (
           SELECT id AS x FROM off_menus
           UNION
           SELECT unnest(string_to_array(NULLIF(value, ''), ','))::int
           FROM ir_config_parameter WHERE key = 'ssc.pre_upgrade.deactivated_menu_ids'
       ) s), ''),
       1, now(), 1, now()
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = now();

UPDATE ir_ui_view SET active = false WHERE id IN (SELECT id FROM off_views);
UPDATE ir_ui_menu SET active = false WHERE id IN (SELECT id FROM off_menus);

\echo ''
\echo '=== result'
SELECT (SELECT count(*) FROM off_views) AS views_off,
       (SELECT count(*) FROM off_menus) AS menus_off;
SELECT key, value FROM ir_config_parameter
WHERE key LIKE 'ssc.pre_upgrade.%' ORDER BY key;

\echo ''
\echo '    Take a fresh backup on production now, then run'
\echo '    tools/revert_production_prep.sql to put production back.'
