## ADDED Requirements

### Requirement: Parquet-first seeding on startup
The ML feature service SHALL attempt to seed its rolling window from local parquet files before falling back to the exchange API.

#### Scenario: Parquet available and recent
- **WHEN** the ML feature service starts and a parquet file exists at `{HISTORICAL_DATA_DIR}/{exchange}/{pair}/1m/data.parquet` with data ending within the last 24 hours
- **THEN** the system SHALL read the tail N bars (where N = `ML_ROLLING_WINDOW`) from the parquet, fetch the gap from parquet's last timestamp to now via the exchange API, concatenate and deduplicate by timestamp_ms, and seed the `PairFeatureState` with the combined data

#### Scenario: Parquet available but stale (>24h old)
- **WHEN** the parquet file exists but its last bar is more than 24 hours old
- **THEN** the system SHALL still read the parquet tail, fetch the larger gap via API (up to `ML_ROLLING_WINDOW` bars), and seed with the combined data

#### Scenario: Parquet missing or unreadable
- **WHEN** no parquet file exists for a pair or the file is corrupt
- **THEN** the system SHALL fall back to the existing API-only seed behavior (fetching `ML_WARMUP_BARS` from the exchange API) and log a warning

#### Scenario: API bridge with overlap for deduplication
- **WHEN** the system bridges the gap between parquet and live data
- **THEN** the API fetch SHALL start from `parquet_last_timestamp_ms - 5 minutes` to ensure overlap, and deduplication by timestamp_ms SHALL remove duplicates

### Requirement: Configurable rolling window size
The ML feature service SHALL support a configurable rolling window size via environment variable.

#### Scenario: Custom window size
- **WHEN** `ML_ROLLING_WINDOW=20160` is set
- **THEN** the `PairFeatureState` deque SHALL have `maxlen=20160` and the warmup seed SHALL target 20,160 bars

#### Scenario: Default window size
- **WHEN** `ML_ROLLING_WINDOW` is not set
- **THEN** the system SHALL default to 20,160 bars (14 days of 1m data)

#### Scenario: Feature pipeline coverage
- **WHEN** the rolling window contains 20,160 bars
- **THEN** all feature pipeline indicators SHALL produce valid (non-NaN) values, including `atr_pctl_7d` which requires `rolling(10080)`

### Requirement: Historical data directory configuration
The ML feature service SHALL accept a configurable path for the historical parquet store.

#### Scenario: Custom data directory
- **WHEN** `HISTORICAL_DATA_DIR=/workspace/hbot/data/historical` is set
- **THEN** the system SHALL look for parquet files at `{HISTORICAL_DATA_DIR}/{exchange}/{pair}/1m/data.parquet`

#### Scenario: Default data directory
- **WHEN** `HISTORICAL_DATA_DIR` is not set
- **THEN** the system SHALL default to `data/historical` relative to the working directory

### Requirement: Startup performance
The ML feature service SHALL seed from parquet significantly faster than from the exchange API alone.

#### Scenario: Parquet seed timing
- **WHEN** the system seeds 20,160 bars from a local parquet file
- **THEN** the parquet read SHALL complete in under 2 seconds (excluding the API bridge)

#### Scenario: API-only fallback timing comparison
- **WHEN** the system falls back to API-only seeding of 20,160 bars
- **THEN** the API seed SHALL take approximately 30+ seconds due to pagination and rate limits, demonstrating the performance benefit of parquet-first seeding

### Requirement: Seamless transition to live data
The ML feature service SHALL ensure no gap between historical seed data and the first live bar.

#### Scenario: Gap-free transition
- **WHEN** the system has seeded from parquet + API bridge and begins receiving live trades
- **THEN** the bar builder SHALL produce the next 1m bar contiguously from the last seeded bar, with no missing bars in between

#### Scenario: Duplicate bar handling
- **WHEN** the API bridge and the live bar builder both produce a bar for the same minute
- **THEN** the system SHALL keep the live bar (more accurate) and discard the API-sourced duplicate

### Requirement: Manifest-based startup validation
The ML feature service SHALL validate its data coverage against the data requirements manifest at startup.

#### Scenario: Validates coverage against manifest
- **WHEN** the ML feature service starts and `config/data_requirements.yml` declares `ml_feature_service.lookback_bars: 20160`
- **THEN** the service SHALL compare the number of seeded bars against 20,160 and log whether coverage is sufficient or partial
