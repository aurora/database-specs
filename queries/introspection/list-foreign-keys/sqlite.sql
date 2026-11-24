SELECT
    :schema                                               AS schema_name,
    :table                                                AS table_name,
    'fk_' || :table || '_' || fk.id                       AS constraint_name,
    fk.seq + 1                                            AS column_position,
    fk."from"                                             AS column_name,
    :schema                                               AS referenced_schema,
    fk."table"                                            AS referenced_table,
    COALESCE(fk."to",
             (SELECT p.name FROM pragma_table_info(fk."table", :schema) p WHERE p.pk = fk.seq + 1))
                                                          AS referenced_column,
    lower(replace(fk.on_update, ' ', '-'))                AS on_update,
    lower(replace(fk.on_delete, ' ', '-'))                AS on_delete,
    CASE WHEN fk."match" = 'NONE' THEN NULL ELSE lower(fk."match") END
                                                          AS match_type,
    NULL                                                  AS is_deferrable,
    NULL                                                  AS initially_deferred,
    (SELECT foreign_keys FROM pragma_foreign_keys)        AS is_enforced
FROM pragma_foreign_key_list(:table, :schema) fk
ORDER BY fk.id, fk.seq
