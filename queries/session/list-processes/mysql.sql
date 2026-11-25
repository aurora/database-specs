SELECT
    CAST(p.ID AS SIGNED)                                  AS session_id,
    p.USER                                                AS user_name,
    p.HOST                                                AS client_address,
    p.DB                                                  AS database_name,
    CAST(NULL AS CHAR)                                    AS application_name,
    CASE WHEN p.STATE IS NULL OR p.STATE = '' THEN p.COMMAND
         ELSE CONCAT(p.COMMAND, ': ', p.STATE) END        AS state,
    p.INFO                                                AS query,
    CASE WHEN p.COMMAND <> 'Sleep' THEN p.TIME END        AS query_seconds,
    CAST(NULL AS SIGNED)                                  AS blocked_by,
    p.ID = CONNECTION_ID()                                AS is_current
FROM information_schema.PROCESSLIST p
ORDER BY p.ID
