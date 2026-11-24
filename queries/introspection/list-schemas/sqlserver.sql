SELECT
    s.name                                                AS schema_name,
    CAST(CASE WHEN s.schema_id >= 16384 OR s.name IN ('sys', 'INFORMATION_SCHEMA', 'guest')
              THEN 1 ELSE 0 END AS bit)                   AS is_system,
    USER_NAME(s.principal_id)                             AS owner,
    CAST(NULL AS nvarchar(128))                           AS default_charset,
    CAST(NULL AS nvarchar(128))                           AS default_collation,
    CAST(ep.value AS nvarchar(max))                       AS comment
FROM sys.schemas s
LEFT JOIN sys.extended_properties ep ON ep.class = 3 AND ep.major_id = s.schema_id
                                    AND ep.minor_id = 0 AND ep.name = 'MS_Description'
ORDER BY s.name
