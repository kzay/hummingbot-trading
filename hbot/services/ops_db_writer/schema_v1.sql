CREATE TABLE IF NOT EXISTS bot_snapshot_minute (
  bot TEXT NOT NULL,
  variant TEXT NOT NULL,
  ts_utc TIMESTAMPTZ NOT NULL,
  exchange TEXT,
  trading_pair TEXT,
  state TEXT,
  regime TEXT,
  equity_quote DOUBLE PRECISION,
  base_pct DOUBLE PRECISION,
  target_base_pct DOUBLE PRECISION,
  daily_loss_pct DOUBLE PRECISION,
  drawdown_pct DOUBLE PRECISION,
  cancel_per_min DOUBLE PRECISION,
  orders_active DOUBLE PRECISION,
  fills_count_today DOUBLE PRECISION,
  fees_paid_today_quote DOUBLE PRECISION,
  risk_reasons TEXT,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (bot, variant, ts_utc)
);

CREATE TABLE IF NOT EXISTS bot_daily (
  bot TEXT NOT NULL,
  variant TEXT NOT NULL,
  day_utc DATE NOT NULL,
  ts_utc TIMESTAMPTZ NOT NULL,
  exchange TEXT,
  trading_pair TEXT,
  state TEXT,
  equity_open_quote DOUBLE PRECISION,
  equity_now_quote DOUBLE PRECISION,
  pnl_quote DOUBLE PRECISION,
  pnl_pct DOUBLE PRECISION,
  turnover_x DOUBLE PRECISION,
  fills_count DOUBLE PRECISION,
  ops_events TEXT,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (bot, variant, day_utc)
);

CREATE TABLE IF NOT EXISTS fills (
  fill_key TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  variant TEXT NOT NULL,
  ts_utc TIMESTAMPTZ,
  trade_id TEXT,
  order_id TEXT,
  side TEXT,
  price DOUBLE PRECISION,
  amount DOUBLE PRECISION,
  fee_paid_quote DOUBLE PRECISION,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS exchange_snapshot (
  bot TEXT NOT NULL,
  ts_utc TIMESTAMPTZ NOT NULL,
  exchange TEXT,
  trading_pair TEXT,
  source TEXT,
  equity_quote DOUBLE PRECISION,
  base_pct DOUBLE PRECISION,
  account_probe_status TEXT,
  payload JSONB NOT NULL,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (bot, ts_utc)
);

CREATE TABLE IF NOT EXISTS reconciliation_report (
  ts_utc TIMESTAMPTZ PRIMARY KEY,
  status TEXT,
  critical_count INTEGER,
  warning_count INTEGER,
  payload JSONB NOT NULL,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS accounting_snapshot (
  bot TEXT NOT NULL,
  ts_utc TIMESTAMPTZ NOT NULL,
  exchange TEXT,
  trading_pair TEXT,
  mid DOUBLE PRECISION,
  equity_quote DOUBLE PRECISION,
  base_balance DOUBLE PRECISION,
  quote_balance DOUBLE PRECISION,
  fees_paid_today_quote DOUBLE PRECISION,
  funding_paid_today_quote DOUBLE PRECISION,
  daily_loss_pct DOUBLE PRECISION,
  drawdown_pct DOUBLE PRECISION,
  fee_source TEXT,
  payload JSONB NOT NULL,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (bot, ts_utc)
);

CREATE TABLE IF NOT EXISTS parity_report (
  ts_utc TIMESTAMPTZ PRIMARY KEY,
  status TEXT,
  failed_bots INTEGER,
  checked_bots INTEGER,
  payload JSONB NOT NULL,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_risk_report (
  ts_utc TIMESTAMPTZ PRIMARY KEY,
  status TEXT,
  critical_count INTEGER,
  warning_count INTEGER,
  portfolio_action TEXT,
  payload JSONB NOT NULL,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS promotion_gate_run (
  run_id TEXT PRIMARY KEY,
  ts_utc TIMESTAMPTZ,
  status TEXT,
  critical_failures JSONB,
  payload JSONB NOT NULL,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL
);
