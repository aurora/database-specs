SELECT
    :schema                                               AS schema_name,
    m.name                                                AS table_name,
    CASE
        WHEN m.type = 'view'                              THEN 'view'
        WHEN m.sql LIKE 'CREATE VIRTUAL TABLE%'           THEN 'virtual-table'
        ELSE 'table'
    END                                                   AS table_type,
    NULL                                                  AS partition_of,
    CASE WHEN m.type = 'table' AND m.sql NOT LIKE 'CREATE VIRTUAL TABLE%' THEN
        CASE WHEN EXISTS (
            SELECT 1 FROM pragma_index_list(m.name) il
             WHERE il.origin = 'pk'
               AND NOT EXISTS (SELECT 1 FROM pragma_index_xinfo(il.name) ix WHERE ix.cid = -1))
             THEN 'without-rowid' ELSE 'rowid' END
    END                                                   AS storage_engine,
    NULL                                                  AS row_estimate,
    NULL                                                  AS data_bytes,
    NULL                                                  AS index_bytes,
    NULL                                                  AS collation,
    NULL                                                  AS comment
FROM sqlite_master m
WHERE :schema = 'main'
  AND m.type IN ('table', 'view')
  AND m.name NOT LIKE 'sqlite\_%' ESCAPE '\'
ORDER BY m.name
