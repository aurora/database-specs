SELECT
    :schema                                               AS schema_name,
    :table                                                AS table_name,
    il.name                                               AS index_name,
    il."unique"                                           AS is_unique,
    il.origin = 'pk'                                      AS is_primary,
    'btree'                                               AS index_type,
    -- WITHOUT ROWID tables are stored in primary key order: their pk index has no rowid column (cid -1)
    il.origin = 'pk' AND NOT EXISTS (
        SELECT 1 FROM pragma_index_xinfo(il.name, :schema) r WHERE r.cid = -1)
                                                          AS is_clustered,
    ix.seqno + 1                                          AS column_position,
    ix.name                                               AS column_name,
    NULL                                                  AS expression,
    CASE WHEN ix."desc" THEN 'desc' ELSE 'asc' END        AS sort_order,
    NULL                                                  AS nulls_first,
    NULL                                                  AS prefix_length,
    0                                                     AS is_included,
    1                                                     AS is_visible,
    CASE WHEN il.partial THEN
        (SELECT trim(substr(m.sql, instr(upper(m.sql), ' WHERE ') + 7))
           FROM sqlite_master m WHERE m.type = 'index' AND m.name = il.name)
    END                                                   AS predicate,
    NULL                                                  AS comment
FROM pragma_index_list(:table, :schema) il
JOIN pragma_index_xinfo(il.name, :schema) ix
WHERE ix.key = 1
ORDER BY is_primary DESC, il.name, ix.seqno
