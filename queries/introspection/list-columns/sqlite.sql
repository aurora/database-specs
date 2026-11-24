WITH pk AS (
    SELECT COUNT(*) AS n FROM pragma_table_info(:table, :schema) WHERE pk > 0
), pk_index AS (
    -- rowid tables with INTEGER PRIMARY KEY have no primary key index
    SELECT COUNT(*) AS n FROM pragma_index_list(:table, :schema) WHERE origin = 'pk'
), cols AS (
    SELECT x.*,
           x.pk = 1 AND upper(x.type) = 'INTEGER'
             AND (SELECT n FROM pk) = 1 AND (SELECT n FROM pk_index) = 0 AS rowid_alias
    FROM pragma_table_xinfo(:table, :schema) x
    WHERE x.hidden <> 1
)
SELECT
    :schema                                               AS schema_name,
    :table                                                AS table_name,
    c.name                                                AS column_name,
    ROW_NUMBER() OVER (ORDER BY c.cid)                    AS ordinal_position,
    c.type                                                AS data_type,
    CASE WHEN c.rowid_alias THEN 0 ELSE c."notnull" = 0 END
                                                          AS is_nullable,
    CASE WHEN c.hidden IN (2, 3) THEN NULL ELSE c.dflt_value END
                                                          AS default_raw,
    c.rowid_alias                                         AS is_auto_increment,
    NULL                                                  AS generation_expression,
    CASE c.hidden WHEN 2 THEN 'virtual' WHEN 3 THEN 'stored' END
                                                          AS generation_kind,
    NULL                                                  AS collation,
    NULL                                                  AS comment
FROM cols c
ORDER BY c.cid
