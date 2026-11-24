SELECT
    tc.TABLE_SCHEMA                                       AS schema_name,
    tc.TABLE_NAME                                         AS table_name,
    tc.CONSTRAINT_NAME                                    AS constraint_name,
    CASE tc.CONSTRAINT_TYPE WHEN 'PRIMARY KEY' THEN 'primary-key' ELSE 'unique' END
                                                          AS constraint_type,
    k.ORDINAL_POSITION                                    AS column_position,
    k.COLUMN_NAME                                         AS column_name,
    CAST(NULL AS CHAR)                                    AS check_expression,
    tc.CONSTRAINT_NAME                                    AS index_name,
    TRUE                                                  AS is_enforced,
    FALSE                                                 AS is_deferrable,
    FALSE                                                 AS initially_deferred
FROM information_schema.TABLE_CONSTRAINTS tc
JOIN information_schema.KEY_COLUMN_USAGE k
  ON k.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND k.TABLE_NAME = tc.TABLE_NAME
 AND k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
WHERE tc.TABLE_SCHEMA = :schema
  AND tc.TABLE_NAME = :table
  AND tc.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'UNIQUE')
ORDER BY constraint_type, tc.CONSTRAINT_NAME, k.ORDINAL_POSITION
