SELECT
    v.TABLE_SCHEMA                                        AS schema_name,
    v.TABLE_NAME                                          AS view_name,
    NULLIF(v.VIEW_DEFINITION, '')                         AS definition,
    FALSE                                                 AS is_materialized,
    v.IS_UPDATABLE = 'YES'                                AS is_updatable,
    CASE v.CHECK_OPTION WHEN 'LOCAL' THEN 'local' WHEN 'CASCADED' THEN 'cascaded' END
                                                          AS check_option,
    LOWER(v.SECURITY_TYPE)                                AS security_type,
    CAST(NULL AS CHAR)                                    AS comment
FROM information_schema.VIEWS v
WHERE v.TABLE_SCHEMA = :schema
ORDER BY v.TABLE_NAME
