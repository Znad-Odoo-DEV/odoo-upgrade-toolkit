-- Everything the Subcontractors Studio app is made of.
--
--     psql -P pager=off -f ~/src/user/tools/inventory_subcontractors_app.sql
--
-- Read only. Nothing is deleted.
--
-- Deleting a Studio app means deleting its models, and a model does not come
-- alone: its fields, the fields on OTHER models that relate to it, its views,
-- actions and menus, and finally its table. Odoo's own delete does all of that
-- in one consistent step, which is why this only takes inventory - the deleting
-- is done from Settings > Technical > Models once the database is on 19.0 and
-- the registry loads again.
--
-- Section 4 is the one to read carefully. A field pointing INTO the app from a
-- model that is not part of it means something outside expects this data to
-- exist. x_items_ordered turned out to be reachable from product.template that
-- way, which is exactly the kind of thing worth knowing before, not after.

CREATE OR REPLACE FUNCTION pg_temp.rowcount(tbl text) RETURNS bigint AS $$
DECLARE n bigint;
BEGIN
    EXECUTE format('SELECT count(*) FROM %I', tbl) INTO n;
    RETURN n;
EXCEPTION WHEN undefined_table THEN RETURN -1;
END $$ LANGUAGE plpgsql;

-- The app's models, matched on the naming Studio gave them. Listed as a table
-- so every later section works off exactly the same set.
CREATE TEMP TABLE app_model AS
SELECT m.id, m.model, m.name->>'en_US' AS label
FROM ir_model m
WHERE m.state = 'manual'
  AND (m.model LIKE 'x\_subcontract%' OR m.model LIKE 'x\_0\_3\_subcontractor%');

\echo ''
\echo '=== 1. models in the app, and what they hold'

SELECT a.model, a.label, pg_temp.rowcount(a.model) AS rows,
       (SELECT count(*) FROM ir_model_fields f WHERE f.model_id = a.id) AS fields
FROM app_model a
ORDER BY pg_temp.rowcount(a.model) DESC, a.model;

SELECT count(*) AS models, sum(pg_temp.rowcount(model)) AS total_rows FROM app_model;

\echo ''
\echo '=== 2. menus that reach it'

SELECT me.id, me.name->>'en_US' AS label, me.active,
       COALESCE(d.module || '.' || d.name, '(no xml_id)') AS xml_id
FROM ir_ui_menu me
LEFT JOIN ir_model_data d ON d.model = 'ir.ui.menu' AND d.res_id = me.id
JOIN ir_act_window w ON me.action = 'ir.actions.act_window,' || w.id
WHERE w.res_model IN (SELECT model FROM app_model)
ORDER BY me.id;

\echo ''
\echo '=== 3. views and actions built on it'

SELECT 'view' AS kind, count(*) FROM ir_ui_view WHERE model IN (SELECT model FROM app_model)
UNION ALL
SELECT 'action', count(*) FROM ir_act_window WHERE res_model IN (SELECT model FROM app_model);

\echo ''
\echo '=== 4. fields pointing INTO the app from outside it'
\echo '    (anything here breaks when the app goes - read this list closely)'

SELECT f.model AS from_model, f.name AS field, f.ttype, f.state, f.relation AS points_at
FROM ir_model_fields f
WHERE f.relation IN (SELECT model FROM app_model)
  AND f.model NOT IN (SELECT model FROM app_model)
ORDER BY f.model, f.name;

\echo ''
\echo '=== 5. fields pointing OUT of the app'
\echo '    (harmless to drop - only the app loses them)'

SELECT f.model AS from_model, f.name AS field, f.ttype, f.relation AS points_at
FROM ir_model_fields f
WHERE f.model IN (SELECT model FROM app_model)
  AND f.relation IS NOT NULL
  AND f.relation NOT IN (SELECT model FROM app_model)
ORDER BY f.model, f.name;

\echo ''
\echo '=== 6. models named "supplier" - part of this app, or their own thing?'
\echo '    Not deleted by any Subcontractors cleanup unless you say so.'

SELECT m.model, m.name->>'en_US' AS label, pg_temp.rowcount(m.model) AS rows,
       (SELECT count(*) FROM ir_ui_menu me
        JOIN ir_act_window w ON me.action = 'ir.actions.act_window,' || w.id
        WHERE w.res_model = m.model) AS menus
FROM ir_model m
WHERE m.state = 'manual'
  AND (m.model LIKE 'x\_supplier%' OR m.model LIKE 'x\_2\_2\_1\_suppliers%')
  AND m.model NOT IN (SELECT model FROM app_model)
ORDER BY m.model;
