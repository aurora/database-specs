SELECT
    t.EVENT_OBJECT_SCHEMA                                 AS schema_name,
    t.EVENT_OBJECT_TABLE                                  AS table_name,
    t.TRIGGER_NAME                                        AS trigger_name,
    LOWER(t.ACTION_TIMING)                                AS timing,
    LOWER(t.EVENT_MANIPULATION)                           AS events,
    LOWER(t.ACTION_ORIENTATION)                           AS level,
    t.ACTION_ORDER                                        AS action_order,
    t.ACTION_CONDITION                                    AS `condition`,
    t.ACTION_STATEMENT                                    AS action_statement,
    TRUE                                                  AS is_enabled
FROM information_schema.TRIGGERS t
WHERE t.EVENT_OBJECT_SCHEMA = :schema
  AND t.EVENT_OBJECT_TABLE = :table
ORDER BY t.TRIGGER_NAME
