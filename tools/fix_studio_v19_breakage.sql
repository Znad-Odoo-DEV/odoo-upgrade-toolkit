-- Studio customisations that 19.0 rejects, found from the upgrade log.
--
--     psql -f ~/src/user/tools/fix_studio_v19_breakage.sql
--
-- Two problems, neither of them ours, both fatal to the post-upgrade crawler.
--
-- 1. A view xpaths onto //block[@id='user_default_rights'] and cannot find it.
--    An inherited view that fails to apply invalidates the whole tree it hangs
--    from, so every Settings menu in the database fails at once - CRM, Project,
--    Purchase, HR, Attendances, Inventory, Website, Manufacturing, Sales,
--    Maintenance, Planning. One view, eleven failures.
--
--    Note the block still EXISTS in 19.0, in base_setup's settings view, which
--    carries priority 0 and so applies before anything else. Why the xpath
--    misses it here is a question about this database, not about 19.0 - hence
--    the priority and inherit_id columns below. Whatever the reason, the view
--    cannot apply during the upgrade, and switching it off is what unblocks it;
--    the customisation gets rebuilt in Studio on 19.0 afterwards.
--
-- 2. Studio models with no ir.model.access rows at all. On 18.0 that quietly
--    worked out; on 19.0 reading a relation to one raises AccessError, which is
--    what breaks 'Store > Transaction' through x_transaction.x_studio_item_3 ->
--    x_items_ordered. This script REPORTS those - granting access is a security
--    decision, and section 3 below prints the statement to run once you have
--    decided which group should have it.
--
-- Core views are never touched: only views that studio_customization owns, or
-- that nothing owns, are switched off.

\echo ''
\echo '=== 1. views referencing the user_default_rights block'

SELECT v.id,
       COALESCE(d.module || '.' || d.name, '(no xml_id)') AS xml_id,
       v.priority,
       v.inherit_id,
       COALESCE(pd.module || '.' || pd.name, '-') AS inherits_from,
       v.active
FROM ir_ui_view v
LEFT JOIN ir_model_data d  ON d.model  = 'ir.ui.view' AND d.res_id  = v.id
LEFT JOIN ir_model_data pd ON pd.model = 'ir.ui.view' AND pd.res_id = v.inherit_id
WHERE v.arch_db::text LIKE '%user_default_rights%'
ORDER BY v.priority, v.id;

\echo '--- the xpath itself, from each non-core view above'

SELECT v.id,
       substring(v.arch_db::text
                 from position('user_default_rights' in v.arch_db::text) - 120
                 for 260) AS around_the_xpath
FROM ir_ui_view v
LEFT JOIN ir_model_data d ON d.model = 'ir.ui.view' AND d.res_id = v.id
WHERE v.arch_db::text LIKE '%user_default_rights%'
  AND (d.id IS NULL OR d.module = 'studio_customization')
ORDER BY v.id;

\echo '--- switching off the non-core ones and recording them'

WITH doomed AS (
    SELECT v.id
    FROM ir_ui_view v
    LEFT JOIN ir_model_data d ON d.model = 'ir.ui.view' AND d.res_id = v.id
    WHERE v.active
      AND v.arch_db::text LIKE '%user_default_rights%'
      -- never a core view: only Studio's, or one nothing owns
      AND (d.id IS NULL OR d.module = 'studio_customization')
), merged AS (
    SELECT string_agg(x::text, ',' ORDER BY x) AS ids
    FROM (
        SELECT id AS x FROM doomed
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

UPDATE ir_ui_view v SET active = false
FROM (
    SELECT v2.id
    FROM ir_ui_view v2
    LEFT JOIN ir_model_data d ON d.model = 'ir.ui.view' AND d.res_id = v2.id
    WHERE v2.active
      AND v2.arch_db::text LIKE '%user_default_rights%'
      AND (d.id IS NULL OR d.module = 'studio_customization')
) sel
WHERE v.id = sel.id;

\echo ''
\echo '=== 2. any OTHER non-core view inheriting the settings form'
\echo '    (same failure mode - one bad xpath takes every Settings menu down)'

SELECT v.id,
       COALESCE(d.module || '.' || d.name, '(no xml_id)') AS xml_id,
       v.name,
       v.active
FROM ir_ui_view v
LEFT JOIN ir_model_data d ON d.model = 'ir.ui.view' AND d.res_id = v.id
WHERE v.model = 'res.config.settings'
  AND v.inherit_id IS NOT NULL
  AND v.active
  AND (d.id IS NULL OR d.module = 'studio_customization')
ORDER BY v.id;

\echo ''
\echo '=== 3. Studio models with no access rules at all'
\echo '    (reading a relation to one raises AccessError on 19.0)'

SELECT m.id, m.model, m.name->>'en_US' AS label
FROM ir_model m
WHERE m.model LIKE 'x\_%'
  AND m.state = 'manual'
  AND NOT EXISTS (SELECT 1 FROM ir_model_access a WHERE a.model_id = m.id)
ORDER BY m.model;

\echo ''
\echo '    To grant internal users read access to one of them, run:'
\echo '      INSERT INTO ir_model_access'
\echo '        (name, model_id, group_id, perm_read, perm_write, perm_create, perm_unlink, active)'
\echo '      SELECT ''access_'' || m.model, m.id,'
\echo '        (SELECT res_id FROM ir_model_data'
\echo '          WHERE module = ''base'' AND name = ''group_user''),'
\echo '        true, false, false, false, true'
\echo '      FROM ir_model m WHERE m.model = ''x_items_ordered'';'

\echo ''
\echo '=== result'
SELECT value AS recorded_view_ids
FROM ir_config_parameter
WHERE key = 'ssc.pre_upgrade.deactivated_view_ids';
