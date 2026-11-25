SELECT
    u.User                                                AS user_name,
    u.Host                                                AS host,
    'user'                                                AS kind,
    u.User LIKE 'mysql.%'                                 AS is_system,
    u.account_locked = 'N'                                AS can_login,
    u.Super_priv = 'Y'                                    AS is_superuser,
    u.account_locked = 'Y'                                AS is_locked,
    u.plugin                                              AS auth_method
FROM mysql.user u
ORDER BY u.User, u.Host
