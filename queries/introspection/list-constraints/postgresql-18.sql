SELECT
    n.nspname                                             AS schema_name,
    c.relname                                             AS table_name,
    con.conname::text                                     AS constraint_name,
    CASE con.contype WHEN 'p' THEN 'primary-key' WHEN 'u' THEN 'unique'
                     WHEN 'c' THEN 'check' ELSE 'exclusion' END
                                                          AS constraint_type,
    CASE WHEN con.contype <> 'c' THEN k.ord::integer END  AS column_position,
    CASE WHEN con.contype <> 'c' THEN a.attname::text END AS column_name,
    CASE WHEN con.contype = 'c' THEN pg_get_expr(con.conbin, con.conrelid) END
                                                          AS check_expression,
    CASE WHEN con.contype <> 'c' THEN ic.relname::text END
                                                          AS index_name,
    con.conenforced                                       AS is_enforced,
    con.condeferrable                                     AS is_deferrable,
    con.condeferred                                       AS initially_deferred
FROM pg_catalog.pg_constraint con
JOIN pg_catalog.pg_class c     ON c.oid = con.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN LATERAL unnest(CASE WHEN con.contype <> 'c' THEN con.conkey ELSE ARRAY[NULL::int2] END)
          WITH ORDINALITY AS k(attnum, ord) ON true
LEFT JOIN pg_catalog.pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
LEFT JOIN pg_catalog.pg_class ic    ON ic.oid = con.conindid
WHERE n.nspname = :schema
  AND c.relname = :table
  AND con.contype IN ('p', 'u', 'c', 'x')
ORDER BY constraint_type, con.conname, column_position
