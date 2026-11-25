SELECT
    p.name                                                AS user_name,
    CAST(NULL AS nvarchar(128))                           AS host,
    CASE WHEN p.type = 'R' THEN 'role' ELSE 'login' END   AS kind,
    CAST(CASE WHEN p.is_fixed_role = 1 OR p.name LIKE '##%##' OR p.name LIKE 'NT AUTHORITY\%' OR p.name LIKE 'NT SERVICE\%'
              THEN 1 ELSE 0 END AS bit)                   AS is_system,
    CAST(CASE WHEN p.type IN ('S', 'U', 'G') THEN 1 ELSE 0 END AS bit)
                                                          AS can_login,
    CAST(CASE WHEN p.type <> 'R' AND IS_SRVROLEMEMBER('sysadmin', p.name) = 1 THEN 1 ELSE 0 END AS bit)
                                                          AS is_superuser,
    p.is_disabled                                         AS is_locked,
    CASE p.type WHEN 'S' THEN 'sql-login' WHEN 'U' THEN 'windows-login' WHEN 'G' THEN 'windows-group' END
                                                          AS auth_method
FROM sys.server_principals p
WHERE p.type IN ('S', 'U', 'G', 'R')
ORDER BY p.name
