SELECT
  (SELECT COUNT(*) FROM audits_userloginlog
    WHERE datetime >= %(from_90)s
      AND datetime < %(to_date_exclusive)s
      AND status = 1
      /*ORG_FILTER_LOGIN*/) AS login_users_90d_events,
  (SELECT COUNT(DISTINCT username) FROM audits_userloginlog
    WHERE datetime >= %(from_90)s
      AND datetime < %(to_date_exclusive)s
      AND status = 1
      /*ORG_FILTER_LOGIN*/) AS login_users_90d,
  (SELECT COUNT(*) FROM terminal_session
    WHERE date_start >= %(from_90)s
      AND date_start < %(to_date_exclusive)s
      /*ORG_FILTER*/) AS asset_logins_90d,
  (SELECT COUNT(*) FROM audits_ftplog
    WHERE date_start >= %(from_90)s
      AND date_start < %(to_date_exclusive)s
      /*ORG_FILTER_FTP*/) AS ftp_uploads_90d,
  (SELECT COUNT(*) FROM audits_userloginlog
    WHERE datetime >= %(from_30)s
      AND datetime < %(to_date_exclusive)s
      AND status = 1
      /*ORG_FILTER_LOGIN*/) AS login_users_30d_events,
  (SELECT COUNT(DISTINCT username) FROM audits_userloginlog
    WHERE datetime >= %(from_30)s
      AND datetime < %(to_date_exclusive)s
      AND status = 1
      /*ORG_FILTER_LOGIN*/) AS login_users_30d,
  (SELECT COUNT(*) FROM terminal_session
    WHERE date_start >= %(from_30)s
      AND date_start < %(to_date_exclusive)s
      /*ORG_FILTER*/) AS asset_logins_30d,
  (SELECT COUNT(*) FROM audits_ftplog
    WHERE date_start >= %(from_30)s
      AND date_start < %(to_date_exclusive)s
      /*ORG_FILTER_FTP*/) AS ftp_uploads_30d,
  (SELECT COUNT(*) FROM terminal_command
    WHERE FROM_UNIXTIME(timestamp) >= %(from_90)s
      AND FROM_UNIXTIME(timestamp) < %(to_date_exclusive)s
      /*ORG_FILTER_CMD*/) AS command_records_90d,
  (SELECT COUNT(*) FROM terminal_command
    WHERE FROM_UNIXTIME(timestamp) >= %(from_90)s
      AND FROM_UNIXTIME(timestamp) < %(to_date_exclusive)s
      AND risk_level >= 4
      /*ORG_FILTER_CMD*/) AS dangerous_command_records_90d,
  (SELECT COUNT(*) FROM tickets_ticket
    WHERE date_created >= %(from_90)s
      AND date_created < %(to_date_exclusive)s
      /*ORG_FILTER_TICKET*/) AS ticket_requests_90d,
  (SELECT COALESCE(MAX(day_count), 0) FROM (
      SELECT COUNT(*) AS day_count
      FROM audits_userloginlog
      WHERE status = 1
        /*ORG_FILTER_LOGIN_ALL*/
      GROUP BY DATE(datetime)
    ) t) AS max_daily_login_count,
  (SELECT COALESCE(MAX(day_count), 0) FROM (
      SELECT COUNT(*) AS day_count
      FROM terminal_session
      WHERE 1 = 1
        /*ORG_FILTER_ALL*/
      GROUP BY DATE(date_start)
    ) t) AS max_daily_asset_access_count;
