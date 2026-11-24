-- timing, event and condition are read from the stored CREATE TRIGGER text;
-- u is the upper-cased text with whitespace normalized and one leading space (positions shifted by 1)
WITH t AS (
    SELECT m.name, m.tbl_name, m.sql,
           ' ' || upper(replace(replace(replace(m.sql, char(10), ' '), char(13), ' '), char(9), ' ')) || ' ' AS u
    FROM sqlite_master m
    WHERE :schema = 'main' AND m.type = 'trigger' AND m.tbl_name = :table
), p AS (
    SELECT t.*, substr(t.u, 1, instr(t.u, ' ON ')) AS head,
           instr(t.u, ' WHEN ') AS when_pos, instr(t.u, ' BEGIN ') AS begin_pos
    FROM t
)
SELECT
    :schema                                               AS schema_name,
    p.tbl_name                                            AS table_name,
    p.name                                                AS trigger_name,
    CASE WHEN p.head LIKE '% BEFORE %' THEN 'before'
         WHEN p.head LIKE '% INSTEAD OF %' THEN 'instead-of'
         ELSE 'after' END                                 AS timing,
    CASE WHEN p.head LIKE '% INSERT %' THEN 'insert'
         WHEN p.head LIKE '% UPDATE %' THEN 'update'
         ELSE 'delete' END                                AS events,
    'row'                                                 AS level,
    NULL                                                  AS action_order,
    CASE WHEN p.when_pos > 0 AND p.when_pos < p.begin_pos
         THEN trim(substr(p.sql, p.when_pos + 5, p.begin_pos - 1 - (p.when_pos + 5))) END
                                                          AS condition,
    trim(substr(p.sql, p.begin_pos))                      AS action_statement,
    1                                                     AS is_enabled
FROM p
ORDER BY p.name
