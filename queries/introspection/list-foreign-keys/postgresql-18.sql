SELECT
    n.nspname                                             AS schema_name,
    t.relname                                             AS table_name,
    con.conname                                           AS constraint_name,
    k.ord::integer                                        AS column_position,
    a.attname::text                                       AS column_name,
    rn.nspname::text                                      AS referenced_schema,
    rt.relname::text                                      AS referenced_table,
    ra.attname::text                                      AS referenced_column,
    CASE con.confupdtype
        WHEN 'a' THEN 'no-action' WHEN 'r' THEN 'restrict' WHEN 'c' THEN 'cascade'
        WHEN 'n' THEN 'set-null'  WHEN 'd' THEN 'set-default'
    END                                                   AS on_update,
    CASE con.confdeltype
        WHEN 'a' THEN 'no-action' WHEN 'r' THEN 'restrict' WHEN 'c' THEN 'cascade'
        WHEN 'n' THEN 'set-null'  WHEN 'd' THEN 'set-default'
    END                                                   AS on_delete,
    CASE con.confmatchtype WHEN 's' THEN 'simple' WHEN 'f' THEN 'full' WHEN 'p' THEN 'partial' END
                                                          AS match_type,
    con.condeferrable                                     AS is_deferrable,
    con.condeferred                                       AS initially_deferred,
    con.conenforced                                       AS is_enforced
FROM pg_catalog.pg_constraint con
JOIN pg_catalog.pg_class t       ON t.oid = con.conrelid
JOIN pg_catalog.pg_namespace n   ON n.oid = t.relnamespace
JOIN pg_catalog.pg_class rt      ON rt.oid = con.confrelid
JOIN pg_catalog.pg_namespace rn  ON rn.oid = rt.relnamespace
CROSS JOIN LATERAL unnest(con.conkey, con.confkey) WITH ORDINALITY AS k(attnum, refattnum, ord)
JOIN pg_catalog.pg_attribute a   ON a.attrelid = con.conrelid AND a.attnum = k.attnum
JOIN pg_catalog.pg_attribute ra  ON ra.attrelid = con.confrelid AND ra.attnum = k.refattnum
WHERE con.contype = 'f'
  AND n.nspname = :schema
  AND t.relname = :table
ORDER BY con.conname, k.ord
