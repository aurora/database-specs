SELECT
    s.SCHEMA_NAME                                         AS schema_name,
    s.SCHEMA_NAME IN ('information_schema', 'mysql', 'performance_schema', 'sys')
                                                          AS is_system,
    CAST(NULL AS CHAR)                                    AS owner,
    s.DEFAULT_CHARACTER_SET_NAME                          AS default_charset,
    s.DEFAULT_COLLATION_NAME                              AS default_collation,
    NULLIF(s.SCHEMA_COMMENT, '')                          AS comment
FROM information_schema.SCHEMATA s
ORDER BY s.SCHEMA_NAME
