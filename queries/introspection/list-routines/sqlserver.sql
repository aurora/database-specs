SELECT
    s.name                                                AS schema_name,
    o.name                                                AS routine_name,
    o.name                                                AS specific_name,
    CASE o.type WHEN 'P' THEN 'procedure' WHEN 'PC' THEN 'procedure' WHEN 'AF' THEN 'aggregate'
                ELSE 'function' END                       AS routine_type,
    (SELECT STRING_AGG(CAST(p.name + ' ' + TYPE_NAME(p.user_type_id)
                            + CASE WHEN p.is_output = 1 THEN ' OUTPUT' ELSE '' END AS nvarchar(max)), ', ')
                WITHIN GROUP (ORDER BY p.parameter_id)
       FROM sys.parameters p WHERE p.object_id = o.object_id AND p.parameter_id > 0)
                                                          AS arguments,
    CASE WHEN o.type IN ('IF', 'TF', 'FT') THEN 'TABLE'
         WHEN o.type IN ('FN', 'FS', 'AF')
         THEN (SELECT TYPE_NAME(p.user_type_id) FROM sys.parameters p
                WHERE p.object_id = o.object_id AND p.parameter_id = 0) END
                                                          AS return_type,
    CASE WHEN o.type IN ('FS', 'FT', 'PC', 'AF') THEN 'clr' ELSE 'sql' END
                                                          AS language,
    CASE WHEN o.type = 'P' THEN NULL
         ELSE CAST(OBJECTPROPERTY(o.object_id, 'IsDeterministic') AS bit) END
                                                          AS is_deterministic,
    CASE WHEN m.execute_as_principal_id IS NULL THEN 'invoker' ELSE 'definer' END
                                                          AS security_type,
    m.definition                                          AS definition,
    CAST(ep.value AS nvarchar(max))                       AS comment
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
LEFT JOIN sys.sql_modules m ON m.object_id = o.object_id
LEFT JOIN sys.extended_properties ep ON ep.class = 1 AND ep.major_id = o.object_id
                                    AND ep.minor_id = 0 AND ep.name = 'MS_Description'
WHERE s.name = :schema
  AND o.type IN ('P', 'PC', 'FN', 'IF', 'TF', 'FS', 'FT', 'AF')
  AND o.is_ms_shipped = 0
ORDER BY o.name
