SELECT
    d.name                                                AS schema_name,
    d.name = 'temp'                                       AS is_system,
    NULL                                                  AS owner,
    (SELECT encoding FROM pragma_encoding)                AS default_charset,
    NULL                                                  AS default_collation,
    NULL                                                  AS comment
FROM pragma_database_list d
ORDER BY d.name
