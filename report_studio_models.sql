-- What is actually inside every Studio model that has no access rules.
--
--     psql -P pager=off -f ~/src/user/tools/report_studio_models.sql
--
-- Read only. Nothing is granted, nothing is deleted.
--
-- A Studio model with no ir.model.access row is unreadable to everyone but the
-- superuser on 19.0, which is how 'Store > Transaction' fails the crawler. Each
-- one has to be either granted read or removed, and that is a per-model call -
-- an empty leftover from an abandoned Studio app is not the same thing as a
-- table with ten thousand rows behind a screen people use daily.
--
-- The columns are there to make that call without opening each one:
--
--   rows        how much data would be lost by deleting it
--   fields      how many fields it defines
--   pointed_at  fields on OTHER models with a relation to it - a non-zero
--               number means deleting it breaks those models too
--   views       views built on it
--   actions     window actions opening it
--   menus       menus reaching those actions - zero means nothing in the UI
--               leads here any more

CREATE OR REPLACE FUNCTION pg_temp.rowcount(tbl text) RETURNS bigint AS $$
DECLARE n bigint;
BEGIN
    EXECUTE format('SELECT count(*) FROM %I', tbl) INTO n;
    RETURN n;
EXCEPTION
    -- A model whose table was already dropped: report -1 rather than abort the
    -- whole report on it.
    WHEN undefined_table THEN RETURN -1;
END $$ LANGUAGE plpgsql;

\echo ''
\echo '=== Studio models with no access rules'
\echo ''

SELECT m.model,
       COALESCE(m.name->>'en_US', '') AS label,
       pg_temp.rowcount(m.model) AS rows,
       (SELECT count(*) FROM ir_model_fields f
         WHERE f.model_id = m.id AND f.state = 'manual') AS fields,
       (SELECT count(*) FROM ir_model_fields f
         WHERE f.relation = m.model) AS pointed_at,
       (SELECT count(*) FROM ir_ui_view v
         WHERE v.model = m.model) AS views,
       (SELECT count(*) FROM ir_act_window a
         WHERE a.res_model = m.model) AS actions,
       (SELECT count(*) FROM ir_ui_menu me
         JOIN ir_act_window a ON me.action = 'ir.actions.act_window,' || a.id
         WHERE a.res_model = m.model) AS menus
FROM ir_model m
WHERE m.model LIKE 'x\_%'
  AND m.state = 'manual'
  AND NOT EXISTS (SELECT 1 FROM ir_model_access a WHERE a.model_id = m.id)
ORDER BY pg_temp.rowcount(m.model) DESC, m.model;

\echo ''
\echo '=== the two you named'
\echo ''
\echo '--- x_items_ordered: what points at it'

SELECT f.model AS from_model, f.name AS field, f.ttype, f.state
FROM ir_model_fields f
WHERE f.relation = 'x_items_ordered'
ORDER BY f.model, f.name;

\echo '--- Store > Transaction menus'

SELECT me.id,
       me.name->>'en_US' AS label,
       d.module || '.' || d.name AS xml_id,
       me.active,
       (SELECT count(*) FROM ir_ui_menu c WHERE c.parent_id = me.id) AS children
FROM ir_ui_menu me
JOIN ir_model_data d ON d.model = 'ir.ui.menu' AND d.res_id = me.id
WHERE d.module = 'studio_customization'
  AND d.name LIKE 'store_transaction%';

\echo ''
\echo '=== totals'
SELECT count(*) AS models_without_access
FROM ir_model m
WHERE m.model LIKE 'x\_%'
  AND m.state = 'manual'
  AND NOT EXISTS (SELECT 1 FROM ir_model_access a WHERE a.model_id = m.id);
