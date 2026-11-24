SELECT
    n.nspname                                             AS schema_name,
    c.relname                                             AS view_name,
    rtrim(btrim(pg_get_viewdef(c.oid, true)), ';')        AS definition,
    c.relkind = 'm'                                       AS is_materialized,
    CASE WHEN c.relkind = 'm' THEN false ELSE iv.is_updatable = 'YES' END
                                                          AS is_updatable,
    CASE iv.check_option WHEN 'LOCAL' THEN 'local' WHEN 'CASCADED' THEN 'cascaded' END
                                                          AS check_option,
    CASE WHEN c.relkind = 'm' THEN NULL
         WHEN EXISTS (SELECT 1 FROM unnest(c.reloptions) o
                       WHERE lower(o) IN ('security_invoker=true', 'security_invoker=on',
                                          'security_invoker=1', 'security_invoker=yes'))
         THEN 'invoker' ELSE 'definer' END                AS security_type,
    obj_description(c.oid, 'pg_class')                    AS comment
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN information_schema.views iv
       ON iv.table_schema = n.nspname AND iv.table_name = c.relname
WHERE n.nspname = :schema
  AND c.relkind IN ('v', 'm')
ORDER BY c.relname
