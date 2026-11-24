SELECT
    k.TABLE_SCHEMA                                        AS schema_name,
    k.TABLE_NAME                                          AS table_name,
    k.CONSTRAINT_NAME                                     AS constraint_name,
    k.ORDINAL_POSITION                                    AS column_position,
    k.COLUMN_NAME                                         AS column_name,
    k.REFERENCED_TABLE_SCHEMA                             AS referenced_schema,
    k.REFERENCED_TABLE_NAME                               AS referenced_table,
    k.REFERENCED_COLUMN_NAME                              AS referenced_column,
    LOWER(REPLACE(r.UPDATE_RULE, ' ', '-'))               AS on_update,
    LOWER(REPLACE(r.DELETE_RULE, ' ', '-'))               AS on_delete,
    LOWER(NULLIF(r.MATCH_OPTION, 'NONE'))                 AS match_type,
    FALSE                                                 AS is_deferrable,
    FALSE                                                 AS initially_deferred,
    TRUE                                                  AS is_enforced
FROM information_schema.KEY_COLUMN_USAGE k
JOIN information_schema.REFERENTIAL_CONSTRAINTS r
  ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA
 AND r.CONSTRAINT_NAME   = k.CONSTRAINT_NAME
 AND r.TABLE_NAME        = k.TABLE_NAME
WHERE k.REFERENCED_TABLE_SCHEMA = :schema
  AND k.REFERENCED_TABLE_NAME = :table
ORDER BY k.TABLE_SCHEMA, k.TABLE_NAME, k.CONSTRAINT_NAME, k.ORDINAL_POSITION
