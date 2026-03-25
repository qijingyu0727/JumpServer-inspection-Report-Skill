SELECT
  @@hostname AS hostname,
  VERSION() AS version,
  @@version_comment AS version_comment,
  @@port AS port,
  NOW() AS checked_at;
