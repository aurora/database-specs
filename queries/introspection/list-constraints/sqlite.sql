SELECT
    :schema                                               AS schema_name,
    :table                                                AS table_name,
    'pk_' || :table                                       AS constraint_name,
    'primary-key'                                         AS constraint_type,
    x.pk                                                  AS column_position,
    x.name                                                AS column_name,
    NULL                                                  AS check_expression,
    (SELECT il.name FROM pragma_index_list(:table, :schema) il WHERE il.origin = 'pk')
                                                          AS index_name,
    1                                                     AS is_enforced,
    0                                                     AS is_deferrable,
    0                                                     AS initially_deferred
FROM pragma_table_info(:table, :schema) x
WHERE x.pk > 0
UNION ALL
SELECT
    :schema, :table, il.name, 'unique', ix.seqno + 1, ix.name, NULL, il.name, 1, 0, 0
FROM pragma_index_list(:table, :schema) il
JOIN pragma_index_xinfo(il.name, :schema) ix
WHERE il.origin = 'u' AND ix.key = 1
ORDER BY 4, 3, 5
