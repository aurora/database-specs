WITH acl AS (
    SELECT 'database' AS object_type, NULL::text AS schema_name, d.datname::text AS object_name,
           NULL::text AS column_name, a.grantee, a.privilege_type, a.is_grantable
      FROM pg_catalog.pg_database d,
           aclexplode(coalesce(d.datacl, acldefault('d', d.datdba))) a
     WHERE d.datname = current_database()
    UNION ALL
    SELECT 'schema', n.nspname::text, NULL, NULL, a.grantee, a.privilege_type, a.is_grantable
      FROM pg_catalog.pg_namespace n,
           aclexplode(coalesce(n.nspacl, acldefault('n', n.nspowner))) a
     WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
    UNION ALL
    SELECT CASE WHEN c.relkind = 'S' THEN 'sequence' ELSE 'table' END, n.nspname::text, c.relname::text, NULL,
           a.grantee, a.privilege_type, a.is_grantable
      FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace,
           aclexplode(coalesce(c.relacl, acldefault((CASE WHEN c.relkind = 'S' THEN 's' ELSE 'r' END)::"char", c.relowner))) a
     WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
       AND n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
    UNION ALL
    SELECT 'column', n.nspname::text, c.relname::text, att.attname::text, a.grantee, a.privilege_type, a.is_grantable
      FROM pg_catalog.pg_attribute att
      JOIN pg_catalog.pg_class c     ON c.oid = att.attrelid
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace,
           aclexplode(att.attacl) a
     WHERE att.attacl IS NOT NULL AND att.attnum > 0 AND NOT att.attisdropped
       AND n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
    UNION ALL
    SELECT 'routine', n.nspname::text, p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')', NULL,
           a.grantee, a.privilege_type, a.is_grantable
      FROM pg_catalog.pg_proc p
      JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace,
           aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
     WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
)
SELECT
    :grantee::text                                        AS grantee,
    NULL::text                                            AS grantee_host,
    acl.object_type                                       AS object_type,
    acl.schema_name                                       AS schema_name,
    acl.object_name                                       AS object_name,
    acl.column_name                                       AS column_name,
    acl.privilege_type::text                              AS privilege,
    acl.is_grantable                                      AS is_grantable,
    false                                                 AS is_denied
FROM acl
WHERE acl.grantee = COALESCE((SELECT r.oid FROM pg_catalog.pg_roles r WHERE r.rolname = :grantee),
                             CASE WHEN upper(:grantee) = 'PUBLIC' THEN 0::oid END)
ORDER BY object_type, schema_name, object_name, column_name, privilege
