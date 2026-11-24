SELECT
    s.name                                                AS schema_name,
    sq.name                                               AS sequence_name,
    TYPE_NAME(sq.user_type_id)                            AS data_type,
    CAST(sq.start_value AS bigint)                        AS start_value,
    CAST(sq.increment AS bigint)                          AS increment,
    CAST(sq.minimum_value AS bigint)                      AS min_value,
    CAST(sq.maximum_value AS bigint)                      AS max_value,
    sq.is_cycling                                         AS is_cycle,
    sq.cache_size                                         AS cache_size,
    CAST(sq.last_used_value AS bigint)                    AS last_value,
    CAST(NULL AS nvarchar(128))                           AS owned_by_table,
    CAST(NULL AS nvarchar(128))                           AS owned_by_column
FROM sys.sequences sq
JOIN sys.schemas s ON s.schema_id = sq.schema_id
WHERE s.name = :schema
ORDER BY sq.name
