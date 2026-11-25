SELECT
    d.name                                                AS database_name,
    CAST(CASE WHEN d.database_id <= 4 THEN 1 ELSE 0 END AS bit)
                                                          AS is_system,
    SUSER_SNAME(d.owner_sid)                              AS owner,
    CAST(NULL AS nvarchar(128))                           AS encoding,
    d.collation_name                                      AS collation,
    (SELECT CAST(SUM(CAST(f.size AS bigint)) * 8192 AS bigint)
       FROM sys.master_files f WHERE f.database_id = d.database_id)
                                                          AS size_bytes,
    CAST(CASE WHEN d.name = DB_NAME() THEN 1 ELSE 0 END AS bit)
                                                          AS is_current,
    CAST(NULL AS nvarchar(max))                           AS comment
FROM sys.databases d
ORDER BY d.name
