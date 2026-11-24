SELECT UPPER(WORD) AS word, RESERVED = 1 AS reserved
FROM information_schema.KEYWORDS
ORDER BY word
