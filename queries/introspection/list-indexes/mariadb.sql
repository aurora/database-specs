SELECT
    s.TABLE_SCHEMA                                        AS schema_name,
    s.TABLE_NAME                                          AS table_name,
    s.INDEX_NAME                                          AS index_name,
    s.NON_UNIQUE = 0                                      AS is_unique,
    s.INDEX_NAME = 'PRIMARY'                              AS is_primary,
    LOWER(s.INDEX_TYPE)                                   AS index_type,
    s.SEQ_IN_INDEX                                        AS column_position,
    s.COLUMN_NAME                                         AS column_name,
    CAST(NULL AS CHAR)                                    AS expression,
    CASE s.COLLATION WHEN 'A' THEN 'asc' WHEN 'D' THEN 'desc' END
                                                          AS sort_order,
    NULL                                                  AS nulls_first,
    s.SUB_PART                                            AS prefix_length,
    FALSE                                                 AS is_included,
    s.IGNORED = 'NO'                                      AS is_visible,
    CAST(NULL AS CHAR)                                    AS predicate,
    NULLIF(s.INDEX_COMMENT, '')                           AS comment
FROM information_schema.STATISTICS s
WHERE s.TABLE_SCHEMA = :schema
  AND s.TABLE_NAME = :table
ORDER BY s.INDEX_NAME = 'PRIMARY' DESC, s.INDEX_NAME, s.SEQ_IN_INDEX
