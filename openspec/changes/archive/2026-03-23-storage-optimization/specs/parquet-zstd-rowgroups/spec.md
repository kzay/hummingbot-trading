## ADDED Requirements

### Requirement: Zstd compression for all Parquet writes
All `save_*` functions in `data_store.py` SHALL write Parquet files using Zstd compression instead of Snappy.

#### Scenario: Save candles with Zstd
- **WHEN** `save_candles()` writes a Parquet file
- **THEN** the file's compression codec SHALL be `ZSTD`

#### Scenario: Save trades with Zstd
- **WHEN** `save_trades()` writes a Parquet file
- **THEN** the file's compression codec SHALL be `ZSTD`

#### Scenario: Save funding rates with Zstd
- **WHEN** `save_funding_rates()` writes a Parquet file
- **THEN** the file's compression codec SHALL be `ZSTD`

#### Scenario: Save LS ratio with Zstd
- **WHEN** `save_long_short_ratio()` writes a Parquet file
- **THEN** the file's compression codec SHALL be `ZSTD`

### Requirement: Multiple row groups for predicate pushdown
All `save_*` functions in `data_store.py` SHALL write Parquet files with a `row_group_size` of 100,000 rows.

#### Scenario: Large candle file has multiple row groups
- **WHEN** `save_candles()` writes 640,000 rows
- **THEN** the resulting Parquet file SHALL contain at least 6 row groups

#### Scenario: Small file produces one row group
- **WHEN** `save_candles()` writes 50,000 rows
- **THEN** the resulting Parquet file SHALL contain exactly 1 row group

### Requirement: Backward-compatible reads
All `load_*` functions SHALL read Parquet files regardless of their compression codec (Snappy, Zstd, or uncompressed).

#### Scenario: Read legacy Snappy file
- **WHEN** `load_candles()` reads a Snappy-compressed Parquet file
- **THEN** it SHALL return the same data as if the file were Zstd-compressed

#### Scenario: Read new Zstd file
- **WHEN** `load_candles()` reads a Zstd-compressed Parquet file
- **THEN** it SHALL return valid `CandleRow` objects with correct values

### Requirement: Predicate pushdown available for timestamp-range loaders
Parquet files written by `data_store.py` SHALL retain row-group statistics that allow timestamp-range loaders to use pyarrow predicate pushdown.

#### Scenario: Filtered range loader can skip irrelevant row groups
- **WHEN** a Parquet file with multiple row groups is queried through a timestamp-filtered loader for a 30-day window
- **THEN** pyarrow SHALL be able to skip row groups whose statistics fall completely outside the requested time range

### Requirement: Timeframe-aware candle validation
`validate_candles()` SHALL accept an optional `expected_interval_ms` parameter. When omitted, it SHALL default to 60,000 ms (1m). The gap detection threshold SHALL use this parameter instead of the hardcoded 60,000 ms.

#### Scenario: Validate 5m candles without false gaps
- **WHEN** `validate_candles()` is called with `expected_interval_ms=300_000` on a contiguous 5m candle file
- **THEN** no gap warnings SHALL be produced

#### Scenario: Validate 1m candles with default
- **WHEN** `validate_candles()` is called without `expected_interval_ms` on a contiguous 1m candle file
- **THEN** no gap warnings SHALL be produced (backward compatible)
