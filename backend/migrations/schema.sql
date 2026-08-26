CREATE TABLE IF NOT EXISTS stock_master (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  stock_code VARCHAR(10) NOT NULL,
  market ENUM('SH','SZ','BJ') NOT NULL,
  stock_name VARCHAR(100) NOT NULL,
  full_code VARCHAR(12) NOT NULL,
  is_st TINYINT(1) NOT NULL DEFAULT 0,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id), UNIQUE KEY uk_stock_code (stock_code), UNIQUE KEY uk_full_code (full_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS stock_daily (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  stock_id BIGINT UNSIGNED NOT NULL,
  trade_date DATE NOT NULL,
  open_price DECIMAL(12,4), close_price DECIMAL(12,4) NOT NULL,
  high_price DECIMAL(12,4), low_price DECIMAL(12,4),
  volume DECIMAL(24,4), amount DECIMAL(24,4),
  amplitude_pct DECIMAL(14,6), change_pct DECIMAL(14,6),
  change_amount DECIMAL(12,4), turnover_pct DECIMAL(14,6),
  data_source VARCHAR(30) NOT NULL DEFAULT 'file',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id), UNIQUE KEY uk_stock_date (stock_id, trade_date),
  KEY idx_daily_date (trade_date),
  CONSTRAINT fk_daily_stock FOREIGN KEY (stock_id) REFERENCES stock_master(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prediction_run (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  model_code VARCHAR(50) NOT NULL DEFAULT 'multi_factor_rank',
  model_version VARCHAR(30) NOT NULL DEFAULT '1.0.0',
  base_date DATE NOT NULL, status ENUM('running','success','failed') NOT NULL DEFAULT 'success',
  top_n INT NOT NULL, ic_days INT, min_history INT, min_amount DECIMAL(24,4),
  backtest_trade_days INT, backtest_sample_count INT,
  backtest_up_rate DECIMAL(14,10), backtest_avg_return DECIMAL(14,10),
  market_avg_return DECIMAL(14,10), excess_return DECIMAL(14,10),
  parameters JSON, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id), UNIQUE KEY uk_prediction_version (model_code, model_version, base_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prediction_factor (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, prediction_run_id BIGINT UNSIGNED NOT NULL,
  factor_code VARCHAR(50) NOT NULL, factor_name VARCHAR(100) NOT NULL,
  mean_ic DECIMAL(14,10), positive_ic_rate DECIMAL(14,10), valid_trade_days INT,
  model_weight DECIMAL(14,10), PRIMARY KEY (id),
  UNIQUE KEY uk_run_factor (prediction_run_id, factor_code),
  CONSTRAINT fk_factor_run FOREIGN KEY (prediction_run_id) REFERENCES prediction_run(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prediction_candidate (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, prediction_run_id BIGINT UNSIGNED NOT NULL,
  stock_id BIGINT UNSIGNED NOT NULL, ranking INT NOT NULL, score DECIMAL(14,8) NOT NULL,
  base_close DECIMAL(12,4), daily_return DECIMAL(14,10), return_5d DECIMAL(14,10),
  volume_ratio_20 DECIMAL(14,10), avg_amount_20 DECIMAL(24,4), volatility_10 DECIMAL(14,10),
  up_probability DECIMAL(14,10), expected_return DECIMAL(14,10),
  return_low_90 DECIMAL(14,10), return_high_90 DECIMAL(14,10),
  target_price DECIMAL(12,4), price_low_90 DECIMAL(12,4), price_high_90 DECIMAL(12,4),
  prediction_confidence DECIMAL(14,10),
  PRIMARY KEY (id), UNIQUE KEY uk_run_stock (prediction_run_id, stock_id),
  UNIQUE KEY uk_run_rank (prediction_run_id, ranking),
  CONSTRAINT fk_candidate_run FOREIGN KEY (prediction_run_id) REFERENCES prediction_run(id) ON DELETE CASCADE,
  CONSTRAINT fk_candidate_stock FOREIGN KEY (stock_id) REFERENCES stock_master(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS candidate_factor (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, candidate_id BIGINT UNSIGNED NOT NULL,
  factor_code VARCHAR(50) NOT NULL, percentile DECIMAL(14,10),
  PRIMARY KEY (id), UNIQUE KEY uk_candidate_factor (candidate_id, factor_code),
  CONSTRAINT fk_candidate_factor FOREIGN KEY (candidate_id) REFERENCES prediction_candidate(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS intraday_run (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, prediction_run_id BIGINT UNSIGNED NOT NULL,
  observed_at DATETIME NOT NULL, data_source VARCHAR(30) NOT NULL,
  candidate_count INT, valid_candidate_count INT, market_stock_count INT,
  market_avg_return DECIMAL(14,10), market_up_rate DECIMAL(14,10), score_rank_ic DECIMAL(14,10),
  PRIMARY KEY (id), UNIQUE KEY uk_intraday_time (prediction_run_id, observed_at),
  CONSTRAINT fk_intraday_run FOREIGN KEY (prediction_run_id) REFERENCES prediction_run(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS intraday_candidate (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, intraday_run_id BIGINT UNSIGNED NOT NULL,
  candidate_id BIGINT UNSIGNED NOT NULL, current_price DECIMAL(12,4), previous_close DECIMAL(12,4),
  current_return DECIMAL(14,10), market_excess DECIMAL(14,10), is_up TINYINT(1),
  PRIMARY KEY (id), UNIQUE KEY uk_intraday_candidate (intraday_run_id, candidate_id),
  CONSTRAINT fk_intraday_detail_run FOREIGN KEY (intraday_run_id) REFERENCES intraday_run(id) ON DELETE CASCADE,
  CONSTRAINT fk_intraday_detail_candidate FOREIGN KEY (candidate_id) REFERENCES prediction_candidate(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS intraday_group_result (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, intraday_run_id BIGINT UNSIGNED NOT NULL, top_n INT NOT NULL,
  candidate_count INT, valid_count INT, up_count INT, down_count INT, flat_count INT,
  up_rate DECIMAL(14,10), avg_return DECIMAL(14,10), median_return DECIMAL(14,10),
  best_return DECIMAL(14,10), worst_return DECIMAL(14,10), market_avg_return DECIMAL(14,10), excess_return DECIMAL(14,10),
  PRIMARY KEY (id), UNIQUE KEY uk_intraday_group (intraday_run_id, top_n),
  CONSTRAINT fk_intraday_group FOREIGN KEY (intraday_run_id) REFERENCES intraday_run(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS verification_run (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, prediction_run_id BIGINT UNSIGNED NOT NULL,
  actual_trade_date DATE NOT NULL, candidate_count INT, verified_count INT, unverified_count INT,
  market_stock_count INT, market_avg_return DECIMAL(14,10), market_up_rate DECIMAL(14,10), score_rank_ic DECIMAL(14,10),
  verified_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (id),
  UNIQUE KEY uk_verification (prediction_run_id, actual_trade_date),
  CONSTRAINT fk_verification_run FOREIGN KEY (prediction_run_id) REFERENCES prediction_run(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS verification_detail (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, verification_run_id BIGINT UNSIGNED NOT NULL,
  candidate_id BIGINT UNSIGNED NOT NULL, base_close DECIMAL(12,4), actual_close DECIMAL(12,4),
  actual_return DECIMAL(14,10), market_excess DECIMAL(14,10), is_up TINYINT(1), verified TINYINT(1),
  PRIMARY KEY (id), UNIQUE KEY uk_verification_detail (verification_run_id, candidate_id),
  CONSTRAINT fk_verification_detail_run FOREIGN KEY (verification_run_id) REFERENCES verification_run(id) ON DELETE CASCADE,
  CONSTRAINT fk_verification_detail_candidate FOREIGN KEY (candidate_id) REFERENCES prediction_candidate(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS verification_group_result (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, verification_run_id BIGINT UNSIGNED NOT NULL, top_n INT NOT NULL,
  candidate_count INT, verified_count INT, up_count INT, down_count INT, flat_count INT,
  up_rate DECIMAL(14,10), avg_return DECIMAL(14,10), median_return DECIMAL(14,10),
  best_return DECIMAL(14,10), worst_return DECIMAL(14,10), market_avg_return DECIMAL(14,10), excess_return DECIMAL(14,10),
  PRIMARY KEY (id), UNIQUE KEY uk_verification_group (verification_run_id, top_n),
  CONSTRAINT fk_verification_group FOREIGN KEY (verification_run_id) REFERENCES verification_run(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS system_job (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  job_type ENUM('collect','predict','verify','intraday','pipeline') NOT NULL,
  status ENUM('pending','running','success','failed') NOT NULL DEFAULT 'pending',
  progress INT NOT NULL DEFAULT 0,
  parameters JSON NULL,
  command_text VARCHAR(1000) NULL,
  log_text MEDIUMTEXT NULL,
  error_message TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME NULL,
  finished_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_job_status_created (status,created_at),
  KEY idx_job_type_created (job_type,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS task_schedule (
  id TINYINT UNSIGNED NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 0,
  run_time TIME NOT NULL DEFAULT '15:20:00',
  weekdays VARCHAR(20) NOT NULL DEFAULT '1,2,3,4,5',
  data_dir VARCHAR(255) NOT NULL DEFAULT 'data',
  data_source ENUM('sina','eastmoney','auto') NOT NULL DEFAULT 'sina',
  top_n INT NOT NULL DEFAULT 30,
  last_trigger_date DATE NULL,
  last_job_id BIGINT UNSIGNED NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_schedule_job FOREIGN KEY (last_job_id) REFERENCES system_job(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO task_schedule(id) VALUES(1);

CREATE TABLE IF NOT EXISTS app_user (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, username VARCHAR(50) NOT NULL,
  password_hash VARCHAR(255) NOT NULL, display_name VARCHAR(100) NOT NULL,
  email VARCHAR(150) NULL, mobile VARCHAR(30) NULL,
  status ENUM('active','disabled','locked') NOT NULL DEFAULT 'active',
  must_change_password TINYINT(1) NOT NULL DEFAULT 0, failed_login_count INT NOT NULL DEFAULT 0,
  locked_until DATETIME NULL, last_login_at DATETIME NULL, last_login_ip VARCHAR(64) NULL,
  password_changed_at DATETIME NULL, created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY(id), UNIQUE KEY uk_user_username(username), UNIQUE KEY uk_user_email(email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS app_role (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, role_code VARCHAR(50) NOT NULL,
  role_name VARCHAR(100) NOT NULL, description VARCHAR(255) NULL,
  is_system TINYINT(1) NOT NULL DEFAULT 0, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(id), UNIQUE KEY uk_role_code(role_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS app_permission (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, permission_code VARCHAR(100) NOT NULL,
  permission_name VARCHAR(100) NOT NULL, permission_group VARCHAR(50) NOT NULL,
  description VARCHAR(255) NULL, PRIMARY KEY(id), UNIQUE KEY uk_permission_code(permission_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS app_user_role (
  user_id BIGINT UNSIGNED NOT NULL, role_id BIGINT UNSIGNED NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id,role_id),
  CONSTRAINT fk_user_role_user FOREIGN KEY(user_id) REFERENCES app_user(id) ON DELETE CASCADE,
  CONSTRAINT fk_user_role_role FOREIGN KEY(role_id) REFERENCES app_role(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS app_role_permission (
  role_id BIGINT UNSIGNED NOT NULL, permission_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY(role_id,permission_id),
  CONSTRAINT fk_role_permission_role FOREIGN KEY(role_id) REFERENCES app_role(id) ON DELETE CASCADE,
  CONSTRAINT fk_role_permission_permission FOREIGN KEY(permission_id) REFERENCES app_permission(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS app_session (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, user_id BIGINT UNSIGNED NOT NULL,
  token_hash CHAR(64) NOT NULL, csrf_token CHAR(64) NOT NULL, expires_at DATETIME NOT NULL,
  revoked_at DATETIME NULL, ip_address VARCHAR(64) NULL, user_agent VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, last_active_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(id), UNIQUE KEY uk_session_token(token_hash), KEY idx_session_user(user_id),
  CONSTRAINT fk_session_user FOREIGN KEY(user_id) REFERENCES app_user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS password_reset_token (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, user_id BIGINT UNSIGNED NOT NULL,
  token_hash CHAR(64) NOT NULL, expires_at DATETIME NOT NULL, used_at DATETIME NULL,
  created_by BIGINT UNSIGNED NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(id), UNIQUE KEY uk_reset_token(token_hash), KEY idx_reset_user(user_id),
  CONSTRAINT fk_reset_user FOREIGN KEY(user_id) REFERENCES app_user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, user_id BIGINT UNSIGNED NULL,
  username VARCHAR(50) NULL, action VARCHAR(100) NOT NULL, resource_type VARCHAR(50) NULL,
  resource_id VARCHAR(100) NULL, request_method VARCHAR(10) NULL, request_path VARCHAR(500) NULL,
  request_ip VARCHAR(64) NULL, success TINYINT(1) NOT NULL, detail JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(id),
  KEY idx_audit_user_time(user_id,created_at), KEY idx_audit_action_time(action,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO app_role(role_code,role_name,description,is_system) VALUES
('admin','管理员','全部系统权限',1),('operator','操作员','执行任务并查看业务数据',1),('viewer','观察员','只读查看业务数据',1);

INSERT IGNORE INTO app_permission(permission_code,permission_name,permission_group) VALUES
('dashboard:view','查看市场总览','业务查看'),('stock:view','查看行情','业务查看'),
('prediction:view','查看预测','业务查看'),('verification:view','查看验证','业务查看'),
('intraday:view','查看盘中观察','业务查看'),('task:view','查看任务与日志','任务'),
('task:collect','拉取行情','任务'),('task:predict','执行预测','任务'),('task:verify','执行验证','任务'),
('task:intraday','执行盘中观察','任务'),('task:pipeline','执行完整流水线','任务'),
('schedule:view','查看定时配置','定时任务'),('schedule:update','修改定时配置','定时任务'),
('user:view','查看用户','账号管理'),('user:create','创建用户','账号管理'),
('user:update','编辑用户','账号管理'),('user:disable','启停用户','账号管理'),
('user:reset_password','重置密码','账号管理'),('role:view','查看角色权限','账号管理'),
('role:manage','管理自定义角色','账号管理'),('session:manage','管理登录设备','账号管理'),
('audit:view','查看审计日志','审计');

INSERT IGNORE INTO app_role_permission(role_id,permission_id)
SELECT r.id,p.id FROM app_role r CROSS JOIN app_permission p WHERE r.role_code='admin';
INSERT IGNORE INTO app_role_permission(role_id,permission_id)
SELECT r.id,p.id FROM app_role r JOIN app_permission p ON p.permission_code IN
('dashboard:view','stock:view','prediction:view','verification:view','intraday:view','task:view','task:collect','task:predict','task:verify','task:intraday','task:pipeline','schedule:view')
WHERE r.role_code='operator';
INSERT IGNORE INTO app_role_permission(role_id,permission_id)
SELECT r.id,p.id FROM app_role r JOIN app_permission p ON p.permission_code IN
('dashboard:view','stock:view','prediction:view','verification:view','intraday:view')
WHERE r.role_code='viewer';
