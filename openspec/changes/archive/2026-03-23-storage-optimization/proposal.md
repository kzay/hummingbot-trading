## Why

The historical data storage layer uses Snappy-compressed Parquet files written as single row groups, and the backtest/replay read path converts every row to Python `Decimal` objects. Benchmarking shows the Decimal conversion is **72x slower** than the Parquet read itself (5,641 ms vs 78 ms for 640K rows), making it the dominant bottleneck in backtesting and ML dataset assembly. Meanwhile, Snappy compression achieves only 1.35–1.61x ratios on OHLCV data, leaving significant disk savings on the table. Single row groups also prevent predicate pushdown, forcing full-file scans even when only a time window is needed.

## What Changes

- Eliminate most of the Decimal conversion bottleneck on the backtest and replay read paths by adding filtered parquet loaders that use pyarrow predicate pushdown, then converting only the requested window to `CandleRow` / `TradeRow` / `FundingRow`. Preserve the existing `CandleRow` engine boundary for feeds, synthesizers, and adapters.
- Switch Parquet compression from Snappy to Zstd across all persistence functions (`save_candles`, `save_trades`, `save_funding_rates`, `save_long_short_ratio`). Benchmarked at 21% smaller files with equal or faster read times.
- Write multiple row groups (100K rows each) to enable timestamp-based predicate pushdown in pyarrow, reducing range-query times from 49 ms to 21 ms.
- Correct catalog selection semantics so backtest/replay loaders choose the dataset that best covers the requested range instead of the current “narrowest range” heuristic.
- Add a one-shot migration script to re-compress existing Parquet files in-place (Snappy → Zstd + row groups).
- Fix `validate_candles()` to accept the correct expected candle interval so 5m/15m/1h files don't produce thousands of false-positive gap warnings.

## Capabilities

### New Capabilities
- `parquet-zstd-rowgroups`: Zstd compression and multiple row groups for all Parquet persistence, with backward-compatible reads (pyarrow transparently reads Snappy or Zstd).
- `filtered-read-path`: Predicate-pushed parquet loaders for backtesting and replay that avoid full-file scans and only materialize the requested window into existing domain row types.
- `data-migration`: One-shot script to re-compress existing historical data files to the new format.

### Modified Capabilities

## Impact

- `controllers/backtesting/data_store.py` — compression and row-group changes in all `save_*` functions, plus new filtered window loaders for candles, trades, and funding
- `controllers/backtesting/data_store.py` — `validate_candles()` gains a configurable expected interval
- `controllers/backtesting/data_catalog.py` — selection semantics updated for duplicate/superseded datasets and date-window lookups
- `controllers/backtesting/harness.py` — switch from full-file `load_candles()` reads to filtered parquet window loading while preserving `list[CandleRow]` return type
- `controllers/backtesting/replay_harness.py` — same filtered window loading for candles, trades, and funding while preserving existing row-domain types
- `controllers/backtesting/walkforward.py` — ensure the harness contract remains compatible with slicing and temporary parquet generation
- `controllers/ml/research.py` — already uses `load_candles_df()`, no change needed
- Existing Parquet files remain readable (pyarrow reads both Snappy and Zstd); new files are written with Zstd + row groups
- No API or schema changes; all changes are internal to the data layer
