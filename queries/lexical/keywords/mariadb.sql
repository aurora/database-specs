SELECT UPPER(WORD) AS word, NULL AS reserved
FROM information_schema.KEYWORDS
ORDER BY word
