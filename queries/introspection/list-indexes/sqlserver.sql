SELECT
    s.name                                                AS schema_name,
    o.name                                                AS table_name,
    i.name                                                AS index_name,
    i.is_unique                                           AS is_unique,
    i.is_primary_key                                      AS is_primary,
    CASE i.type
        WHEN 1 THEN 'btree'
        WHEN 2 THEN 'btree'
        WHEN 3 THEN 'xml'
        WHEN 4 THEN 'spatial'
        WHEN 5 THEN 'columnstore'
        WHEN 6 THEN 'columnstore'
        WHEN 7 THEN 'hash'
        ELSE LOWER(i.type_desc)
    END                                                   AS index_type,
    CAST(CASE WHEN i.type IN (1, 5) THEN 1 ELSE 0 END AS bit)
                                                          AS is_clustered,
    CAST(ROW_NUMBER() OVER (
        PARTITION BY i.object_id, i.index_id
        ORDER BY ic.is_included_column, ic.key_ordinal, ic.index_column_id) AS int)
                                                          AS column_position,
    c.name                                                AS column_name,
    CAST(NULL AS nvarchar(max))                           AS expression,
    CASE WHEN ic.is_included_column = 1 OR i.type NOT IN (1, 2) THEN NULL
         WHEN ic.is_descending_key = 1 THEN 'desc' ELSE 'asc' END
                                                          AS sort_order,
    CAST(NULL AS bit)                                     AS nulls_first,
    CAST(NULL AS int)                                     AS prefix_length,
    ic.is_included_column                                 AS is_included,
    CAST(CASE WHEN i.is_disabled = 1 THEN 0 ELSE 1 END AS bit)
                                                          AS is_visible,
    i.filter_definition                                   AS predicate,
    CAST(ep.value AS nvarchar(max))                       AS comment
FROM sys.indexes i
JOIN sys.objects o          ON o.object_id = i.object_id
JOIN sys.schemas s          ON s.schema_id = o.schema_id
JOIN sys.index_columns ic   ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c          ON c.object_id = ic.object_id AND c.column_id = ic.column_id
LEFT JOIN sys.extended_properties ep ON ep.class = 7 AND ep.major_id = i.object_id
                                    AND ep.minor_id = i.index_id AND ep.name = 'MS_Description'
WHERE s.name = :schema
  AND o.name = :table
  AND i.type > 0
ORDER BY i.is_primary_key DESC, i.name, column_position
