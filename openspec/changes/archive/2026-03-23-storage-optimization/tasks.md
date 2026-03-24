## 1. Parquet Compression and Row Groups

- [x] 1.1 In `data_store.py`, change `save_candles()` from `compression="snappy"` to `compression="zstd"` and add `row_group_size=100_000`
- [x] 1.2 In `data_store.py`, change `save_trades()` from `compression="snappy"` to `compression="zstd"` and add `row_group_size=100_000`
- [x] 1.3 In `data_store.py`, change `save_funding_rates()` from `compression="snappy"` to `compression="zstd"` and add `row_group_size=100_000`
- [x] 1.4 In `data_store.py`, change `save_long_short_ratio()` from `compression="snappy"` to `compression="zstd"` and add `row_group_size=100_000`
- [x] 1.5 Verify backward compatibility: write a test that reads an existing Snappy file, re-saves with Zstd, reads again, and confirms identical data

## 2. Timeframe-Aware Validation

- [x] 2.1 Add `expected_interval_ms` parameter to `validate_candles()` signature (default 60,000 ms for backward compatibility)
- [x] 2.2 Update gap detection logic in `validate_candles()` to use `expected_interval_ms` instead of hardcoded 60,000
- [x] 2.3 Update `data_downloader.py` CLI to pass correct `expected_interval_ms` based on resolution string (e.g., `"5m"` → 300,000, `"1h"` → 3,600,000) when calling `validate_candles()` via `download_and_register_candles()`
- [x] 2.4 Write test: `validate_candles()` with `expected_interval_ms=300_000` on contiguous 5m data produces no gap warnings

## 3. Filtered Parquet Loaders

- [x] 3.1 Add `load_candles_window(path, start_ms=None, end_ms=None) -> list[CandleRow]` to `data_store.py` — use pyarrow/parquet timestamp filters to read only the requested window, then materialize `CandleRow` objects
- [x] 3.2 Add `load_trades_window(path, start_ms=None, end_ms=None) -> list[TradeRow]` to `data_store.py` — filtered parquet read, then materialize `TradeRow` objects
- [x] 3.3 Add `load_funding_window(path, start_ms=None, end_ms=None) -> list[FundingRow]` to `data_store.py` — filtered parquet read, then materialize `FundingRow` objects
- [x] 3.4 Ensure filtered loaders preserve chronological ordering by `timestamp_ms`
- [x] 3.5 Write tests for the filtered loaders: verify range filtering, row counts, ordering, and equality with full-load + Python filter behavior

## 4. Catalog Selection Semantics

- [x] 4.1 Update `DataCatalog.find()` or add a new range-aware finder that accepts requested `start_ms` / `end_ms`
- [x] 4.2 Implement selection logic that prefers datasets fully covering the requested window, then widest/newest among remaining matches
- [x] 4.3 Write tests with duplicate/superseded catalog entries to verify correct dataset selection

## 5. Harness and Replay Integration

- [x] 5.1 In `harness.py`, replace full-file `load_candles()` + Python date filtering with range-aware catalog lookup + `load_candles_window()` while preserving `list[CandleRow]` return type
- [x] 5.2 In `replay_harness.py`, replace full-file candle/trade/funding loads with range-aware catalog lookup + `load_candles_window()`, `load_trades_window()`, and `load_funding_window()`
- [x] 5.3 Verify `walkforward.py` remains compatible with `BacktestHarness._load_candles()` output and update tests if needed
- [x] 5.4 Run existing backtest and replay tests to verify behavior is unchanged
- [x] 5.5 Add a benchmark or regression check showing filtered loader performance is materially faster than full-file load + Python filtering on the benchmark dataset

## 6. Data Migration Script

- [x] 6.1 Create `scripts/migrate_parquet_zstd.py` that discovers all `.parquet` files under a given directory, re-writes each with Zstd compression + 100K row groups using atomic tmp-then-rename
- [x] 6.2 Add safety preconditions: fail fast if temporary parquet files or other signs of active writers are present in the target directory
- [x] 6.3 Add row-count and logical-content verification after reload for each migrated file
- [x] 6.4 Add summary report: files migrated, original total size, new total size, savings percentage
- [x] 6.5 Run migration on `data/historical/` only after the directory is quiesced and verify all files are re-compressed
- [x] 6.6 Write test: migration preserves logical table content across repeated runs
