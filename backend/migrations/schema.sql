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
