SELECT
    s.name                                                AS schema_name,
    t.name                                                AS type_name,
    CASE WHEN t.is_table_type = 1 THEN 'table-type'
         WHEN t.is_assembly_type = 1 THEN 'base'
         ELSE 'alias' END                                 AS kind,
    CASE WHEN t.is_table_type = 0 AND t.is_assembly_type = 0 THEN
        TYPE_NAME(t.system_type_id)
        + CASE WHEN TYPE_NAME(t.system_type_id) IN ('varchar', 'char', 'varbinary', 'binary')
                    THEN '(' + CASE WHEN t.max_length = -1 THEN 'max' ELSE CAST(t.max_length AS varchar(10)) END + ')'
               WHEN TYPE_NAME(t.system_type_id) IN ('nvarchar', 'nchar')
                    THEN '(' + CASE WHEN t.max_length = -1 THEN 'max' ELSE CAST(t.max_length / 2 AS varchar(10)) END + ')'
               WHEN TYPE_NAME(t.system_type_id) IN ('decimal', 'numeric')
                    THEN '(' + CAST(t.precision AS varchar(10)) + ',' + CAST(t.scale AS varchar(10)) + ')'
               ELSE '' END END                            AS base_type,
    CAST(NULL AS nvarchar(max))                           AS enum_values,
    CASE WHEN t.is_table_type = 1 THEN
        (SELECT STRING_AGG(CAST(QUOTENAME(c.name) + ' ' + TYPE_NAME(c.user_type_id) AS nvarchar(max)), ', ')
                WITHIN GROUP (ORDER BY c.column_id)
           FROM sys.table_types tt JOIN sys.columns c ON c.object_id = tt.type_table_object_id
          WHERE tt.user_type_id = t.user_type_id) END    AS attributes,
    CASE WHEN t.is_table_type = 0 THEN t.is_nullable END  AS is_nullable,
    CAST(NULL AS nvarchar(max))                           AS default_raw,
    CAST(NULL AS nvarchar(max))                           AS check_expression,
    CAST(ep.value AS nvarchar(max))                       AS comment
FROM sys.types t
JOIN sys.schemas s ON s.schema_id = t.schema_id
LEFT JOIN sys.extended_properties ep ON ep.class = 6 AND ep.major_id = t.user_type_id
                                    AND ep.minor_id = 0 AND ep.name = 'MS_Description'
WHERE t.is_user_defined = 1
  AND s.name = :schema
ORDER BY t.name
