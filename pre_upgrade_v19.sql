-- Pre-upgrade preparation, done straight in SQL.
--
--     psql -f ~/src/user/tools/pre_upgrade_v19.sql
--
-- Same job as tools/pre_upgrade_v19.py, but without going through Odoo. Once
-- the 19.0 port is on the branch, an 18.0 server cannot even import the module
-- (models.Constraint, res.groups.privilege and all_group_ids do not exist
-- there), so the registry never loads and odoo-bin shell is unusable. The rows
-- this has to touch are plain rows, and psql does not care that the module is
-- broken.
--
-- Everything here is reversible: tools/post_upgrade_v19.py reads back the same
-- config parameter once the database is on 19.0 with the modules loaded.

\echo ''
\echo '=== 1. views of ours that inherit a core view'

UPDATE ir_ui_view SET active = false
WHERE active
  AND id IN (
    SELECT res_id FROM ir_model_data
    WHERE model = 'ir.ui.view'
      AND ((module = 'ssc_attendance' AND name = 'res_config_settings_view_form')
        OR (module = 'ssc_payroll'    AND name = 'view_company_form_ssc_payroll'))
  );

\echo '=== 1b. interface-built views on our models'

-- Recorded before they are switched off, so post_upgrade_v19.py restores
-- exactly this set. Merged with anything a previous run left behind.
WITH foreign_views AS (
    SELECT v.id
    FROM ir_ui_view v
    WHERE v.active
      AND v.model LIKE 'ssc.%'
      AND NOT EXISTS (
        SELECT 1 FROM ir_model_data d
        WHERE d.model = 'ir.ui.view' AND d.res_id = v.id
          AND d.module IN ('ssc_payroll', 'ssc_attendance')
      )
), merged AS (
    SELECT string_agg(x::text, ',' ORDER BY x) AS ids
    FROM (
        SELECT id AS x FROM foreign_views
        UNION
        SELECT unnest(string_to_array(NULLIF(value, ''), ','))::int
        FROM ir_config_parameter
        WHERE key = 'ssc.pre_upgrade.deactivated_view_ids'
    ) all_ids
)
INSERT INTO ir_config_parameter (key, value, create_uid, create_date, write_uid, write_date)
SELECT 'ssc.pre_upgrade.deactivated_view_ids', COALESCE(ids, ''), 1, now(), 1, now()
FROM merged
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = now();

SELECT id, model, type, name
FROM ir_ui_view v
WHERE v.active
  AND v.model LIKE 'ssc.%'
  AND NOT EXISTS (
    SELECT 1 FROM ir_model_data d
    WHERE d.model = 'ir.ui.view' AND d.res_id = v.id
      AND d.module IN ('ssc_payroll', 'ssc_attendance')
  );

UPDATE ir_ui_view v SET active = false
WHERE v.active
  AND v.model LIKE 'ssc.%'
  AND NOT EXISTS (
    SELECT 1 FROM ir_model_data d
    WHERE d.model = 'ir.ui.view' AND d.res_id = v.id
      AND d.module IN ('ssc_payroll', 'ssc_attendance')
  );

\echo '=== 1c. duplicate time keeper rules'

-- These hardcode a company and are OR-ed with the rule the module ships for the
-- same group, so they hand that company to every member regardless of which
-- companies they were granted. Switching them off narrows access, it does not
-- widen it - the module rule already covers the legitimate case.
SELECT id, name, active FROM ir_rule WHERE name IN ('ssc timekeeper', 'ra timekeeper');
UPDATE ir_rule SET active = false WHERE name IN ('ssc timekeeper', 'ra timekeeper');

\echo ''
\echo '=== result'
SELECT value AS recorded_view_ids
FROM ir_config_parameter
WHERE key = 'ssc.pre_upgrade.deactivated_view_ids';

SELECT count(*) FILTER (WHERE active) AS still_active_ssc_foreign_views
FROM ir_ui_view v
WHERE v.model LIKE 'ssc.%'
  AND NOT EXISTS (
    SELECT 1 FROM ir_model_data d
    WHERE d.model = 'ir.ui.view' AND d.res_id = v.id
      AND d.module IN ('ssc_payroll', 'ssc_attendance')
  );
