SELECT
    a.pid                                                 AS session_id,
    a.usename::text                                       AS user_name,
    host(a.client_addr)                                   AS client_address,
    a.datname::text                                       AS database_name,
    nullif(a.application_name, '')                       AS application_name,
    a.state                                               AS state,
    a.query                                               AS query,
    CASE WHEN a.state = 'active' THEN floor(extract(epoch FROM now() - a.query_start))::integer END
                                                          AS query_seconds,
    (pg_blocking_pids(a.pid))[1]                          AS blocked_by,
    a.pid = pg_backend_pid()                              AS is_current
FROM pg_catalog.pg_stat_activity a
WHERE a.backend_type = 'client backend'
ORDER BY a.pid
