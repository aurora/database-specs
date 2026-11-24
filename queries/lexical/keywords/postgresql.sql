SELECT upper(word) AS word, catcode IN ('R', 'T') AS reserved
FROM pg_get_keywords()
ORDER BY word
