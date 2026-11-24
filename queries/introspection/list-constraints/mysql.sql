SELECT
    tc.TABLE_SCHEMA                                       AS schema_name,
    tc.TABLE_NAME                                         AS table_name,
    tc.CONSTRAINT_NAME                                    AS constraint_name,
    CASE tc.CONSTRAINT_TYPE WHEN 'PRIMARY KEY' THEN 'primary-key'
                            WHEN 'UNIQUE' THEN 'unique' ELSE 'check' END
                                                          AS constraint_type,
    k.ORDINAL_POSITION                                    AS column_position,
    k.COLUMN_NAME                                         AS column_name,
    cc.CHECK_CLAUSE                                       AS check_expression,
    CASE WHEN tc.CONSTRAINT_TYPE <> 'CHECK' THEN tc.CONSTRAINT_NAME END
                                                          AS index_name,
    tc.ENFORCED = 'YES'                                   AS is_enforced,
    FALSE                                                 AS is_deferrable,
    FALSE                                                 AS initially_deferred
FROM information_schema.TABLE_CONSTRAINTS tc
LEFT JOIN information_schema.KEY_COLUMN_USAGE k
       ON tc.CONSTRAINT_TYPE <> 'CHECK'
      AND k.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND k.TABLE_NAME = tc.TABLE_NAME
      AND k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
LEFT JOIN information_schema.CHECK_CONSTRAINTS cc
       ON tc.CONSTRAINT_TYPE = 'CHECK'
      AND cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
WHERE tc.TABLE_SCHEMA = :schema
  AND tc.TABLE_NAME = :table
  AND tc.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'UNIQUE', 'CHECK')
ORDER BY constraint_type, tc.CONSTRAINT_NAME, k.ORDINAL_POSITION
