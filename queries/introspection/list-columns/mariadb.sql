SELECT
    c.TABLE_SCHEMA                                   AS schema_name,
    c.TABLE_NAME                                     AS table_name,
    c.COLUMN_NAME                                    AS column_name,
    c.ORDINAL_POSITION                               AS ordinal_position,
    c.COLUMN_TYPE                                    AS data_type,
    c.IS_NULLABLE = 'YES'                            AS is_nullable,
    CASE
        WHEN c.IS_GENERATED = 'ALWAYS' THEN NULL
        WHEN c.COLUMN_DEFAULT = 'NULL' THEN NULL
        ELSE c.COLUMN_DEFAULT
    END                                              AS default_raw,
    c.EXTRA LIKE '%auto_increment%'                  AS is_auto_increment,
    NULLIF(c.GENERATION_EXPRESSION, '')              AS generation_expression,
    CASE
        WHEN c.EXTRA LIKE '%STORED GENERATED%'  THEN 'stored'
        WHEN c.EXTRA LIKE '%VIRTUAL GENERATED%' THEN 'virtual'
    END                                              AS generation_kind,
    c.COLLATION_NAME                                 AS collation,
    NULLIF(c.COLUMN_COMMENT, '')                     AS comment
FROM information_schema.COLUMNS c
WHERE c.TABLE_SCHEMA = :schema
  AND c.TABLE_NAME = :table
ORDER BY c.ORDINAL_POSITION
