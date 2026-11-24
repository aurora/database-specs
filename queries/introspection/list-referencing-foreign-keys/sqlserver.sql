SELECT
    s.name                                                AS schema_name,
    t.name                                                AS table_name,
    fk.name                                               AS constraint_name,
    fkc.constraint_column_id                              AS column_position,
    pc.name                                               AS column_name,
    rs.name                                               AS referenced_schema,
    rt.name                                               AS referenced_table,
    rc.name                                               AS referenced_column,
    REPLACE(LOWER(fk.update_referential_action_desc), '_', '-') AS on_update,
    REPLACE(LOWER(fk.delete_referential_action_desc), '_', '-') AS on_delete,
    CAST(NULL AS nvarchar(10))                            AS match_type,
    CAST(0 AS bit)                                        AS is_deferrable,
    CAST(0 AS bit)                                        AS initially_deferred,
    CAST(CASE WHEN fk.is_disabled = 1 THEN 0 ELSE 1 END AS bit)
                                                          AS is_enforced
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.tables t                ON t.object_id = fk.parent_object_id
JOIN sys.schemas s               ON s.schema_id = t.schema_id
JOIN sys.columns pc              ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
JOIN sys.tables rt               ON rt.object_id = fk.referenced_object_id
JOIN sys.schemas rs              ON rs.schema_id = rt.schema_id
JOIN sys.columns rc              ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
WHERE rs.name = :schema
  AND rt.name = :table
ORDER BY s.name, t.name, fk.name, fkc.constraint_column_id
