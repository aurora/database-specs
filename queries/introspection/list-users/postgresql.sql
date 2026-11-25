SELECT
    r.rolname::text                                       AS user_name,
    NULL::text                                            AS host,
    CASE WHEN r.rolcanlogin THEN 'user' ELSE 'role' END   AS kind,
    r.rolname LIKE 'pg\_%'                                AS is_system,
    r.rolcanlogin                                         AS can_login,
    r.rolsuper                                            AS is_superuser,
    r.rolvaliduntil IS NOT NULL AND r.rolvaliduntil < now() AS is_locked,
    NULL::text                                            AS auth_method
FROM pg_catalog.pg_roles r
ORDER BY r.rolname
