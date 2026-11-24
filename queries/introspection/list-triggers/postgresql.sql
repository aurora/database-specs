SELECT
    n.nspname                                             AS schema_name,
    c.relname                                             AS table_name,
    t.tgname::text                                        AS trigger_name,
    CASE WHEN t.tgtype & 2 = 2 THEN 'before'
         WHEN t.tgtype & 64 = 64 THEN 'instead-of'
         ELSE 'after' END                                 AS timing,
    concat_ws(',',
        CASE WHEN t.tgtype & 4  = 4  THEN 'insert' END,
        CASE WHEN t.tgtype & 16 = 16 THEN 'update' END,
        CASE WHEN t.tgtype & 8  = 8  THEN 'delete' END,
        CASE WHEN t.tgtype & 32 = 32 THEN 'truncate' END) AS events,
    CASE WHEN t.tgtype & 1 = 1 THEN 'row' ELSE 'statement' END
                                                          AS level,
    NULL::integer                                         AS action_order,
    substring(pg_get_triggerdef(t.oid, true) from ' WHEN \((.*)\) EXECUTE ')
                                                          AS condition,
    substring(pg_get_triggerdef(t.oid, true) from ' (EXECUTE (FUNCTION|PROCEDURE) .*)$')
                                                          AS action_statement,
    t.tgenabled <> 'D'                                    AS is_enabled
FROM pg_catalog.pg_trigger t
JOIN pg_catalog.pg_class c     ON c.oid = t.tgrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :schema
  AND c.relname = :table
  AND NOT t.tgisinternal
ORDER BY t.tgname
