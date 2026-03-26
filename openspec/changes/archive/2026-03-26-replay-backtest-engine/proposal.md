## Why

The current backtesting system uses custom adapter classes that **reimplement** strategy logic instead of running the real controller code. The `BacktestPullbackAdapter` skips all trade-flow signals (absorption, delta trap, depth imbalance), funding alignment, and probe mode — producing results that can be significantly more optimistic than production. Every strategy change requires a parallel update to the adapter, creating maintenance drift and silent divergence. We need a backtesting engine where the real `PullbackV1Controller` runs unchanged, receiving replayed historical data through the same interfaces it uses in production.

## What Changes

- **New replay mode for PaperEngine**: Historical candles, trade ticks, and funding rates are replayed through the same data interfaces the strategy uses in production (ConnectorRuntimeAdapter, CanonicalMarketDataReader, PaperDesk). The controller does not know it is running on replayed data.
- **Historical trade-tick pipeline**: Download, store, and catalog trade-level data (already partially supported by `DataDownloader.download_trades()` but not wired to catalog or harness).
- **Historical funding-rate pipeline**: Download, store, and catalog funding-rate history via ccxt.
- **Replay data providers**: Drop-in replacements for live data sources — `ReplayMarketDataReader` (replaces Redis-backed `CanonicalMarketDataReader`), `ReplayConnector` (replaces Hummingbot connector), `ReplayClock` (replaces wall clock).
- **Replay harness**: Orchestrates the asyncio time loop — advances the clock, ticks PaperDesk for order matching, **`await`s** `controller.update_processed_data()` on the real strategy, and collects metrics (with `ReplayResult.limitations` for fidelity gaps).
- **Hummingbot framework stubs**: Reuses the proven `sys.modules` stub-injection pattern from `test_epp_v2_4_core.py` so the controller can be instantiated without Hummingbot installed.
- **Existing adapter backtest preserved**: The current `BacktestHarness` + adapter pipeline remains available as `mode: "adapter"` for lightweight runs; the new replay mode is `mode: "replay"`.

## Capabilities

### New Capabilities

- `replay-data-pipeline`: Download, store (parquet), and catalog historical trade ticks and funding rates alongside existing candle data.
- `replay-data-providers`: Drop-in replay replacements for production data interfaces — ReplayClock, ReplayMarketDataReader, ReplayConnector — so the real strategy controller runs unchanged on historical data.
- `replay-harness`: Orchestration engine that instantiates the real strategy controller with replay data providers injected, drives the time loop, and produces metrics/reports.

### Modified Capabilities

_(none — existing adapter backtest is preserved as-is)_

## Impact

- **Code**: New files in `hbot/controllers/backtesting/` (replay_clock, replay_market_reader, replay_connector, replay_market_data_provider, replay_harness, hb_stubs). Extensions to `data_downloader.py`, `data_store.py`, `data_catalog.py`, `historical_feed.py`.
- **Data**: New parquet files for trade ticks (`resolution="trades"`) and funding rates (`resolution="funding"`) in `hbot/data/historical/`.
- **Dependencies**: ccxt (already present) for funding-rate download. No new external dependencies.
- **Config**: New backtest YAML fields (`mode: "replay"`, `strategy_module` + `strategy_class` or allowlisted registry key, `warmup_bars` / `warmup_duration`, optional replay degraded flags). Existing configs continue to work with `mode: "adapter"` (or omitted mode).
- **Tests**: Existing adapter-based tests unchanged. New tests for replay data providers and harness.
