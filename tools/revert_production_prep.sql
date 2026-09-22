-- Put production back the moment the backup is taken.
--
--     psql -P pager=off -f ~/src/user/tools/revert_production_prep.sql
--
-- prepare_production_v19.sql switches views and menus off so the backup captures
-- a database the upgrade platform can crawl. Production stays on 18.0, where
-- nothing turns them back on - so without this, the Payroll Configuration group
-- stays missing from the company form and a handful of Studio menus stay hidden,
-- for as long as nobody notices.
--
-- The upgrade works off the backup, so it still sees the switched-off state.
-- Production only carries it for the minutes between the two scripts.
--
-- The config parameters are deliberately NOT cleared: they travel with the
-- backup, and tools/post_upgrade_v19.py reads them on the upgraded database to
-- restore the same set there.

\echo ''
\echo '=== recorded by the preparation script'

SELECT key, value FROM ir_config_parameter
WHERE key LIKE 'ssc.pre_upgrade.%' ORDER BY key;

\echo ''
\echo '=== switching them back on'

UPDATE ir_ui_view SET active = true
WHERE id IN (
    SELECT unnest(string_to_array(NULLIF(value, ''), ','))::int
    FROM ir_config_parameter
    WHERE key = 'ssc.pre_upgrade.deactivated_view_ids'
);

UPDATE ir_ui_menu SET active = true
WHERE id IN (
    SELECT unnest(string_to_array(NULLIF(value, ''), ','))::int
    FROM ir_config_parameter
    WHERE key = 'ssc.pre_upgrade.deactivated_menu_ids'
);

\echo ''
\echo '=== check - nothing below should read false'

SELECT v.id, v.model, v.active,
       COALESCE(d.module || '.' || d.name, '(no xml_id)') AS xml_id
FROM ir_ui_view v
LEFT JOIN ir_model_data d ON d.model = 'ir.ui.view' AND d.res_id = v.id
WHERE v.id IN (
    SELECT unnest(string_to_array(NULLIF(value, ''), ','))::int
    FROM ir_config_parameter WHERE key = 'ssc.pre_upgrade.deactivated_view_ids')
ORDER BY v.id;

SELECT me.id, me.name->>'en_US' AS label, me.active
FROM ir_ui_menu me
WHERE me.id IN (
    SELECT unnest(string_to_array(NULLIF(value, ''), ','))::int
    FROM ir_config_parameter WHERE key = 'ssc.pre_upgrade.deactivated_menu_ids')
ORDER BY me.id;
