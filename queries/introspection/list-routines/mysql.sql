SELECT
    r.ROUTINE_SCHEMA                                      AS schema_name,
    r.ROUTINE_NAME                                        AS routine_name,
    r.SPECIFIC_NAME                                       AS specific_name,
    LOWER(r.ROUTINE_TYPE)                                 AS routine_type,
    (SELECT GROUP_CONCAT(CONCAT_WS(' ', p.PARAMETER_MODE, p.PARAMETER_NAME, p.DTD_IDENTIFIER)
                         ORDER BY p.ORDINAL_POSITION SEPARATOR ', ')
       FROM information_schema.PARAMETERS p
      WHERE p.SPECIFIC_SCHEMA = r.ROUTINE_SCHEMA AND p.SPECIFIC_NAME = r.SPECIFIC_NAME
        AND p.ROUTINE_TYPE = r.ROUTINE_TYPE AND p.ORDINAL_POSITION > 0)
                                                          AS arguments,
    CASE WHEN r.ROUTINE_TYPE = 'FUNCTION' THEN r.DTD_IDENTIFIER END
                                                          AS return_type,
    LOWER(r.ROUTINE_BODY)                                 AS language,
    r.IS_DETERMINISTIC = 'YES'                            AS is_deterministic,
    LOWER(r.SECURITY_TYPE)                                AS security_type,
    r.ROUTINE_DEFINITION                                  AS definition,
    NULLIF(r.ROUTINE_COMMENT, '')                         AS comment
FROM information_schema.ROUTINES r
WHERE r.ROUTINE_SCHEMA = :schema
  AND r.ROUTINE_TYPE IN ('FUNCTION', 'PROCEDURE')
ORDER BY r.ROUTINE_NAME, r.SPECIFIC_NAME
