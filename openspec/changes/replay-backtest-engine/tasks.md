## 0. Foundations (before harness construction)

- [x] 0.1 Audit `time.time()` / monotonic usage in `ConnectorRuntimeAdapter` (lines 100/111/118/129/145/152/257), `services/common/market_data_plane.py` (`CanonicalMarketDataReader` lines 150/167/204/325), `SharedRuntimeKernel` / `DirectionalRuntimeController`, `bots/bot7/pullback_v1.py` (`_time_mod.time()` at lines 376/1097/1627), `paper_engine_v2/hb_event_fire.py` (fill timestamp line 239), `protective_stop.py` (line 244), `telemetry_mixin.py` (line 109), and `hb_bridge.py`; document every call site that affects staleness, cache TTL, fill timestamps, or logging
- [x] 0.2 Choose and document mitigation per call site: module-level `time.time` patch during replay, replay-specific branch, or optional production time-source injection; add to `design.md` replay maintenance profile
- [x] 0.3 Audit `ConnectorRuntimeAdapter._reader_for` / `_aux_market_readers`; plan monkeypatch or dict replacement so no lazy live `CanonicalMarketDataReader` is constructed during replay
- [x] 0.4 Implement `ReplayInjection.apply(controller, ...)` (or equivalent) centralizing post-init replacement of `_trade_reader`, `_runtime_adapter._canonical_market_reader`, `connectors`, `market_data_provider`; add a contract test that required attributes exist after apply on a stubbed controller
- [x] 0.5 Document asyncio driver: replay loop SHALL `await controller.update_processed_data()` each step (no synchronous tick)

## 1. Data Pipeline — Funding Rates

- [x] 1.1 Add `FundingRow` dataclass to `backtesting/types.py` with fields `timestamp_ms: int`, `rate: Decimal`
- [x] 1.2 Add `download_funding_rates(symbol, since_ms, until_ms)` to `DataDownloader` using ccxt `fetch_funding_rate_history()`, with retry/backoff matching existing patterns
- [x] 1.3 Add `save_funding_rates(path, rates)` and `load_funding_rates(path) -> list[FundingRow]` to `DataStore` using parquet with schema `(timestamp_ms: int64, rate: float64)`
- [x] 1.4 Update `DataCatalog` to accept `resolution="funding"` entries in `register()` and `find()`; implement disambiguation rule when multiple entries match (spec: narrowest range or raise)
- [x] 1.5 Test: round-trip save/load funding rates; catalog register/find with `resolution="funding"`; floor-search edge cases (before first rate, gap)

## 2. Data Pipeline — Wire Trade Ticks to Catalog

- [x] 2.1 Add a catalog-aware `download_and_register_trades()` helper that calls existing `download_trades()`, saves via `save_trades()`, deduplicates by `trade_id` on append, and registers in catalog with `resolution="trades"`
- [x] 2.2 Add a catalog-aware `download_and_register_funding()` helper (same pattern for funding)
- [x] 2.3 Add CLI entry point for data download: `python -m controllers.backtesting.data_downloader --exchange bitget --pair BTC-USDT --types candles,trades,funding --start 2025-01-01 --end 2025-03-01` (document UTC/date parsing in help text)
- [x] 2.4 Download BTC-USDT trade ticks and funding rates for the existing candle date range and register in catalog (ops task; optional in CI) — Run: `PYTHONPATH=hbot python -m controllers.backtesting.data_downloader --exchange bitget --pair "BTC/USDT:USDT" --types candles,trades,funding --start 2025-01-01 --end 2025-03-01 --output hbot/data/historical`
- [x] 2.5 Test: duplicate catalog entries → disambiguation or error; corrupt/missing parquet → clear failure

## 3. Replay Clock

- [x] 3.1 Create `backtesting/replay_clock.py` with `ReplayClock` class: `__init__(start_ns)`, `time() -> float`, `now_ns -> int` property, `advance(step_ns)`; expose `now_ms` if needed for staleness
- [x] 3.2 Test: init, advance, time consistency

## 4. ReplayMarketDataReader

- [x] 4.1 Create `backtesting/replay_market_reader.py` with `ReplayMarketDataReader` class taking `clock: ReplayClock` and `trades: list[TradeRow]`
- [x] 4.2 Implement time-indexed trade lookup: `advance(now_ns)` updates the visible window; `recent_trades(count)` returns `list[MarketTrade]` before current time
- [x] 4.3 Implement `get_top_of_book()` returning `MarketTopOfBook` derived from recent buy/sell trade prices
- [x] 4.4 Implement `get_depth_imbalance(depth)` computing imbalance from recent trade volumes
- [x] 4.5 Implement `get_trade_flow_features(...)` with **replay-time** staleness (not `time.time()`)
- [x] 4.6 Implement remaining `CanonicalMarketDataReader` public methods used by adapter/kernel: `get_market_state`, `latest_quote`, `latest_depth`, `latest_payloads`, `recent_trade_payloads`, `market_state_debug`; implement `get_directional_trade_features` per spec (stale/unsupported or second-leg data)
- [x] 4.7 Test: recent_trades window correctness; golden fixture for `get_trade_flow_features` on frozen trades; edge case with no trades

## 5. ReplayConnector and ReplayMarketDataProvider

- [x] 5.1 Create `backtesting/replay_connector.py` with `ReplayConnector` class taking `clock`, `candles`, `funding_rates`, `portfolio: PaperPortfolio`, `instrument_spec`
- [x] 5.2 Implement `get_mid_price(pair)` from current candle interpolation (same logic as HistoricalDataFeed)
- [x] 5.3 Implement `get_order_book(pair)` returning an adapter-compatible object with `.best_bid`, `.best_ask`, `.bid_entries()`, `.ask_entries()` (matching HB `OrderBook` interface); can wrap `HistoricalDataFeed.get_book()` `OrderBookSnapshot` with a thin adapter since `OrderBookSnapshot` has `.bids`/`.asks` tuples but the adapter calls `.bid_entries()`/`.ask_entries()` methods
- [x] 5.4 Implement `get_funding_info(pair)` with floor-search on funding_rates by timestamp
- [x] 5.5 Implement `get_balance()`, `get_available_balance()`, `get_position()`, `account_positions()` delegating to `PaperPortfolio`
- [x] 5.6 Implement `trading_rules`, `ready`, `status_dict` and any additional methods discovered in 0.1 audit (`get_price_by_type`, etc.)
- [x] 5.7 Create `ReplayMarketDataProvider` with `time() -> float` wrapping `ReplayClock`, `get_connector(name)`, and `get_candles_df(connector, pair, interval, count)` returning historical OHLCV candles up to current replay time (required by `_get_ohlcv_ema_and_atr()` for EMA/ATR regime detection every tick); add stub/replay implementations for any other `market_data_provider` methods the kernel calls
- [x] 5.8 Test: mid price at various clock positions; funding lookup; balance delegation
- [x] 5.9 Test: with frozen wall clock + advancing `ReplayClock`, verify connector/adapter-visible behavior matches spec (mid cache / staleness)

## 6. HB Stub Module

- [x] 6.1 Extract the `_install_hb_stubs()` pattern from `test_epp_v2_4_core.py` into a reusable `backtesting/hb_stubs.py` module that both tests and the replay harness can import
- [x] 6.2 Extend stubs to cover `DirectionalRuntimeController` imports (merge patterns from `test_directional_runtime.py`)
- [x] 6.3 Verify: importing `PullbackV1Controller` after stubs succeeds without Hummingbot

## 7. Replay Harness

- [x] 7.1 Create `backtesting/replay_harness.py` with `ReplayHarness` class
- [x] 7.2 Implement config loading: parse YAML with `mode: "replay"`, `strategy_module`, `strategy_class` (or registry), `strategy_config`, `data` section, `start_date`, `end_date`, `step_interval_s`, `warmup_bars` or `warmup_duration`, optional `replay.allow_missing_funding`
- [x] 7.3 Implement data loading: resolve candles, trades, funding from catalog; validate cross-stream coverage per spec; fail fast or set `degraded` when explicitly allowed
- [x] 7.4 Apply replay maintenance profile (env/config) before controller tick; validate `fee_mode` is `manual` or `project` (not `auto`); patch `time.time` in `hb_event_fire` module for replay fill timestamps
- [x] 7.5 Implement controller instantiation: install HB stubs → import strategy class from `strategy_module` → create config → instantiate controller
- [x] 7.6 Implement post-init injection via `ReplayInjection.apply`; pre-register instrument in PaperDesk via `desk.register_instrument(instrument_spec, historical_data_feed)` before calling `install_paper_desk_bridge`; apply `_reader_for` / aux-reader mitigation from 0.3
- [x] 7.7 Implement PriceBuffer warm-up from historical candles per `warmup_*` config
- [x] 7.8 Implement async suppression: patch `_ensure_price_sampler_started` to no-op; feed price samples synchronously via `_price_buffer.add_sample()` each tick
- [x] 7.9 Implement asyncio time loop: advance clock → advance reader → align feed → call `drive_desk_tick(strategy, desk, now_ns)` (**sole** desk-tick; do NOT call `desk.tick()` separately — `drive_desk_tick` calls it internally and then routes fill events) → **`await` `update_processed_data()`** → collect metrics
- [x] 7.10 Implement metrics collection: per-tick equity, position, regime, fills; aggregate into `ReplayResult` including `limitations` and optional `degraded`
- [x] 7.11 Implement report generation: reuse `compute_backtest_metrics()` from existing `metrics.py`; produce summary output
- [x] 7.12 Add CLI: `python -m controllers.backtesting.replay_harness --config path.yml` with optional `--progress-every N`

## 8. Replay Config Template

- [x] 8.1 Create `data/backtest_configs/bot7_pullback_replay.yml` template with `mode: "replay"`, `strategy_module`, `strategy_class`, full `strategy_config` matching production, `warmup_bars` or `warmup_duration`, and data section
- [x] 8.2 Document config fields in the YAML with inline comments (including UTC/date semantics)

## 8.5 Replay environment verification

- [x] 8.5.1 Verify `REDIS_HOST` unset gives safe no-ops for: `BridgeState.get_redis()`, `_get_telemetry_redis()`, `DailyStateStore` (file fallback), `_consume_signals`, `_check_hard_stop_transitions`, `_consume_paper_exchange_events`, `_check_portfolio_risk_guard`
- [x] 8.5.2 Verify `PAPER_EXCHANGE_MODE` unset/disabled gives safe no-ops for: `_ensure_sync_state_command`, `_publish_paper_exchange_command`
- [x] 8.5.3 Verify HB framework executor paths (`filter_executors`, `executors_info`, `StopExecutorAction`, `CreateExecutorAction`) fail gracefully with MagicMock stubs (all wrapped in try/except)
- [x] 8.5.4 Verify `_refresh_margin_ratio` falls back to computed ratio when `ReplayConnector` lacks `get_margin_info`
- [x] 8.5.5 Verify `_run_startup_position_sync` works with `ReplayConnector.get_position()` and `account_positions` backed by `PaperPortfolio`

## 9. Integration and validation

- [x] 9.1 Integration test: load a small slice of real candle + trade data, run `ReplayHarness` with `PullbackV1Controller`, verify asyncio loop completes without error and produces a structured `ReplayResult`
- [x] 9.2 Contract test: frozen trade fixture → `ReplayMarketDataReader.get_trade_flow_features()` matches golden expected aggregates (replaces flaky “PnL differs from adapter” smoke)
- [x] 9.3 Test: replay run does not require Redis (no connection attempts or explicit skip if mock proves none)
- [x] 9.4 Test: invalid `strategy_module` / `strategy_class` fails fast with clear error
