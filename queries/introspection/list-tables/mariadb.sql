SELECT
    t.TABLE_SCHEMA                                        AS schema_name,
    t.TABLE_NAME                                          AS table_name,
    CASE
        WHEN t.TABLE_TYPE IN ('VIEW', 'SYSTEM VIEW')       THEN 'view'
        WHEN t.CREATE_OPTIONS LIKE '%partitioned%'         THEN 'partitioned-table'
        ELSE 'table'
    END                                                   AS table_type,
    CAST(NULL AS CHAR)                                    AS partition_of,
    t.ENGINE                                              AS storage_engine,
    t.TABLE_ROWS                                          AS row_estimate,
    t.DATA_LENGTH                                         AS data_bytes,
    t.INDEX_LENGTH                                        AS index_bytes,
    t.TABLE_COLLATION                                     AS collation,
    CASE WHEN t.TABLE_TYPE = 'VIEW' THEN NULL
         ELSE NULLIF(t.TABLE_COMMENT, '') END             AS comment
FROM information_schema.TABLES t
WHERE t.TABLE_SCHEMA = :schema
  AND t.TABLE_TYPE NOT IN ('SEQUENCE', 'TEMPORARY')
ORDER BY t.TABLE_NAME
