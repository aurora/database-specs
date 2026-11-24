SELECT
    n.nspname                                           AS schema_name,
    c.relname                                           AS table_name,
    a.attname                                           AS column_name,
    row_number() OVER (ORDER BY a.attnum)::integer      AS ordinal_position,
    format_type(a.atttypid, a.atttypmod)                AS data_type,
    NOT a.attnotnull                                    AS is_nullable,
    CASE WHEN a.attgenerated = '' THEN pg_get_expr(d.adbin, d.adrelid) END
                                                        AS default_raw,
    (a.attidentity <> ''
        OR coalesce(pg_get_expr(d.adbin, d.adrelid), '') LIKE 'nextval(%')
                                                        AS is_auto_increment,
    CASE WHEN a.attgenerated <> '' THEN pg_get_expr(d.adbin, d.adrelid) END
                                                        AS generation_expression,
    CASE a.attgenerated WHEN 's' THEN 'stored' WHEN 'v' THEN 'virtual' END
                                                        AS generation_kind,
    CASE WHEN a.attcollation <> 0 AND a.attcollation <> t.typcollation
         THEN co.collname::text END                     AS collation,
    col_description(c.oid, a.attnum)                    AS comment
FROM pg_catalog.pg_attribute a
JOIN pg_catalog.pg_class c      ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace n  ON n.oid = c.relnamespace
JOIN pg_catalog.pg_type t       ON t.oid = a.atttypid
LEFT JOIN pg_catalog.pg_attrdef d   ON d.adrelid = a.attrelid AND d.adnum = a.attnum
LEFT JOIN pg_catalog.pg_collation co ON co.oid = a.attcollation
WHERE n.nspname = :schema
  AND c.relname = :table
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum
