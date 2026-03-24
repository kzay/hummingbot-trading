## Context

The current backtesting system (`BacktestHarness` + adapter pattern) uses custom adapter classes (`BacktestPullbackAdapter`, `BacktestRuntimeAdapter`) that reimplement strategy decision logic. For bot7 pullback, the adapter skips all trade-flow signals (absorption, delta trap, depth imbalance), funding alignment checks, and probe mode — producing inflated results.

The production strategy controller (`PullbackV1Controller`) extends `DirectionalRuntimeController` → `SharedRuntimeKernel` → `MarketMakingControllerBase` (Hummingbot). Its main tick is **`async`** `update_processed_data()` which calls ~15 methods consuming data from:
- `ConnectorRuntimeAdapter` — mid price, order book, funding, balances (wraps Hummingbot connector); may use **`time.time()`** for staleness / cache timestamps in shared code
- `CanonicalMarketDataReader` — trade ticks, depth, quotes (reads Redis streams in production); production staleness uses wall clock unless replaced in replay
- `market_data_provider` — time (`time()`), optional candle/history APIs
- `ConnectorRuntimeAdapter._reader_for()` — may **lazily construct additional** `CanonicalMarketDataReader` instances for alternate connector/pair (multi-connector trade-flow features)
- `PaperDesk` (via `install_paper_desk_bridge`) — order execution in paper mode

The existing test suite (`test_epp_v2_4_core.py`, `test_directional_runtime.py`) already demonstrates that the controller can be instantiated **without Hummingbot installed** using `sys.modules` stub injection — creating fake `MarketMakingControllerBase`, `MarketMakingControllerConfigBase`, and related types.

PaperDesk already simulates an exchange. The gap is in the **data feed layer** and in **shared-runtime side effects** (wall clock, Redis, lazy readers, supervisory maintenance).

## Goals / Non-Goals

**Goals:**
- Run the real `PullbackV1Controller` via **`await update_processed_data()`** on historical data with trade-flow and funding paths active per replay data (not “all signals” if multi-connector spot data is absent — see v1 scope)
- **No edits to strategy decision code** for replay; injection and harness-only changes are acceptable
- Produce comparable metrics to the existing backtest (equity curve, fills, PnL, regime trace) so results can be compared
- **v1 primary target:** single-connector directional replay (e.g. bot7 pullback on one perpetual). Multi-connector strategies (e.g. directional features needing spot + futures readers) require explicit replay support or fail fast
- Download and store trade ticks and funding rates alongside existing 1m candle data

**Non-Goals:**
- Real L2 order book snapshot replay (synthetic books from trades/candles are acceptable)
- Sub-second tick resolution (60s steps are acceptable for v1)
- Running inside a live Hummingbot process (the replay engine is standalone)
- Replacing the existing adapter-based backtest (it remains available for lightweight runs)
- Live paper trading replay (this is offline historical replay only)

## Decisions

### Decision 1: Post-init injection over subclassing

**Choice**: After instantiating the real controller, replace its data source attributes (`_trade_reader`, `_runtime_adapter._canonical_market_reader`, `connectors`, `market_data_provider`) with replay versions. Centralize in `ReplayInjection.apply(...)` where practical for contract tests.

**Why not subclassing**: Subclassing `PullbackV1Controller` to override data access would couple the replay engine to the strategy's internal structure. Post-init injection is less invasive — the controller class is unchanged.

**Why not constructor injection**: `SharedRuntimeKernel.__init__` creates `ConnectorRuntimeAdapter` and `CanonicalMarketDataReader` internally during init. Modifying the constructor would require production code changes. Post-init replacement avoids this.

**Brittleness**: Private attribute names (`_trade_reader`, `_runtime_adapter._canonical_market_reader`) are a **compatibility contract**; refactors to the kernel require updating one injection helper and its contract test.

### Decision 2: Reuse HB stub pattern from test suite

**Choice**: Use the exact `_install_hb_stubs()` + `sys.modules` injection pattern from `test_epp_v2_4_core.py` to import and instantiate controllers without Hummingbot.

**Alternative considered**: Running inside a Hummingbot process. Rejected because it adds massive complexity (asyncio event loop, connector lifecycle, script runner) with no benefit for offline replay.

### Decision 3: ReplayMarketDataReader implements full CanonicalMarketDataReader public API

**Choice**: Create `ReplayMarketDataReader` that implements the **full public surface** used by the kernel and `ConnectorRuntimeAdapter`, backed by a time-indexed buffer of historical `TradeRow` data. Staleness MUST use **replay time**, not `time.time()`.

**Alternative considered**: Mocking Redis streams with fake data. Rejected because it's fragile (depends on Redis wire format) and slower than direct in-memory access.

**Fidelity note**: `get_top_of_book()` derived from trade extremes is a **deliberate approximation** vs live quote/L2; adverse selection and spread filters may differ from production. This MUST appear in `ReplayResult.limitations`.

### Decision 4: ReplayConnector as explicit mock

**Choice**: Create a lightweight `ReplayConnector` class that implements connector methods `ConnectorRuntimeAdapter` actually calls, plus any adjacent calls discovered in audit. Backed by replay data and `PaperPortfolio`.

**Alternative considered**: Using `MagicMock` for the connector. Rejected because MagicMock silently returns mock objects for uncalled methods, which could mask bugs.

### Decision 5: ReplayClock as single logical time source

**Choice**: A `ReplayClock` object that provides `time() -> float` and `now_ns -> int`. All replay components reference the same instance.

**Wall-clock leakage**: `ConnectorRuntimeAdapter`, `CanonicalMarketDataReader` (if copied), and other modules may call **`time.time()`** for staleness, cache TTL, or logging. **Mitigation (required):** patch `time.time` in affected modules during replay, or inject a time source into shared code (production change — only if agreed), or narrow code paths so replay always hits replay-aware branches. This is **foundational** and MUST be validated before the harness loop is considered complete.

### Decision 6: Trade-flow feature computation

**Choice**: `ReplayMarketDataReader.get_trade_flow_features()` uses the **same aggregation rules** as production `CanonicalMarketDataReader` but with replay-backed trades and **replay-time** for “now” and stale checks.

**Alternative considered**: Calling production `get_trade_flow_features()` with mocked Redis. Rejected due to Redis dependency and complexity.

### Decision 7: Funding rates stored in parquet

**Choice**: Add `download_funding_rates()` to `DataDownloader` using ccxt's `fetch_funding_rate_history()`. Store as parquet with schema `(timestamp_ms: int64, rate: float64)`. Register in catalog with `resolution="funding"`.

**Replay cadence**: Controller funding refresh may use `funding_rate_refresh_s`. For replay, set refresh interval `<= step_interval_s` or force refresh each tick so 8h funding marks are visible when the clock steps.

### Decision 8: Executor actions routed through PaperDesk bridge

**Choice**: (1) Pre-register the instrument in PaperDesk via `desk.register_instrument(instrument_spec, historical_data_feed)` so the matching engine uses `HistoricalDataFeed` for order book snapshots. (2) Then call `install_paper_desk_bridge(strategy, desk, connector_name, instrument_id, trading_pair, instrument_spec)` to route `strategy.buy()`, `strategy.sell()`, `strategy.cancel()` through PaperDesk.

**Why pre-register**: `install_paper_desk_bridge` only skips feed creation when `instrument_id.key in desk._engines` (line 2180). Without pre-registration, it would create `HummingbotDataFeed(connector, pair)` wrapping the `ReplayConnector`, which may not implement `get_order_book()` in the format `HummingbotDataFeed` expects (it calls `connector.get_order_book(pair)` and expects HB `OrderBook` type with `.bid_entries()` / `.ask_entries()`).

**Risk**: Full Hummingbot `PositionExecutor` lifecycle (barriers, auto-refresh) may not match production. **v1 acceptance:** plan and orders through PaperDesk are authoritative; executor internals are secondary. Document under limitations.

### Decision 9: Async boundary

**Choice**: The harness runs an **asyncio** driver that **`await`s** `update_processed_data()` each step. No synchronous “fire and forget” call.

### Decision 10: Auxiliary `CanonicalMarketDataReader` instances

**Choice**: `ConnectorRuntimeAdapter._reader_for()` must not create live Redis readers during replay. Mitigations: replace `_aux_market_readers`, patch `_reader_for`, or **fail fast** when the strategy calls multi-connector features without replay support.

### Decision 11: Fill routing via drive_desk_tick (sole tick mechanism)

**Choice**: Each replay tick calls `drive_desk_tick(strategy, desk, now_ns)` (from `hb_bridge.py`) as the **sole** desk-tick entry point. `drive_desk_tick` internally calls `desk.tick(now_ns)` (line 2602), then iterates `OrderFilled` / `FundingApplied` events and fires them to the controller via `_fire_hb_events` → `controller.did_fill_order(hb_fill)`. The harness SHALL NOT call `desk.tick()` separately — doing so would double-tick the matching engine.

**Redis I/O inside `drive_desk_tick`**: The function also runs parallel Redis reads (`_consume_signals`, `_check_hard_stop_transitions`, `_consume_paper_exchange_events`) at the top. These check `_bridge_state.get_redis()` and return early when Redis is `None`, so they are safe for replay. Integration tests SHALL verify no Redis connection is attempted.

**Risk**: `hb_event_fire.py:239` uses `time.time()` to set the fill event timestamp. For replay, this means fill logs carry wall-clock time unless patched. **v1 acceptance:** patch `time.time` in `hb_event_fire` during replay (same mechanism as Decision 5 wall-clock patch), or document wall-clock fill timestamps as a known limitation.

### Decision 12: Fee mode constraint

**Choice**: Replay config SHALL require `fee_mode: manual` or `fee_mode: project`. `fee_mode: auto` calls `FeeResolver.from_exchange_api(connector)` which hits the live exchange API and will fail or return wrong data with a `ReplayConnector`.

### Decision 13: Replay maintenance profile (environment / config)

Before the loop, apply defaults so live-only paths do not run. **Keys (confirmed by audit):**

- `REDIS_HOST` = unset/empty → `BridgeState.get_redis()` returns None; `_get_telemetry_redis()` returns None; `DailyStateStore` uses file fallback; `_consume_signals`, `_check_hard_stop_transitions`, `_consume_paper_exchange_events`, `_check_portfolio_risk_guard` all return early.
- `PAPER_EXCHANGE_MODE` = unset/disabled → `_ensure_sync_state_command` and `_publish_paper_exchange_command` return early; no Redis publishes attempted.
- `HB_HISTORY_PROVIDER_ENABLED` / `HB_HISTORY_SEED_ENABLED` = false → `_maybe_seed_price_buffer()` skips network/Redis/Postgres history fetch.
- `HB_CANONICAL_MARKET_DATA_ENABLED` = false/unset → prevents `CanonicalMarketDataReader.__init__` from connecting to Redis at import time.
- Require `fee_mode: manual` or `fee_mode: project` (not `auto`) → prevents `FeeResolver.from_exchange_api()` call.
- Disable or stub protective-stop paths (`protective_stop_enabled: false` or equivalent) — `BitgetStopBackend` uses ccxt `create_order`/`cancel_order` which require live exchange.
- Ensure `ReplayConnector` implements `get_position()`, `account_positions`, `get_balance()`, `get_available_balance()` backed by `PaperPortfolio` → `_run_startup_position_sync()` and `_check_position_reconciliation()` work without live exchange.
- Ensure `ReplayMarketDataProvider.get_candles_df()` returns historical candles → `_get_ohlcv_ema_and_atr()` computes EMA/ATR for regime detection as in production.

The replay config template SHALL document which flags the harness sets or requires.

## Risks / Trade-offs

- **[`time.time()` leakage]** → Staleness and adapter cache use wall clock → silent divergence. Affected modules confirmed by code audit: `ConnectorRuntimeAdapter` (mid-price cache/staleness at lines 100/111/118/129/145/152/257), `market_data_plane.py` (stale checks, trade-flow "now" at lines 150/167/204/325), `pullback_v1.py` (`_time_mod.time()` for `now_ms` at lines 376/1097/1627), `hb_event_fire.py` (fill event timestamps at line 239), `protective_stop.py` (refresh interval at line 244), `telemetry_mixin.py` (`_last_sub_minute_publish_ts` at line 109), `hb_bridge.py` (sync keys — safe when `PAPER_EXCHANGE_MODE=disabled`). **Mitigation:** audit all listed modules; patch `time.time` / `time.monotonic` in critical modules during replay; test with frozen wall clock.

- **[Async API]** → Calling `update_processed_data()` without `await` breaks the run. **Mitigation:** asyncio driver in harness; spec requirement.

- **[Lazy `_aux_market_readers`]** → Hidden Redis usage. **Mitigation:** patch `_reader_for` or clear aux dict after injection.

- **[Supervisory maintenance]** → Fee hooks, portfolio guard, protective stop may assume live infra. **Mitigation:** replay maintenance profile + fail fast on unexpected external I/O. Confirmed safe paths: `_check_portfolio_risk_guard` returns early when `_get_telemetry_redis()` is None; `_refresh_margin_ratio` falls back to computed ratio when `get_margin_info` is absent; `_cleanup_recovery_zombie_executors` wrapped in try/except with graceful HB import failure.

- **[Init-order coupling]** → `CanonicalMarketDataReader.__init__` may touch Redis when `HB_CANONICAL_MARKET_DATA_ENABLED=true`. **Mitigation:** mock before import, replace instance immediately after init, or ensure env var is false/unset.

- **[`get_candles_df` dependency]** → `_get_ohlcv_ema_and_atr()` calls `market_data_provider.get_candles_df()` every tick for EMA/ATR regime detection. Without it, regime detection falls back to price-buffer-only, silently differing from production. **Mitigation:** `ReplayMarketDataProvider` MUST implement `get_candles_df` returning historical candles up to replay time.

- **[`drive_desk_tick` internal Redis I/O]** → `drive_desk_tick` calls `_consume_signals`, `_check_hard_stop_transitions`, `_consume_paper_exchange_events` which all require Redis. Confirmed safe: all check `_bridge_state.get_redis()` and return early when None. `_ensure_sync_state_command` returns early when `PAPER_EXCHANGE_MODE` is disabled (default). **No mitigation needed** beyond ensuring `REDIS_HOST` is unset.

- **[`install_paper_desk_bridge` feed creation]** → `install_paper_desk_bridge` internally creates `HummingbotDataFeed(connector, pair)` if the instrument is not already registered (line 2192). `HummingbotDataFeed` calls `connector.get_order_book()` expecting HB `OrderBook` type with `.bid_entries()`/`.ask_entries()` methods, not PaperEngine `OrderBookSnapshot`. **Mitigation:** harness MUST pre-register instrument via `desk.register_instrument(spec, historical_data_feed)` BEFORE calling `install_paper_desk_bridge`.

- **[DailyStateStore Redis]** → Uses Redis when available, falls back to file persistence when `redis_url=None`. **Mitigation:** ensure `REDIS_HOST` is unset; file fallback path is sufficient for replay.

- **[Executor framework depth]** → Barriers and refresh differ from live. HB executor imports (`StopExecutorAction`, `CreateExecutorAction`, `PositionExecutorConfig`) are all wrapped in try/except with graceful failure. `self.executors_info` and `self.filter_executors` from MagicMock base class return MagicMock objects; iteration raises TypeError caught by existing exception handlers. **Mitigation:** document in `ReplayResult.limitations`.

- **[Synthetic order book fidelity]** → Fills are approximate vs L2. **Mitigation:** document in limitations.

- **[Data volume]** → Trade parquet large. **Mitigation:** parquet compression; future streaming optional.

## Migration Plan

- Phase 1: Data pipeline (trades + funding + catalog rules) — no change to live trading.
- Phase 2: Replay providers + contract tests — no change to live trading.
- Phase 3: Replay harness behind `mode: "replay"` — adapter mode unchanged.
- Rollback: stop using replay configs; no production rollback required.

## Appendix A: `time.time()` / Wall-Clock Audit (Task 0.1–0.3)

### Call-Site Inventory and Mitigations

| Module | Call Sites | Impact | Mitigation | Status |
|---|---|---|---|---|
| `connector_runtime_adapter.py` | `time.time()` at lines 100, 111, 118, 129, 145, 152, 257 | Mid-price cache staleness; controls whether cached prices are re-fetched | Module-level `time` replaced with `SimpleNamespace(time=clock.time)` via `_install_replay_time_patches` | Patched |
| `paper_engine_v2/hb_event_fire.py` | `time.time()` at line 239 | Fill event timestamp in HB event object | Module-level `time` replaced with clock shim via `_install_replay_time_patches` | Patched |
| `protective_stop.py` | `time.time()` at line 244 | Refresh interval for stop-loss monitoring | Module-level `time` replaced with clock shim via `_install_replay_time_patches` | Patched |
| `telemetry_mixin.py` | `_time_mod.time()` at lines 110, 170, 266; `_time_mod.perf_counter()` at line 602 | Sub-minute telemetry publish throttle; source timestamp; tick duration | Module-level `_time_mod` replaced with shim (`.time` = clock, `.perf_counter` = real perf_counter) via `_install_replay_time_patches` | Patched |
| `bots/bot7/pullback_v1.py` | `_time_mod.time()` at lines 376, 1097, 1627 | Trade age computation; signal timestamp; cancel sweep cooldown | All 3 sites guarded: prefer `market_data_provider.time()` when provider is set (always true in replay). `_time_mod.time()` is fallback only | Safe (no patch needed) |
| `services/common/market_data_plane.py` | `time.time()` at lines 150, 167, 204, 325 | Trade-flow staleness, quote age in `CanonicalMarketDataReader` | Not used in replay — replaced by `ReplayMarketDataReader` which uses `ReplayClock` for staleness | Bypassed |
| `hb_bridge.py` | Various sync-key timestamps | Sync state publish timing | `PAPER_EXCHANGE_MODE=disabled` causes all sync/publish paths to return early | Safe (env guard) |

### Async Driver Contract (Task 0.5)

The replay loop SHALL `await controller.update_processed_data()` each step. The harness (`replay_harness.py` line 661–667) calls `update()` and checks `inspect.isawaitable(result)` before awaiting, handling both sync and async controllers. The outer loop is driven by `async def run_async()` called via `asyncio.run()` from `run()`.

### `ConnectorRuntimeAdapter._reader_for` Audit (Task 0.3)

`_reader_for()` may lazily construct `CanonicalMarketDataReader` instances for alternate connector/pair combos. In replay:
- `ReplayInjection.apply()` replaces `_aux_market_readers` with an empty dict
- `reader_factory` is patched to return the primary `ReplayMarketDataReader` for the primary key, or raise `NotImplementedError` for unsupported aux pairs
- No live `CanonicalMarketDataReader` can be constructed during replay

## Open Questions

- ~~Exact list of env vars to disable for replay~~ → **Resolved** — see Decision 13 for confirmed keys.
- Whether v1 allows `replay.allow_missing_funding` default false only, or always fail fast on missing funding when strategy uses funding gates.
