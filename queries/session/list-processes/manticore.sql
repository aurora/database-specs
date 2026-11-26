SELECT *, IF(connid = CONNECTION_ID(), 1, 0) AS is_current FROM @@system.sessions ORDER BY connid ASC
