SELECT
    u.User                                                AS user_name,
    NULLIF(u.Host, '')                                    AS host,
    CASE WHEN u.is_role = 'Y' THEN 'role' ELSE 'user' END AS kind,
    u.User IN ('mariadb.sys', 'mysql', 'PUBLIC')          AS is_system,
    u.is_role = 'N' AND COALESCE(JSON_VALUE(g.Priv, '$.account_locked'), 'false') <> 'true'
                                                          AS can_login,
    u.Super_priv = 'Y'                                    AS is_superuser,
    COALESCE(JSON_VALUE(g.Priv, '$.account_locked'), 'false') = 'true'
                                                          AS is_locked,
    NULLIF(u.plugin, '')                                  AS auth_method
FROM mysql.user u
LEFT JOIN mysql.global_priv g ON g.User = u.User AND g.Host = u.Host
ORDER BY u.User, u.Host
