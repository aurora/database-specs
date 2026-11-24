SELECT
    t.schema                                              AS schema_name,
    t.name                                                AS table_name,
    CASE t.type WHEN 'view' THEN 'view' WHEN 'virtual' THEN 'virtual-table' ELSE 'table' END
                                                          AS table_type,
    NULL                                                  AS partition_of,
    CASE WHEN t.type = 'table'
         THEN CASE WHEN t.wr THEN 'without-rowid' ELSE 'rowid' END END
                                                          AS storage_engine,
    NULL                                                  AS row_estimate,
    NULL                                                  AS data_bytes,
    NULL                                                  AS index_bytes,
    NULL                                                  AS collation,
    NULL                                                  AS comment
FROM pragma_table_list t
WHERE t.schema = :schema
  AND t.type IN ('table', 'view', 'virtual')
  AND t.name NOT LIKE 'sqlite\_%' ESCAPE '\'
ORDER BY t.name
