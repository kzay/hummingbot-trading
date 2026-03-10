CREATE TABLE IF NOT EXISTS market_bar_v2 (
  bucket_minute_utc TIMESTAMPTZ NOT NULL,
  connector_name TEXT NOT NULL,
  trading_pair TEXT NOT NULL,
  bar_source TEXT NOT NULL DEFAULT 'quote_mid',
  bar_interval_s INTEGER NOT NULL DEFAULT 60,
  open_price DOUBLE PRECISION NOT NULL,
  high_price DOUBLE PRECISION NOT NULL,
  low_price DOUBLE PRECISION NOT NULL,
  close_price DOUBLE PRECISION NOT NULL,
  volume_base DOUBLE PRECISION,
  volume_quote DOUBLE PRECISION,
  event_count INTEGER NOT NULL DEFAULT 0,
  first_ts_utc TIMESTAMPTZ NOT NULL,
  last_ts_utc TIMESTAMPTZ NOT NULL,
  ingest_ts_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  schema_version INTEGER NOT NULL DEFAULT 2,
  quality_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (bucket_minute_utc, connector_name, trading_pair, bar_source, bar_interval_s)
);

CREATE INDEX IF NOT EXISTS idx_market_bar_v2_key_bucket
  ON market_bar_v2 (connector_name, trading_pair, bar_source, bar_interval_s, bucket_minute_utc DESC);

ALTER TABLE market_bar_v2
  DROP CONSTRAINT IF EXISTS chk_bar_interval_phase1;

ALTER TABLE market_bar_v2
  ADD CONSTRAINT chk_bar_interval_phase1
  CHECK (bar_interval_s = 60);
