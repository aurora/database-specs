SELECT
    s.SEQUENCE_SCHEMA                                     AS schema_name,
    s.SEQUENCE_NAME                                       AS sequence_name,
    s.DATA_TYPE                                           AS data_type,
    CAST(s.START_VALUE AS SIGNED)                         AS start_value,
    CAST(s.INCREMENT AS SIGNED)                           AS increment,
    CAST(s.MINIMUM_VALUE AS SIGNED)                       AS min_value,
    CAST(s.MAXIMUM_VALUE AS SIGNED)                       AS max_value,
    s.CYCLE_OPTION IN ('1', 'YES')                        AS is_cycle,
    CAST(NULL AS SIGNED)                                  AS cache_size,
    CAST(NULL AS SIGNED)                                  AS last_value,
    CAST(NULL AS CHAR)                                    AS owned_by_table,
    CAST(NULL AS CHAR)                                    AS owned_by_column
FROM information_schema.SEQUENCES s
WHERE s.SEQUENCE_SCHEMA = :schema
ORDER BY s.SEQUENCE_NAME
