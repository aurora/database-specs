SELECT
    s.schemaname::text                                    AS schema_name,
    s.sequencename::text                                  AS sequence_name,
    s.data_type::text                                     AS data_type,
    s.start_value                                         AS start_value,
    s.increment_by                                        AS increment,
    s.min_value                                           AS min_value,
    s.max_value                                           AS max_value,
    s.cycle                                               AS is_cycle,
    s.cache_size                                          AS cache_size,
    s.last_value                                          AS last_value,
    ot.relname::text                                      AS owned_by_table,
    oa.attname::text                                      AS owned_by_column
FROM pg_catalog.pg_sequences s
JOIN pg_catalog.pg_namespace sn ON sn.nspname = s.schemaname
JOIN pg_catalog.pg_class sc     ON sc.relnamespace = sn.oid AND sc.relname = s.sequencename
LEFT JOIN pg_catalog.pg_depend d
       ON d.classid = 'pg_catalog.pg_class'::regclass AND d.objid = sc.oid
      AND d.refclassid = 'pg_catalog.pg_class'::regclass AND d.deptype IN ('a', 'i')
LEFT JOIN pg_catalog.pg_class ot     ON ot.oid = d.refobjid
LEFT JOIN pg_catalog.pg_attribute oa ON oa.attrelid = d.refobjid AND oa.attnum = d.refobjsubid
WHERE s.schemaname = :schema
ORDER BY s.sequencename
