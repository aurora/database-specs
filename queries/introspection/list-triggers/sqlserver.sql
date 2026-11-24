SELECT
    s.name                                                AS schema_name,
    o.name                                                AS table_name,
    t.name                                                AS trigger_name,
    CASE WHEN t.is_instead_of_trigger = 1 THEN 'instead-of' ELSE 'after' END
                                                          AS timing,
    CONCAT_WS(',',
        CASE WHEN EXISTS (SELECT 1 FROM sys.trigger_events e WHERE e.object_id = t.object_id AND e.type_desc = 'INSERT') THEN 'insert' END,
        CASE WHEN EXISTS (SELECT 1 FROM sys.trigger_events e WHERE e.object_id = t.object_id AND e.type_desc = 'UPDATE') THEN 'update' END,
        CASE WHEN EXISTS (SELECT 1 FROM sys.trigger_events e WHERE e.object_id = t.object_id AND e.type_desc = 'DELETE') THEN 'delete' END)
                                                          AS events,
    'statement'                                           AS level,
    CAST(NULL AS int)                                     AS action_order,
    CAST(NULL AS nvarchar(max))                           AS condition,
    m.definition                                          AS action_statement,
    CAST(CASE WHEN t.is_disabled = 1 THEN 0 ELSE 1 END AS bit)
                                                          AS is_enabled
FROM sys.triggers t
JOIN sys.objects o  ON o.object_id = t.parent_id
JOIN sys.schemas s  ON s.schema_id = o.schema_id
JOIN sys.sql_modules m ON m.object_id = t.object_id
WHERE t.parent_class = 1
  AND s.name = :schema
  AND o.name = :table
ORDER BY t.name
