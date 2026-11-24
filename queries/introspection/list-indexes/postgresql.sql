SELECT
    n.nspname                                             AS schema_name,
    t.relname                                             AS table_name,
    ic.relname                                            AS index_name,
    i.indisunique                                         AS is_unique,
    i.indisprimary                                        AS is_primary,
    am.amname::text                                       AS index_type,
    k.ord::integer                                        AS column_position,
    a.attname::text                                       AS column_name,
    CASE WHEN k.attnum = 0
         THEN pg_get_indexdef(i.indexrelid, k.ord::integer, true) END
                                                          AS expression,
    CASE WHEN k.ord <= i.indnkeyatts AND pg_indexam_has_property(am.oid, 'can_order')
         THEN CASE WHEN i.indoption[k.ord - 1] & 1 = 1 THEN 'desc' ELSE 'asc' END
    END                                                   AS sort_order,
    CASE WHEN k.ord <= i.indnkeyatts AND pg_indexam_has_property(am.oid, 'can_order')
         THEN i.indoption[k.ord - 1] & 2 = 2
    END                                                   AS nulls_first,
    NULL::integer                                         AS prefix_length,
    k.ord > i.indnkeyatts                                 AS is_included,
    true                                                  AS is_visible,
    pg_get_expr(i.indpred, i.indrelid)                    AS predicate,
    obj_description(i.indexrelid, 'pg_class')             AS comment
FROM pg_catalog.pg_index i
JOIN pg_catalog.pg_class ic     ON ic.oid = i.indexrelid
JOIN pg_catalog.pg_class t      ON t.oid = i.indrelid
JOIN pg_catalog.pg_namespace n  ON n.oid = t.relnamespace
JOIN pg_catalog.pg_am am        ON am.oid = ic.relam
CROSS JOIN LATERAL unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord)
LEFT JOIN pg_catalog.pg_attribute a
       ON a.attrelid = i.indrelid AND a.attnum = k.attnum AND k.attnum > 0
WHERE n.nspname = :schema
  AND t.relname = :table
ORDER BY i.indisprimary DESC, ic.relname, k.ord
