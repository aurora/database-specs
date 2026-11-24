SELECT
    :schema                                               AS schema_name,
    m.name                                                AS view_name,
    trim(substr(m.sql, instr(upper(replace(replace(replace(m.sql, char(10), ' '), char(13), ' '), char(9), ' ')),
                             ' AS ') + 4))                AS definition,
    0                                                     AS is_materialized,
    0                                                     AS is_updatable,
    NULL                                                  AS check_option,
    NULL                                                  AS security_type,
    NULL                                                  AS comment
FROM sqlite_master m
WHERE :schema = 'main'
  AND m.type = 'view'
ORDER BY m.name
