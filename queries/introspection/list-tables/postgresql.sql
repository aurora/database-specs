SELECT
    n.nspname                                             AS schema_name,
    c.relname                                             AS table_name,
    CASE c.relkind
        WHEN 'r' THEN 'table'
        WHEN 'p' THEN 'partitioned-table'
        WHEN 'v' THEN 'view'
        WHEN 'm' THEN 'materialized-view'
        WHEN 'f' THEN 'foreign-table'
    END                                                   AS table_type,
    (SELECT pc.relname::text
       FROM pg_catalog.pg_inherits inh
       JOIN pg_catalog.pg_class pc ON pc.oid = inh.inhparent
      WHERE inh.inhrelid = c.oid AND c.relispartition)    AS partition_of,
    am.amname::text                                       AS storage_engine,
    CASE WHEN c.relkind IN ('r', 'm') AND c.reltuples >= 0
         THEN c.reltuples::bigint END                     AS row_estimate,
    CASE WHEN c.relkind IN ('r', 'm', 'p')
         THEN pg_table_size(c.oid) END                    AS data_bytes,
    CASE WHEN c.relkind IN ('r', 'm', 'p')
         THEN pg_indexes_size(c.oid) END                  AS index_bytes,
    NULL::text                                            AS collation,
    obj_description(c.oid, 'pg_class')                    AS comment
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_catalog.pg_am am  ON am.oid = c.relam
WHERE n.nspname = :schema
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
ORDER BY c.relname
