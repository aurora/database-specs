SELECT
    SUBSTRING(g.GRANTEE, 2, LOCATE('''@''', g.GRANTEE) - 2)        AS grantee,
    SUBSTRING(g.GRANTEE, LOCATE('''@''', g.GRANTEE) + 3,
              CHAR_LENGTH(g.GRANTEE) - LOCATE('''@''', g.GRANTEE) - 3) AS grantee_host,
    g.object_type                                         AS object_type,
    g.schema_name                                         AS schema_name,
    g.object_name                                         AS object_name,
    g.column_name                                         AS column_name,
    g.privilege                                           AS privilege,
    g.is_grantable                                        AS is_grantable,
    FALSE                                                 AS is_denied
FROM (
    SELECT p.GRANTEE, 'global' AS object_type, CAST(NULL AS CHAR(64)) AS schema_name,
           CAST(NULL AS CHAR(64)) AS object_name, CAST(NULL AS CHAR(64)) AS column_name,
           p.PRIVILEGE_TYPE AS privilege, p.IS_GRANTABLE = 'YES' AS is_grantable
      FROM information_schema.USER_PRIVILEGES p
    UNION ALL
    SELECT p.GRANTEE, 'schema', p.TABLE_SCHEMA, NULL, NULL, p.PRIVILEGE_TYPE, p.IS_GRANTABLE = 'YES'
      FROM information_schema.SCHEMA_PRIVILEGES p
    UNION ALL
    SELECT p.GRANTEE, 'table', p.TABLE_SCHEMA, p.TABLE_NAME, NULL, p.PRIVILEGE_TYPE, p.IS_GRANTABLE = 'YES'
      FROM information_schema.TABLE_PRIVILEGES p
    UNION ALL
    SELECT p.GRANTEE, 'column', p.TABLE_SCHEMA, p.TABLE_NAME, p.COLUMN_NAME, p.PRIVILEGE_TYPE, p.IS_GRANTABLE = 'YES'
      FROM information_schema.COLUMN_PRIVILEGES p
    UNION ALL
    SELECT CONCAT('''', r.User, '''@''', r.Host, ''''), 'routine', r.Db, r.Routine_name, NULL,
           'EXECUTE', FIND_IN_SET('Grant', r.Proc_priv) > 0
      FROM mysql.procs_priv r WHERE FIND_IN_SET('Execute', r.Proc_priv) > 0
    UNION ALL
    SELECT CONCAT('''', r.User, '''@''', r.Host, ''''), 'routine', r.Db, r.Routine_name, NULL,
           'ALTER ROUTINE', FIND_IN_SET('Grant', r.Proc_priv) > 0
      FROM mysql.procs_priv r WHERE FIND_IN_SET('Alter Routine', r.Proc_priv) > 0
) g
WHERE SUBSTRING(g.GRANTEE, 2, LOCATE('''@''', g.GRANTEE) - 2) = :grantee
ORDER BY grantee_host, object_type, schema_name, object_name, column_name, privilege
