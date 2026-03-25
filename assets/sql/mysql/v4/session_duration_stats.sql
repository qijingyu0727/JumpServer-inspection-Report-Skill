SELECT
  COALESCE(MAX(TIMESTAMPDIFF(SECOND, date_start, date_end)), 0) AS max_seconds,
  COALESCE(ROUND(AVG(TIMESTAMPDIFF(SECOND, date_start, date_end))), 0) AS avg_seconds
FROM terminal_session
WHERE date_start >= %(from_date)s
  AND date_start < %(to_date_exclusive)s
  AND date_end IS NOT NULL
  /*ORG_FILTER*/;
