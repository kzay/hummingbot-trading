## Context

The historical data storage layer in `controllers/backtesting/data_store.py` persists OHLCV candles, trades, funding rates, and LS ratios as Parquet files with Snappy compression. The read path has two variants:

1. **`load_candles()` → `list[CandleRow]`**: Reads Parquet, then converts every float64 value to Python `Decimal` via string formatting. Used by backtesting harness, replay harness, and walk-forward engine. Benchmarked at **5,641 ms** for 640K rows.

2. **`load_candles_df()` → `pd.DataFrame`**: Reads Parquet directly into float64 DataFrame. Used by the ML pipeline. Benchmarked at **78 ms** for the same data. **72x faster.**

All files are written as a single row group with Snappy compression, achieving only 1.35–1.61x compression ratios. Single row groups prevent pyarrow's predicate pushdown from skipping irrelevant data during range queries.

Important contract constraints:
- `HistoricalDataFeed` currently accepts `list[CandleRow]` and derives intervals from `CandleRow.timestamp_ms`
- `BookSynthesizer` implementations accept `CandleRow`
- `ReplayPreparedContext` stores `list[CandleRow]`, `list[TradeRow]`, `list[FundingRow]`
- `walkforward.py` slices `BacktestHarness._load_candles()` output and persists those slices back through `save_candles()`
- `DataCatalog.find()` currently prefers the narrowest matching range, which is incorrect for replay/backtest date-window loading when duplicate or superseded datasets exist

Files affected:
- `data_store.py` — 4 save functions, 4 load functions, `validate_candles`
- `harness.py` — imports `load_candles` at lines 27 and 224
- `replay_harness.py` — imports `load_candles`, `load_funding_rates`, `load_trades`
- `data_downloader.py` — imports `load_candles` in 2 places, `save_candles`, `validate_candles`
- `walkforward.py` — imports `save_candles`

## Goals / Non-Goals

**Goals:**
- Eliminate most of the Decimal conversion bottleneck on backtest and replay read paths without breaking the existing `CandleRow`/`TradeRow`/`FundingRow` contracts
- Reduce Parquet file sizes by ~20% via Zstd compression
- Enable timestamp predicate pushdown via multiple row groups (49 ms → 21 ms range queries)
- Maintain full backward compatibility with existing Snappy Parquet files
- Fix false-positive gap warnings in `validate_candles` for non-1m timeframes
- Provide a one-shot migration script for existing data

**Non-Goals:**
- Monthly file partitioning (adds complexity, marginal benefit at <500 MB total data)
- DuckDB or other query engine integration (Parquet reads are already fast enough at this scale)
- Rewriting the whole backtest engine, feed, synthesizer, and replay stack to be DataFrame-native
- Removing the Decimal/domain-row read path entirely
- Changing the directory layout or catalog schema

## Decisions

### 1. Zstd compression with level 3 (default)

**Decision**: Replace `compression="snappy"` with `compression="zstd"` in all `to_parquet()` calls.

**Rationale**: Zstd level 3 is the pyarrow default and provides the best balance. Benchmarked on our actual 1m candle data: 21% smaller files, read time unchanged or slightly faster. Zstd decompression is asymmetric (fast decompress, slower compress) which fits write-once/read-many historical data perfectly.

**Alternatives considered**:
- Zstd level 9–19: diminishing returns (2–5% extra savings) at much higher write cost. Not worth it for <500 MB.
- LZ4: similar ratio to Snappy, no meaningful improvement.
- No compression: wastes disk for no speed gain (compressed reads are faster due to less I/O).

### 2. Row group size of 100,000 rows

**Decision**: Add `row_group_size=100_000` to all `to_parquet()` calls.

**Rationale**: Enables pyarrow predicate pushdown via per-row-group min/max statistics. A 640K-row 1m file gets ~7 row groups, each covering ~69 days of data. A 30-day backtest window touches at most 2 row groups, skipping the rest entirely. Benchmarked: 49 ms → 21 ms for range queries.

**Alternatives considered**:
- 50K rows: more row groups, higher metadata overhead, marginal pushdown improvement.
- 500K rows: too coarse, no effective pushdown on our data volumes.
- Sorted write (explicit sort by timestamp before write): data is already sorted from the downloader, no action needed.

### 3. Filtered parquet loaders at the storage boundary

**Decision**: Keep the engine boundary on `CandleRow`, `TradeRow`, and `FundingRow`, but add filtered parquet loaders that apply pyarrow timestamp filters before materialization. The harness and replay code will request a `[start_ms, end_ms]` window and only convert that subset into domain row objects.

**Rationale**: The current review showed that simply swapping `load_candles()` for `load_candles_df()` is under-scoped because the downstream feed, synthesizer, replay context, and walk-forward code all depend on `list[CandleRow]`. The safer architecture is to optimize at the storage boundary first: skip irrelevant row groups and only build domain objects for the requested window. This captures most of the performance win while preserving existing contracts.

**Alternatives considered**:
- Full DataFrame-native backtesting: too broad for this change; would require redesign of `HistoricalDataFeed`, `BookSynthesizer`, replay context types, and walk-forward integration.
- Keep full-file Decimal loads: not viable, 5.6 seconds per file load is unacceptable for walk-forward CV with 5+ windows.
- Caching full `CandleRow` lists: helps repeated reads but does not solve the full-file scan problem.

Implementation shape:
- Add filtered loaders such as `load_candles_window(...)`, `load_trades_window(...)`, and `load_funding_window(...)`
- Use `pyarrow.parquet.read_table(..., filters=[...])` or equivalent pandas/pyarrow filtered reads
- Convert only the filtered table/DataFrame rows into existing domain row types
- Preserve the existing `load_candles()` / `load_trades()` / `load_funding_rates()` APIs for callers that still need full-file reads

### 4. Backward-compatible reads and harness contracts

**Decision**: Do not change the Parquet schema, column layout, or row-domain contracts. pyarrow transparently reads both Snappy and Zstd compressed files. `BacktestHarness._load_candles()` and replay market loading continue to return domain rows, not DataFrames.

**Rationale**: Users may have branches or backups with old-format files. Zero migration friction.

### 5. Catalog selection must be range-aware

**Decision**: Update dataset selection semantics so callers can request the dataset that best covers a requested `[start_ms, end_ms]` window. The current `DataCatalog.find()` behavior (“prefer the narrowest range”) is not safe once duplicate or superseded registrations exist.

**Rationale**: The catalog already contains duplicate registrations for the same `(exchange, pair, resolution)` with different coverage windows. A filtered loader that asks the catalog for “BTC-USDT/1m” should not accidentally receive the older, narrower file and then fail to satisfy the requested backtest window. Selection must prefer:
- a dataset that fully covers the requested range, if one exists
- otherwise the widest / newest dataset among matches

**Alternatives considered**:
- Keep `find()` as-is and clean the catalog manually: too fragile; duplicates already exist in normal downloader workflows.
- Replace the catalog with direct filesystem scanning: unnecessary; the catalog is still useful, it just needs better selection semantics.

### 6. Fix `validate_candles` timeframe awareness

**Decision**: Add optional `expected_interval_ms` parameter to `validate_candles()` derived from the resolution string (e.g., "5m" → 300,000 ms). Update the CLI to pass the correct interval.

**Rationale**: The current validator hardcodes 60,000 ms (1m), producing 189,503 false-positive gap warnings when validating a 5m candle file.

## Risks / Trade-offs

- **[Risk]** Predicate pushdown does not help because callers still load the full file before filtering → **Mitigation**: require harness/replay window loaders to accept start/end timestamps and apply parquet filters before materialization.
- **[Risk]** Future contributors may still bypass the filtered loaders and call full-file `load_candles()` in hot paths → **Mitigation**: document the new filtered APIs and update the harness/replay callers in the same change.
- **[Risk]** Catalog duplicates cause the loader to choose the wrong parquet file for a requested window → **Mitigation**: update `DataCatalog.find()` or add a range-aware finder used by harness/replay loaders; add tests with duplicate dataset entries.
- **[Risk]** Migration script races with an active downloader or any writer touching `data/historical/` → **Mitigation**: require the migration to run only against a quiesced directory and fail fast if `.tmp` parquet files or active writer markers are detected.
- **[Risk]** Migration script corruption → **Mitigation**: Atomic writes (write tmp, rename). Original files can be re-downloaded from exchange.
- **[Risk]** Older pyarrow versions don't support Zstd → **Mitigation**: pyarrow has supported Zstd since v0.17 (2020). Our pinned version is 18.1.0.
