SELECT
    d.datname::text                                       AS database_name,
    d.datistemplate                                       AS is_system,
    pg_get_userbyid(d.datdba)::text                       AS owner,
    pg_encoding_to_char(d.encoding)::text                 AS encoding,
    d.datcollate::text                                    AS collation,
    CASE WHEN has_database_privilege(d.oid, 'CONNECT') THEN pg_database_size(d.oid) END
                                                          AS size_bytes,
    d.datname = current_database()                        AS is_current,
    shobj_description(d.oid, 'pg_database')               AS comment
FROM pg_catalog.pg_database d
ORDER BY d.datname
