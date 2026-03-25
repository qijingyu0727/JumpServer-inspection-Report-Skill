SELECT
  user AS name,
  COUNT(*) AS value
FROM terminal_session
WHERE date_start >= %(from_date)s
  AND date_start < %(to_date_exclusive)s
  /*ORG_FILTER*/
GROUP BY user
ORDER BY value DESC, name ASC
LIMIT 5;
