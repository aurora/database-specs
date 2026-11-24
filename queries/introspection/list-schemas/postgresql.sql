SELECT
    n.nspname                                             AS schema_name,
    n.nspname IN ('pg_catalog', 'information_schema')     AS is_system,
    pg_get_userbyid(n.nspowner)::text                     AS owner,
    NULL::text                                            AS default_charset,
    NULL::text                                            AS default_collation,
    obj_description(n.oid, 'pg_namespace')                AS comment
FROM pg_catalog.pg_namespace n
WHERE n.nspname !~ '^pg_(toast|temp_|toast_temp_)'
ORDER BY n.nspname
