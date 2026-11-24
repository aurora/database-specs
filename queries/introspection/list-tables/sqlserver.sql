SELECT
    s.name                                                AS schema_name,
    o.name                                                AS table_name,
    CASE
        WHEN o.type = 'V'                                 THEN 'view'
        WHEN t.is_external = 1                            THEN 'foreign-table'
        WHEN EXISTS (SELECT 1 FROM sys.indexes i
                     JOIN sys.partition_schemes ps ON ps.data_space_id = i.data_space_id
                     WHERE i.object_id = o.object_id AND i.index_id IN (0, 1))
                                                          THEN 'partitioned-table'
        ELSE 'table'
    END                                                   AS table_type,
    CAST(NULL AS nvarchar(128))                           AS partition_of,
    CASE WHEN t.is_memory_optimized = 1 THEN 'memory-optimized' END
                                                          AS storage_engine,
    (SELECT CAST(SUM(p.rows) AS bigint) FROM sys.partitions p
      WHERE p.object_id = o.object_id AND p.index_id IN (0, 1) AND o.type = 'U')
                                                          AS row_estimate,
    (SELECT CAST(SUM(au.used_pages) AS bigint) * 8192
       FROM sys.partitions p JOIN sys.allocation_units au ON au.container_id = p.partition_id
      WHERE p.object_id = o.object_id AND p.index_id IN (0, 1) AND o.type = 'U')
                                                          AS data_bytes,
    CASE WHEN o.type = 'U' THEN
        COALESCE((SELECT CAST(SUM(au.used_pages) AS bigint) * 8192
                    FROM sys.partitions p JOIN sys.allocation_units au ON au.container_id = p.partition_id
                   WHERE p.object_id = o.object_id AND p.index_id > 1), 0)
    END                                                   AS index_bytes,
    CAST(NULL AS nvarchar(128))                           AS collation,
    CAST(ep.value AS nvarchar(max))                       AS comment
FROM sys.objects o
JOIN sys.schemas s          ON s.schema_id = o.schema_id
LEFT JOIN sys.tables t      ON t.object_id = o.object_id
LEFT JOIN sys.extended_properties ep ON ep.class = 1 AND ep.major_id = o.object_id
                                    AND ep.minor_id = 0 AND ep.name = 'MS_Description'
WHERE s.name = :schema
  AND o.type IN ('U', 'V')
  AND o.is_ms_shipped = 0
ORDER BY o.name
