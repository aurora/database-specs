SELECT
    s.name                                                AS schema_name,
    t.name                                                AS table_name,
    kc.name                                               AS constraint_name,
    CASE kc.type WHEN 'PK' THEN 'primary-key' ELSE 'unique' END
                                                          AS constraint_type,
    CAST(ic.key_ordinal AS int)                           AS column_position,
    c.name                                                AS column_name,
    CAST(NULL AS nvarchar(max))                           AS check_expression,
    i.name                                                AS index_name,
    CAST(CASE WHEN i.is_disabled = 1 THEN 0 ELSE 1 END AS bit)
                                                          AS is_enforced,
    CAST(0 AS bit)                                        AS is_deferrable,
    CAST(0 AS bit)                                        AS initially_deferred
FROM sys.key_constraints kc
JOIN sys.tables t         ON t.object_id = kc.parent_object_id
JOIN sys.schemas s        ON s.schema_id = t.schema_id
JOIN sys.indexes i        ON i.object_id = kc.parent_object_id AND i.index_id = kc.unique_index_id
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id AND ic.key_ordinal > 0
JOIN sys.columns c        ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE s.name = :schema AND t.name = :table
UNION ALL
SELECT
    s.name, t.name, cc.name, 'check', NULL, NULL, cc.definition, NULL,
    CAST(CASE WHEN cc.is_disabled = 1 THEN 0 ELSE 1 END AS bit),
    CAST(0 AS bit), CAST(0 AS bit)
FROM sys.check_constraints cc
JOIN sys.tables t  ON t.object_id = cc.parent_object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
WHERE s.name = :schema AND t.name = :table
ORDER BY constraint_type, constraint_name, column_position
