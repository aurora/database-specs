-- definition: the original CREATE VIEW text with everything up to the first stand-alone AS removed
WITH v AS (
    SELECT s.name AS schema_name, o.name AS view_name, o.object_id, m.definition,
           PATINDEX('%[' + CHAR(9) + CHAR(10) + CHAR(13) + ' ]AS[' + CHAR(9) + CHAR(10) + CHAR(13) + ' ]%',
                    m.definition) AS as_pos,
           vw.with_check_option
    FROM sys.views vw
    JOIN sys.objects o  ON o.object_id = vw.object_id
    JOIN sys.schemas s  ON s.schema_id = o.schema_id
    LEFT JOIN sys.sql_modules m ON m.object_id = vw.object_id
    WHERE s.name = :schema
)
SELECT
    v.schema_name                                         AS schema_name,
    v.view_name                                           AS view_name,
    CASE WHEN v.as_pos > 0
         THEN LTRIM(SUBSTRING(v.definition, v.as_pos + 4, LEN(v.definition))) END
                                                          AS definition,
    CAST(0 AS bit)                                        AS is_materialized,
    CAST(NULL AS bit)                                     AS is_updatable,
    CASE WHEN v.with_check_option = 1 THEN 'cascaded' END AS check_option,
    CAST(NULL AS nvarchar(10))                            AS security_type,
    CAST(ep.value AS nvarchar(max))                       AS comment
FROM v
LEFT JOIN sys.extended_properties ep ON ep.class = 1 AND ep.major_id = v.object_id
                                    AND ep.minor_id = 0 AND ep.name = 'MS_Description'
ORDER BY v.view_name
