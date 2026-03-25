SELECT
  DATE(date_start) AS day,
  COUNT(*) AS value
FROM terminal_session
WHERE date_start >= %(from_date)s
  AND date_start < %(to_date_exclusive)s
  /*ORG_FILTER*/
GROUP BY DATE(date_start)
ORDER BY day ASC;
