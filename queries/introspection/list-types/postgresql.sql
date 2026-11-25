SELECT
    n.nspname::text                                       AS schema_name,
    t.typname::text                                       AS type_name,
    CASE t.typtype WHEN 'e' THEN 'enum' WHEN 'd' THEN 'domain' WHEN 'c' THEN 'composite'
                   WHEN 'r' THEN 'range' ELSE 'base' END  AS kind,
    CASE t.typtype WHEN 'd' THEN format_type(t.typbasetype, t.typtypmod)
                   WHEN 'r' THEN (SELECT format_type(rg.rngsubtype, NULL) FROM pg_catalog.pg_range rg
                                   WHERE rg.rngtypid = t.oid) END
                                                          AS base_type,
    CASE WHEN t.typtype = 'e' THEN
        (SELECT json_agg(e.enumlabel ORDER BY e.enumsortorder)::text
           FROM pg_catalog.pg_enum e WHERE e.enumtypid = t.oid) END
                                                          AS enum_values,
    CASE WHEN t.typtype = 'c' THEN
        (SELECT string_agg(quote_ident(a.attname) || ' ' || format_type(a.atttypid, a.atttypmod), ', ' ORDER BY a.attnum)
           FROM pg_catalog.pg_attribute a WHERE a.attrelid = t.typrelid AND a.attnum > 0 AND NOT a.attisdropped) END
                                                          AS attributes,
    CASE WHEN t.typtype = 'd' THEN NOT t.typnotnull END   AS is_nullable,
    t.typdefault                                          AS default_raw,
    CASE WHEN t.typtype = 'd' THEN
        (SELECT string_agg(pg_get_expr(c.conbin, 0), ' AND ' ORDER BY c.conname)
           FROM pg_catalog.pg_constraint c WHERE c.contypid = t.oid AND c.contype = 'c') END
                                                          AS check_expression,
    obj_description(t.oid, 'pg_type')                     AS comment
FROM pg_catalog.pg_type t
JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
LEFT JOIN pg_catalog.pg_class rc ON rc.oid = t.typrelid
WHERE n.nspname = :schema
  AND t.typtype IN ('e', 'd', 'c', 'r', 'b')
  AND (t.typtype <> 'c' OR rc.relkind = 'c')
  AND t.typcategory <> 'A'
ORDER BY t.typname
