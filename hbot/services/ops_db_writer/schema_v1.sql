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
  fill_key TEXT NOT NULL,
  bot TEXT NOT NULL,
  variant TEXT NOT NULL,
  ts_utc TIMESTAMPTZ NOT NULL,
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
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (fill_key, ts_utc)
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
  PRIMARY KEY (stream, stream_entry_id, ts_utc)
);

CREATE TABLE IF NOT EXISTS event_envelope_ingest_checkpoint (
  checkpoint_id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  source_line BIGINT NOT NULL,
  updated_ts_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS market_depth_raw (
  stream_entry_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  ts_utc TIMESTAMPTZ NOT NULL,
  instance_name TEXT,
  controller_id TEXT,
  connector_name TEXT,
  trading_pair TEXT,
  market_sequence BIGINT,
  payload JSONB NOT NULL,
  source_path TEXT NOT NULL,
  source_line BIGINT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (stream_entry_id, ts_utc)
);

CREATE TABLE IF NOT EXISTS market_depth_sampled (
  stream_entry_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  ts_utc TIMESTAMPTZ NOT NULL,
  instance_name TEXT,
  controller_id TEXT,
  connector_name TEXT,
  trading_pair TEXT,
  depth_levels INTEGER,
  best_bid DOUBLE PRECISION,
  best_ask DOUBLE PRECISION,
  spread_bps DOUBLE PRECISION,
  mid_price DOUBLE PRECISION,
  bid_depth_total DOUBLE PRECISION,
  ask_depth_total DOUBLE PRECISION,
  depth_imbalance DOUBLE PRECISION,
  top_levels JSONB NOT NULL,
  source_path TEXT NOT NULL,
  source_line BIGINT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (stream_entry_id, ts_utc)
);

CREATE TABLE IF NOT EXISTS market_depth_rollup_minute (
  bucket_minute_utc TIMESTAMPTZ NOT NULL,
  instance_name TEXT NOT NULL,
  controller_id TEXT NOT NULL,
  connector_name TEXT NOT NULL,
  trading_pair TEXT NOT NULL,
  event_count INTEGER NOT NULL,
  avg_spread_bps DOUBLE PRECISION,
  avg_mid_price DOUBLE PRECISION,
  avg_bid_depth_total DOUBLE PRECISION,
  avg_ask_depth_total DOUBLE PRECISION,
  avg_depth_imbalance DOUBLE PRECISION,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (bucket_minute_utc, instance_name, controller_id, connector_name, trading_pair)
);

CREATE TABLE IF NOT EXISTS market_depth_ingest_checkpoint (
  checkpoint_id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  source_line BIGINT NOT NULL,
  updated_ts_utc TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS market_quote_raw (
  stream_entry_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  ts_utc TIMESTAMPTZ NOT NULL,
  connector_name TEXT NOT NULL,
  trading_pair TEXT NOT NULL,
  best_bid DOUBLE PRECISION,
  best_ask DOUBLE PRECISION,
  best_bid_size DOUBLE PRECISION,
  best_ask_size DOUBLE PRECISION,
  mid_price DOUBLE PRECISION,
  last_trade_price DOUBLE PRECISION,
  market_sequence BIGINT,
  payload JSONB NOT NULL,
  source_path TEXT NOT NULL,
  source_line BIGINT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (stream_entry_id, ts_utc)
);

CREATE TABLE IF NOT EXISTS market_quote_bar_minute (
  bucket_minute_utc TIMESTAMPTZ NOT NULL,
  connector_name TEXT NOT NULL,
  trading_pair TEXT NOT NULL,
  event_count INTEGER NOT NULL,
  first_ts_utc TIMESTAMPTZ NOT NULL,
  last_ts_utc TIMESTAMPTZ NOT NULL,
  open_price DOUBLE PRECISION NOT NULL,
  high_price DOUBLE PRECISION NOT NULL,
  low_price DOUBLE PRECISION NOT NULL,
  close_price DOUBLE PRECISION NOT NULL,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (bucket_minute_utc, connector_name, trading_pair)
);

CREATE TABLE IF NOT EXISTS market_quote_ingest_checkpoint (
  checkpoint_id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  source_line BIGINT NOT NULL,
  updated_ts_utc TIMESTAMPTZ NOT NULL
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

CREATE TABLE IF NOT EXISTS paper_exchange_open_order_current (
  instance_name TEXT NOT NULL,
  connector_name TEXT NOT NULL,
  trading_pair TEXT NOT NULL,
  order_id TEXT NOT NULL,
  side TEXT,
  order_type TEXT,
  amount_base DOUBLE PRECISION,
  price DOUBLE PRECISION,
  state TEXT,
  created_ts_utc TIMESTAMPTZ,
  updated_ts_utc TIMESTAMPTZ,
  source_ts_utc TIMESTAMPTZ,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (instance_name, connector_name, trading_pair, order_id)
);

CREATE TABLE IF NOT EXISTS bot_position_current (
  instance_name TEXT NOT NULL,
  trading_pair TEXT NOT NULL,
  quantity DOUBLE PRECISION,
  avg_entry_price DOUBLE PRECISION,
  unrealized_pnl_quote DOUBLE PRECISION,
  side TEXT,
  source_ts_utc TIMESTAMPTZ NOT NULL,
  payload JSONB NOT NULL,
  source_path TEXT NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (instance_name, trading_pair)
);

ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS bot_mode TEXT;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS accounting_source TEXT;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS mid DOUBLE PRECISION;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS spread_pct DOUBLE PRECISION;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS net_edge_pct DOUBLE PRECISION;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS turnover_today_x DOUBLE PRECISION;
ALTER TABLE bot_snapshot_minute ADD COLUMN IF NOT EXISTS raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb;
UPDATE bot_snapshot_minute
SET ts_utc = COALESCE(ts_utc, ingest_ts_utc, TIMESTAMPTZ '1970-01-01T00:00:00+00:00')
WHERE ts_utc IS NULL;
ALTER TABLE bot_snapshot_minute ALTER COLUMN ts_utc SET NOT NULL;
DO $$
DECLARE
  v_pk_name TEXT;
  v_pk_def TEXT;
BEGIN
  SELECT c.conname, pg_get_constraintdef(c.oid)
  INTO v_pk_name, v_pk_def
  FROM pg_constraint c
  WHERE c.conrelid = 'bot_snapshot_minute'::regclass
    AND c.contype = 'p'
  LIMIT 1;

  IF v_pk_name IS NULL THEN
    ALTER TABLE bot_snapshot_minute ADD CONSTRAINT bot_snapshot_minute_pkey PRIMARY KEY (bot, variant, ts_utc);
  ELSIF v_pk_def <> 'PRIMARY KEY (bot, variant, ts_utc)' THEN
    EXECUTE format('ALTER TABLE bot_snapshot_minute DROP CONSTRAINT %I', v_pk_name);
    ALTER TABLE bot_snapshot_minute ADD CONSTRAINT bot_snapshot_minute_pkey PRIMARY KEY (bot, variant, ts_utc);
  END IF;
END
$$;

UPDATE bot_daily
SET day_utc = COALESCE(day_utc, (COALESCE(ts_utc, ingest_ts_utc, TIMESTAMPTZ '1970-01-01T00:00:00+00:00'))::date),
    ts_utc = COALESCE(ts_utc, ingest_ts_utc, TIMESTAMPTZ '1970-01-01T00:00:00+00:00')
WHERE day_utc IS NULL OR ts_utc IS NULL;
ALTER TABLE bot_daily ALTER COLUMN day_utc SET NOT NULL;
ALTER TABLE bot_daily ALTER COLUMN ts_utc SET NOT NULL;
DO $$
DECLARE
  v_pk_name TEXT;
  v_pk_def TEXT;
BEGIN
  SELECT c.conname, pg_get_constraintdef(c.oid)
  INTO v_pk_name, v_pk_def
  FROM pg_constraint c
  WHERE c.conrelid = 'bot_daily'::regclass
    AND c.contype = 'p'
  LIMIT 1;

  IF v_pk_name IS NULL THEN
    ALTER TABLE bot_daily ADD CONSTRAINT bot_daily_pkey PRIMARY KEY (bot, variant, day_utc);
  ELSIF v_pk_def <> 'PRIMARY KEY (bot, variant, day_utc)' THEN
    EXECUTE format('ALTER TABLE bot_daily DROP CONSTRAINT %I', v_pk_name);
    ALTER TABLE bot_daily ADD CONSTRAINT bot_daily_pkey PRIMARY KEY (bot, variant, day_utc);
  END IF;
END
$$;

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
UPDATE fills
SET ts_utc = COALESCE(ts_utc, ingest_ts_utc, TIMESTAMPTZ '1970-01-01T00:00:00+00:00')
WHERE ts_utc IS NULL;
ALTER TABLE fills ALTER COLUMN ts_utc SET NOT NULL;
DO $$
DECLARE
  v_pk_name TEXT;
  v_pk_def TEXT;
BEGIN
  SELECT c.conname, pg_get_constraintdef(c.oid)
  INTO v_pk_name, v_pk_def
  FROM pg_constraint c
  WHERE c.conrelid = 'fills'::regclass
    AND c.contype = 'p'
  LIMIT 1;

  IF v_pk_name IS NULL THEN
    ALTER TABLE fills ADD CONSTRAINT fills_pkey PRIMARY KEY (fill_key, ts_utc);
  ELSIF v_pk_def <> 'PRIMARY KEY (fill_key, ts_utc)' THEN
    EXECUTE format('ALTER TABLE fills DROP CONSTRAINT %I', v_pk_name);
    ALTER TABLE fills ADD CONSTRAINT fills_pkey PRIMARY KEY (fill_key, ts_utc);
  END IF;
END
$$;

ALTER TABLE event_envelope_raw ADD COLUMN IF NOT EXISTS event_version TEXT;
ALTER TABLE event_envelope_raw ADD COLUMN IF NOT EXISTS schema_validation_status TEXT;
DO $$
DECLARE
  v_pk_name TEXT;
  v_pk_def TEXT;
BEGIN
  SELECT c.conname, pg_get_constraintdef(c.oid)
  INTO v_pk_name, v_pk_def
  FROM pg_constraint c
  WHERE c.conrelid = 'event_envelope_raw'::regclass
    AND c.contype = 'p'
  LIMIT 1;

  IF v_pk_name IS NULL THEN
    ALTER TABLE event_envelope_raw ADD CONSTRAINT event_envelope_raw_pkey PRIMARY KEY (stream, stream_entry_id, ts_utc);
  ELSIF v_pk_def <> 'PRIMARY KEY (stream, stream_entry_id, ts_utc)' THEN
    EXECUTE format('ALTER TABLE event_envelope_raw DROP CONSTRAINT %I', v_pk_name);
    ALTER TABLE event_envelope_raw ADD CONSTRAINT event_envelope_raw_pkey PRIMARY KEY (stream, stream_entry_id, ts_utc);
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_bot_snapshot_minute_ts_utc ON bot_snapshot_minute (ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_bot_snapshot_minute_pair_ts_utc ON bot_snapshot_minute (exchange, trading_pair, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_bot_snapshot_minute_bot_variant_ts_utc ON bot_snapshot_minute (bot, variant, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_fills_ts_utc ON fills (ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_fills_bot_variant_ts_utc ON fills (bot, variant, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_fills_pair_ts_utc ON fills (exchange, trading_pair, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills (order_id);
CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_ts_utc ON event_envelope_raw (ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_stream_ts_utc ON event_envelope_raw (stream, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_type_ts_utc ON event_envelope_raw (event_type, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_instance_pair_ts_utc ON event_envelope_raw (instance_name, trading_pair, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_corr_ts_utc ON event_envelope_raw (correlation_id, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_event_envelope_raw_event_id ON event_envelope_raw (event_id);
CREATE INDEX IF NOT EXISTS idx_market_depth_raw_ts_utc ON market_depth_raw (ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_market_depth_raw_pair_ts_utc ON market_depth_raw (connector_name, trading_pair, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_market_depth_sampled_ts_utc ON market_depth_sampled (ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_market_depth_sampled_pair_ts_utc ON market_depth_sampled (connector_name, trading_pair, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_market_depth_rollup_pair_bucket ON market_depth_rollup_minute (connector_name, trading_pair, bucket_minute_utc DESC);
CREATE INDEX IF NOT EXISTS idx_market_quote_raw_ts_utc ON market_quote_raw (ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_market_quote_raw_pair_ts_utc ON market_quote_raw (connector_name, trading_pair, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_market_quote_bar_pair_bucket ON market_quote_bar_minute (connector_name, trading_pair, bucket_minute_utc DESC);
CREATE INDEX IF NOT EXISTS idx_paper_exchange_open_order_current_pair_updated
ON paper_exchange_open_order_current (instance_name, trading_pair, updated_ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_bot_position_current_pair_updated
ON bot_position_current (instance_name, trading_pair, source_ts_utc DESC);
