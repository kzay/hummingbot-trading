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
  bot_mode TEXT,
  accounting_source TEXT,
  mid DOUBLE PRECISION,
  spread_pct DOUBLE PRECISION,
  net_edge_pct DOUBLE PRECISION,
  turnover_today_x DOUBLE PRECISION,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
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
  exchange TEXT,
  trading_pair TEXT,
  state TEXT,
  price DOUBLE PRECISION,
  amount DOUBLE PRECISION,
  amount_base DOUBLE PRECISION,
  notional_quote DOUBLE PRECISION,
  fee_paid_quote DOUBLE PRECISION,
  fee_quote DOUBLE PRECISION,
  mid_ref DOUBLE PRECISION,
  expected_spread_pct DOUBLE PRECISION,
  adverse_drift_30s DOUBLE PRECISION,
  fee_source TEXT,
  is_maker BOOLEAN,
  realized_pnl_quote DOUBLE PRECISION,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS event_envelope_raw (
  stream TEXT NOT NULL,
  stream_entry_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  event_type TEXT,
  event_version TEXT,
  ts_utc TIMESTAMPTZ NOT NULL,
  producer TEXT,
  instance_name TEXT,
  controller_id TEXT,
  connector_name TEXT,
  trading_pair TEXT,
  correlation_id TEXT,
  schema_validation_status TEXT,
  payload JSONB NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (stream, stream_entry_id)
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

ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS bot_mode TEXT;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS accounting_source TEXT;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS mid DOUBLE PRECISION;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS spread_pct DOUBLE PRECISION;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS net_edge_pct DOUBLE PRECISION;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS turnover_today_x DOUBLE PRECISION;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE fills ADD COLUMN IF NOT EXISTS exchange TEXT;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS trading_pair TEXT;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS state TEXT;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS amount_base DOUBLE PRECISION;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS notional_quote DOUBLE PRECISION;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS fee_quote DOUBLE PRECISION;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS mid_ref DOUBLE PRECISION;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS expected_spread_pct DOUBLE PRECISION;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS adverse_drift_30s DOUBLE PRECISION;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS fee_source TEXT;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS is_maker BOOLEAN;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS realized_pnl_quote DOUBLE PRECISION;
ALTER TABLE fills ADD COLUMN IF NOT EXISTS raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE event_envelope_raw ADD COLUMN IF NOT EXISTS event_version TEXT;
ALTER TABLE event_envelope_raw ADD COLUMN IF NOT EXISTS schema_validation_status TEXT;

CREATE INDEX IF NOT EXISTS idx_bot_snapshot_minute_ts_utc ON bot_snapshot_minute (ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_bot_snapshot_minute_pair_ts_utc ON bot_snapshot_minute (exchange, trading_pair, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_fills_ts_utc ON fills (ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_fills_bot_variant_ts_utc ON fills (bot, variant, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_fills_pair_ts_utc ON fills (exchange, trading_pair, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills (order_id);
CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_ts_utc ON event_envelope_raw (ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_type_ts_utc ON event_envelope_raw (event_type, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_corr_ts_utc ON event_envelope_raw (correlation_id, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_event_id ON event_envelope_raw (event_id);
