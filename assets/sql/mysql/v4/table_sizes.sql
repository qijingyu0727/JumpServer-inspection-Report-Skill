SELECT
  table_name,
  ROUND((data_length + index_length) / 1024 / 1024, 2) AS size_mb,
  table_rows
FROM information_schema.tables
WHERE table_schema = %(db_name)s
ORDER BY (data_length + index_length) DESC
LIMIT 10;
