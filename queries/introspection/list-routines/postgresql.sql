SELECT
    n.nspname                                             AS schema_name,
    p.proname                                             AS routine_name,
    p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
                                                          AS specific_name,
    CASE p.prokind WHEN 'p' THEN 'procedure' WHEN 'a' THEN 'aggregate' WHEN 'w' THEN 'window'
                   ELSE 'function' END                    AS routine_type,
    pg_get_function_arguments(p.oid)                      AS arguments,
    CASE WHEN p.prokind <> 'p' THEN pg_get_function_result(p.oid) END
                                                          AS return_type,
    l.lanname::text                                       AS language,
    p.provolatile = 'i'                                   AS is_deterministic,
    CASE WHEN p.prosecdef THEN 'definer' ELSE 'invoker' END
                                                          AS security_type,
    CASE WHEN p.prokind IN ('f', 'p') AND l.lanname NOT IN ('c', 'internal')
         THEN p.prosrc END                                AS definition,
    obj_description(p.oid, 'pg_proc')                     AS comment
FROM pg_catalog.pg_proc p
JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
JOIN pg_catalog.pg_language l  ON l.oid = p.prolang
WHERE n.nspname = :schema
ORDER BY p.proname, specific_name
