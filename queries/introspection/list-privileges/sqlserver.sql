SELECT
    pr.name                                               AS grantee,
    CAST(NULL AS nvarchar(128))                           AS grantee_host,
    CASE pe.class
        WHEN 0 THEN 'database'
        WHEN 3 THEN 'schema'
        ELSE CASE WHEN pe.minor_id > 0 THEN 'column'
                  WHEN o.type IN ('P', 'PC', 'FN', 'IF', 'TF', 'FS', 'FT', 'AF') THEN 'routine'
                  WHEN o.type = 'SO' THEN 'sequence'
                  ELSE 'table' END
    END                                                   AS object_type,
    CASE pe.class WHEN 3 THEN SCHEMA_NAME(pe.major_id) WHEN 1 THEN OBJECT_SCHEMA_NAME(pe.major_id) END
                                                          AS schema_name,
    CASE pe.class WHEN 0 THEN DB_NAME() WHEN 1 THEN OBJECT_NAME(pe.major_id) END
                                                          AS object_name,
    CASE WHEN pe.class = 1 AND pe.minor_id > 0 THEN COL_NAME(pe.major_id, pe.minor_id) END
                                                          AS column_name,
    pe.permission_name                                    AS privilege,
    CAST(CASE WHEN pe.state = 'W' THEN 1 ELSE 0 END AS bit) AS is_grantable,
    CAST(CASE WHEN pe.state = 'D' THEN 1 ELSE 0 END AS bit) AS is_denied
FROM sys.database_permissions pe
JOIN sys.database_principals pr ON pr.principal_id = pe.grantee_principal_id
LEFT JOIN sys.objects o ON pe.class = 1 AND o.object_id = pe.major_id
WHERE pr.name = :grantee
  AND pe.class IN (0, 1, 3)
UNION ALL
SELECT
    sp.name, NULL, 'global', NULL, NULL, NULL, spe.permission_name,
    CAST(CASE WHEN spe.state = 'W' THEN 1 ELSE 0 END AS bit),
    CAST(CASE WHEN spe.state = 'D' THEN 1 ELSE 0 END AS bit)
FROM sys.server_permissions spe
JOIN sys.server_principals sp ON sp.principal_id = spe.grantee_principal_id
WHERE sp.name = :grantee
  AND spe.class = 100
ORDER BY grantee_host, object_type, schema_name, object_name, column_name, privilege
