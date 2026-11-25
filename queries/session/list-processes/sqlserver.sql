SELECT
    CAST(s.session_id AS int)                             AS session_id,
    s.login_name                                          AS user_name,
    c.client_net_address                                  AS client_address,
    DB_NAME(s.database_id)                                AS database_name,
    NULLIF(s.program_name, '')                            AS application_name,
    COALESCE(r.status, s.status)                          AS state,
    t.text                                                AS query,
    CASE WHEN r.start_time IS NOT NULL THEN DATEDIFF(SECOND, r.start_time, SYSDATETIME()) END
                                                          AS query_seconds,
    CAST(NULLIF(r.blocking_session_id, 0) AS int)         AS blocked_by,
    CAST(CASE WHEN s.session_id = @@SPID THEN 1 ELSE 0 END AS bit)
                                                          AS is_current
FROM sys.dm_exec_sessions s
LEFT JOIN sys.dm_exec_connections c ON c.session_id = s.session_id
LEFT JOIN sys.dm_exec_requests r    ON r.session_id = s.session_id
OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) t
WHERE s.is_user_process = 1
ORDER BY s.session_id
