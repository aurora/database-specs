SELECT
    s.name                                                AS schema_name,
    o.name                                                AS table_name,
    c.name                                                AS column_name,
    CAST(ROW_NUMBER() OVER (ORDER BY c.column_id) AS int) AS ordinal_position,
    CASE
        WHEN ty.is_user_defined = 1 THEN ty.name
        WHEN ty.name IN ('varchar', 'char', 'varbinary', 'binary')
            THEN ty.name + '(' + CASE WHEN c.max_length = -1 THEN 'max'
                                      ELSE CAST(c.max_length AS varchar(10)) END + ')'
        WHEN ty.name IN ('nvarchar', 'nchar')
            THEN ty.name + '(' + CASE WHEN c.max_length = -1 THEN 'max'
                                      ELSE CAST(c.max_length / 2 AS varchar(10)) END + ')'
        WHEN ty.name IN ('decimal', 'numeric')
            THEN ty.name + '(' + CAST(c.precision AS varchar(10)) + ',' + CAST(c.scale AS varchar(10)) + ')'
        WHEN ty.name IN ('datetime2', 'time', 'datetimeoffset')
            THEN ty.name + '(' + CAST(c.scale AS varchar(10)) + ')'
        ELSE ty.name
    END                                                   AS data_type,
    c.is_nullable                                         AS is_nullable,
    dc.definition                                         AS default_raw,
    c.is_identity                                         AS is_auto_increment,
    cc.definition                                         AS generation_expression,
    CASE WHEN c.is_computed = 1
         THEN CASE WHEN cc.is_persisted = 1 THEN 'stored' ELSE 'virtual' END
    END                                                   AS generation_kind,
    c.collation_name                                      AS collation,
    CAST(ep.value AS nvarchar(max))                       AS comment
FROM sys.columns c
JOIN sys.objects o               ON o.object_id = c.object_id
JOIN sys.schemas s               ON s.schema_id = o.schema_id
JOIN sys.types ty                ON ty.user_type_id = c.user_type_id
LEFT JOIN sys.default_constraints dc ON dc.object_id = c.default_object_id
LEFT JOIN sys.computed_columns cc    ON cc.object_id = c.object_id AND cc.column_id = c.column_id
LEFT JOIN sys.extended_properties ep ON ep.class = 1 AND ep.major_id = c.object_id
                                    AND ep.minor_id = c.column_id AND ep.name = 'MS_Description'
WHERE s.name = :schema
  AND o.name = :table
  AND o.type IN ('U', 'V')
ORDER BY c.column_id
