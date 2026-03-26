## ADDED Requirements

### Requirement: ReplayHarness instantiates the real strategy controller

The `ReplayHarness` SHALL instantiate the actual strategy controller class (e.g. `PullbackV1Controller`) from its config, using the proven HB stub injection pattern from the test suite. The controller class SHALL be the same class that runs in production — no adapter or reimplementation.

#### Scenario: Controller instantiation with HB stubs

- **WHEN** the replay harness starts with a valid `strategy_module` and `strategy_class` and a valid strategy config
- **THEN** the harness SHALL install Hummingbot framework stubs via `sys.modules`, import the class from `strategy_module`, instantiate the real controller with the provided config, and inject replay data providers post-init

#### Scenario: Strategy config matches production format

- **WHEN** a replay config YAML specifies `strategy_config` fields
- **THEN** these fields SHALL be passed to the real strategy config class (e.g. `PullbackV1Config`) unchanged — the same config that works in production SHALL work in replay

### Requirement: Deterministic strategy class resolution

The replay config SHALL NOT use a bare class name alone. The harness SHALL resolve the controller via **either** (a) `strategy_module` (fully qualified Python module path) plus `strategy_class` (class name within that module), **or** (b) an explicit allowlisted registry mapping short keys to `(module, class)` tuples. Arbitrary dynamic imports from user YAML without an allowlist SHALL NOT be supported in v1 unless behind a registry.

#### Scenario: Module plus class

- **WHEN** YAML contains `strategy_module: "controllers.bots.bot7.pullback_v1"` and `strategy_class: "PullbackV1Controller"`
- **THEN** the harness SHALL import `PullbackV1Controller` from that module and instantiate it

#### Scenario: Invalid module or class

- **WHEN** `strategy_module` or `strategy_class` is missing, wrong, or import fails
- **THEN** the harness SHALL fail fast with a clear error before the replay loop starts

### Requirement: ReplayHarness injects replay data providers post-init

After controller instantiation, the harness SHALL replace the controller's data source attributes with replay versions without modifying the controller class. The implementation SHOULD centralize injection in a single helper (e.g. `ReplayInjection.apply(controller, ...)`) so a contract test can assert required attributes exist after kernel refactors.

#### Scenario: Trade reader injection

- **WHEN** the controller is instantiated
- **THEN** the harness SHALL replace `controller._trade_reader` with a `ReplayMarketDataReader` and replace `controller._runtime_adapter._canonical_market_reader` with the same `ReplayMarketDataReader`

#### Scenario: Auxiliary market readers

- **WHEN** `ConnectorRuntimeAdapter` would lazily create additional `CanonicalMarketDataReader` instances via `_reader_for()` (e.g. alternate connector/pair for trade-flow features)
- **THEN** the harness SHALL prevent live Redis-backed readers: either replace `_aux_market_readers`, monkeypatch `_reader_for` to return replay readers, or document in config that multi-connector strategies are unsupported in v1 and fail fast if such a path is invoked

#### Scenario: Connector injection

- **WHEN** the controller is instantiated
- **THEN** the harness SHALL set `controller.connectors = {connector_name: replay_connector}` where `connector_name` matches `strategy_config.connector_name` (or equivalent config field) and `replay_connector` is a `ReplayConnector` backed by replay data and `PaperPortfolio`

#### Scenario: Market data provider injection

- **WHEN** the controller is instantiated
- **THEN** the harness SHALL set `controller.market_data_provider` to a `ReplayMarketDataProvider` that returns replay clock time from `time()`

#### Scenario: Order routing via PaperDesk bridge

- **WHEN** the controller is instantiated
- **THEN** the harness SHALL (1) pre-register the instrument in PaperDesk via `desk.register_instrument(instrument_spec, historical_data_feed)` so the matching engine uses `HistoricalDataFeed` (not live `HummingbotDataFeed`), then (2) call `install_paper_desk_bridge(strategy, desk, connector_name, instrument_id, trading_pair, instrument_spec)` to route order submission (`buy`, `sell`, `cancel`) through PaperDesk. Pre-registration is required because `install_paper_desk_bridge` skips feed creation only when the instrument key is already in `desk._engines`; without pre-registration it would create a `HummingbotDataFeed(connector, pair)` wrapping the replay connector, which may produce incorrect books.

### Requirement: Replay runs without Redis

A replay run SHALL NOT require a running Redis server. The harness SHALL ensure `CanonicalMarketDataReader` is never used for live I/O after injection: either mock the class before controller import, replace instances post-init, or equivalent. If Redis connection is attempted and fails, the harness SHALL fail with an explicit message rather than silently using partial live behavior.

#### Scenario: No Redis in environment

- **WHEN** Redis is not running and a valid replay config and data are present
- **THEN** the replay SHALL complete successfully using only replay data providers

### Requirement: Async tick driver

`SharedRuntimeKernel.update_processed_data()` is **async**. The harness SHALL drive each tick with `asyncio` (e.g. `await controller.update_processed_data()` inside an event loop or `asyncio.run` per tick in a driver coroutine). A synchronous call without `await` SHALL NOT be used.

#### Scenario: Each step awaits the controller tick

- **WHEN** one replay step executes
- **THEN** the harness SHALL await `update_processed_data()` so the full async body runs

### Requirement: Replay-safe runtime defaults

Before the replay loop, the harness SHALL apply a **replay maintenance profile**: environment variables and/or strategy config overrides that disable or no-op live-only paths that touch Redis, external HTTP, or wall-clock-dependent guards where those would corrupt replay. At minimum, the spec SHALL require:

- Disable history seeding that hits Redis/API/Postgres (`HB_HISTORY_PROVIDER_ENABLED` / `HB_HISTORY_SEED_ENABLED` or equivalents off for replay).
- Disable portfolio risk stream publishing if it would block or require Redis.
- Disable protective-stop or reconciliation hooks that assume live connector semantics unless explicitly backed by replay.
- **Require `fee_mode: manual` or `fee_mode: project`** in replay config (because `fee_mode: auto` calls the live exchange API via `FeeResolver.from_exchange_api`, which will fail or return incorrect data with a replay connector).
- Ensure `REDIS_HOST` is unset or empty so `BridgeState.get_redis()`, `_get_telemetry_redis()`, and `DailyStateStore` all take their no-Redis fallback paths (returns None / file-only persistence).
- Ensure `PAPER_EXCHANGE_MODE` is unset or `disabled` so `drive_desk_tick`'s internal `_ensure_sync_state_command` returns early without attempting Redis publishes.
- Ensure `ReplayMarketDataProvider.get_candles_df()` is implemented (not just stubbed), because `SharedRuntimeKernel._get_ohlcv_ema_and_atr()` calls it every tick for EMA/ATR regime detection. Without it, regime detection falls back to price-buffer-only which may differ from production.
- Ensure `_run_startup_position_sync()` works with `ReplayConnector` (it calls `connector.get_position()` and `account_positions` — the `ReplayConnector` must implement these, backed by `PaperPortfolio`).

The exact keys SHALL be documented in `design.md` and the replay config template.

#### Scenario: History provider does not fetch live candles

- **WHEN** replay starts with replay maintenance profile applied
- **THEN** `_maybe_seed_price_buffer()` or equivalent SHALL not perform network or Redis-backed history fetch; warm-up SHALL come only from local historical candles

### Requirement: Wall-clock alignment for shared runtime

Code in `ConnectorRuntimeAdapter`, `CanonicalMarketDataReader`, or related modules that uses `time.time()` for staleness, cache TTL, or logging SHALL NOT desync replay from `ReplayClock`. The harness SHALL either patch `time.time` (and related) in affected modules during replay, or document and implement an adapter-level time-source injection. This SHALL be verified by tests (see tasks).

#### Scenario: Mid-price cache does not expire on wall clock

- **WHEN** replay advances only the `ReplayClock` and wall clock is frozen or unrelated
- **THEN** mid-price and staleness logic used during the tick SHALL be consistent with replay time, not wall-clock drift

### Requirement: Fill events routed to controller via drive_desk_tick

`drive_desk_tick(strategy, desk, now_ns)` (from `hb_bridge.py`) performs **both** the PaperDesk tick (`desk.tick(now_ns)`) and event routing (`_fire_hb_events` → `controller.did_fill_order()`) in a single call. The harness SHALL call `drive_desk_tick` as the **sole** desk-tick mechanism — it SHALL NOT call `desk.tick()` separately before `drive_desk_tick`, because that would double-tick the matching engine and potentially duplicate fills.

`drive_desk_tick` also performs parallel Redis I/O at the top (`_consume_signals`, `_check_hard_stop_transitions`, `_consume_paper_exchange_events`). These check `_bridge_state.get_redis()` and return early when Redis is `None`, so they are safe for replay without Redis — but the harness SHALL verify this during integration testing (task 9.3).

#### Scenario: Fills reach controller

- **WHEN** PaperDesk matches an order during a replay step
- **THEN** `drive_desk_tick` SHALL fire the fill event so `controller.did_fill_order(hb_fill)` is called, updating position, equity, and fill logs before the next strategy tick

#### Scenario: No fills in a step

- **WHEN** no orders are matched during a replay step
- **THEN** `drive_desk_tick` SHALL still be called (it is a no-op when there are no events) so the harness does not need conditional logic

#### Scenario: No double-tick

- **WHEN** the replay harness executes a step
- **THEN** `desk.tick()` SHALL be called exactly once via `drive_desk_tick`, never separately before or after

### Requirement: Fill event timestamps use replay time

`hb_event_fire.py` uses `time.time()` when constructing `HBOrderFilledEvent.timestamp`. During replay, fill event timestamps SHALL use replay time so fill logs and `did_fill_order` callbacks carry the correct historical timestamp. The harness SHALL either: patch `time.time` in `hb_event_fire` during replay, or pass replay `now` explicitly to event-fire functions, or accept and document that fill log timestamps are wall-clock (acceptable for v1 if documented in limitations).

#### Scenario: Fill timestamp matches replay clock

- **WHEN** a fill event is fired during replay at replay time T
- **THEN** the fill event's timestamp SHALL be T (or documented as a known limitation if wall-clock)

### Requirement: ReplayHarness drives the time loop

The harness SHALL advance time in fixed steps, calling `drive_desk_tick` (which internally ticks PaperDesk and routes fill events), then awaiting `controller.update_processed_data()` at each step. **Tick ordering** (advance clock → advance reader → set HistoricalDataFeed time → `drive_desk_tick` → await controller tick) SHALL be documented as the chosen contract; it is an accepted approximation if it differs slightly from live event ordering.

#### Scenario: Standard time loop execution

- **WHEN** the replay runs from `start_date` to `end_date` with `step_interval_s: 60`
- **THEN** at each step the harness SHALL: (1) advance the ReplayClock by `step_interval_ns`, (2) advance the ReplayMarketDataReader window to the new `now`, (3) align `HistoricalDataFeed` time with the clock, (4) call `drive_desk_tick(strategy, desk, now_ns)` which ticks PaperDesk and routes fill events to the controller, (5) `await controller.update_processed_data()`, (6) collect metrics

#### Scenario: PriceBuffer warm-up before trading loop

- **WHEN** the replay starts
- **THEN** the harness SHALL seed `controller._price_buffer` with historical candle bars from the warm-up period before `start_date`. Config SHALL include `warmup_bars` (minimum count) or `warmup_duration` (time span) so long lookback indicators are satisfied; default SHALL be documented (e.g. align with longest indicator window in target strategy)

### Requirement: Replay tick boundaries

`start_date` SHALL map to the first replay step at or after the first candle open in range. `end_date` SHALL be **inclusive** of the last step whose step end time is `<= end_date` end-of-day UTC (or the timezone documented in config). If `step_interval_s` does not divide the range evenly, the final partial step SHALL either be dropped or completed per documented rule.

#### Scenario: Inclusive end

- **WHEN** `end_date` is set to day D
- **THEN** the last tick SHALL include data through the documented end of D (UTC unless otherwise specified)

### Requirement: Replay config extends backtest YAML format

The replay config SHALL use the existing backtest YAML structure with `mode: "replay"`, `strategy_module`, `strategy_class` (or registry key), `strategy_config`, `data` section, `start_date`, `end_date`, `step_interval_s`, and warm-up fields.

#### Scenario: Replay config YAML

- **WHEN** a YAML config has `mode: "replay"` and valid `strategy_module` / `strategy_class`
- **THEN** the `ReplayHarness` SHALL load and parse it, resolving data from the catalog and instantiating the specified controller

#### Scenario: Legacy adapter config still works

- **WHEN** a YAML config has `mode: "adapter"` (or no mode field)
- **THEN** the existing `BacktestHarness` with adapter pattern SHALL be used (backward compatible)

### Requirement: ReplayHarness produces metrics and reports

The harness SHALL collect per-step metrics (equity, position, regime, signal state) and produce a summary report compatible with the existing `report.py` format. `ReplayResult` (or equivalent) SHALL include a **`limitations`** field or section listing known fidelity gaps: synthetic order book, executor / barrier stubs vs full Hummingbot executors, step granularity (e.g. 60s), and trade-derived TOB vs live L2.

#### Scenario: Metrics collection per tick

- **WHEN** a replay step completes
- **THEN** the harness SHALL record: timestamp, equity, position size, regime label, mid price, and any fills that occurred

#### Scenario: Report generation

- **WHEN** the replay completes
- **THEN** the harness SHALL produce a `ReplayResult` object containing equity curve, fill list, total PnL, max drawdown, Sharpe ratio, regime breakdown — compatible with the existing `BacktestResult` / `compute_backtest_metrics()` format — and the documented limitations

#### Scenario: Limitations surfaced to operator

- **WHEN** the user reads stdout or the result object after a run
- **THEN** limitations SHALL be visible so operators do not equate replay fills with live exchange execution

### Requirement: Async coroutines disabled in replay mode

Background async tasks in `SharedRuntimeKernel` (e.g. price sampler loop) SHALL be disabled or bypassed during replay. Price data SHALL be fed synchronously through the tick loop (e.g. `_price_buffer.add_sample()` each step).

#### Scenario: Price sampler not started

- **WHEN** the controller runs in replay mode
- **THEN** `_ensure_price_sampler_started()` SHALL be a no-op or the sampler coroutine SHALL not be scheduled. Price samples SHALL be added synchronously via `_price_buffer.add_sample()` at each tick.

### Requirement: Funding refresh during replay

Funding rate used by the controller SHALL advance with replay time. The harness or replay config SHALL ensure `_refresh_funding_rate` (or equivalent) sees updates at least once per replay step when historical funding data exists (e.g. set `funding_rate_refresh_s` `<= step_interval_s` in replay profile or force refresh each tick).

#### Scenario: Funding updates per step when data exists

- **WHEN** historical funding series is loaded and each step advances the clock
- **THEN** the connector or controller SHALL observe the correct floor-search rate for the current replay timestamp each step

### Requirement: Failure handling during replay

#### Scenario: Strategy exception mid-loop

- **WHEN** `update_processed_data()` raises during replay
- **THEN** the harness SHALL abort the run, record the step index and exception, and SHALL NOT claim success; partial metrics MAY be written if documented

#### Scenario: Missing required catalog entry

- **WHEN** candles or required trade data cannot be resolved for the requested range
- **THEN** the harness SHALL fail fast before the loop with a clear error (see replay-data-pipeline for missing-data policy)

### Requirement: CLI entry point for replay

A CLI command SHALL allow running a replay from the command line with a config YAML path. Progress logging (e.g. every N steps) SHOULD be optional via flag.

#### Scenario: Run replay from CLI

- **WHEN** the user runs `python -m controllers.backtesting.replay_harness --config path/to/config.yml`
- **THEN** the replay SHALL execute and print a summary report to stdout

### Requirement: Validation uses deterministic signal checks

Regression tests SHALL NOT rely solely on “replay PnL differs from adapter PnL” as proof of trade-flow activation. Tests SHALL assert concrete replay behavior (e.g. non-empty `recent_trades` window at a known timestamp, non-trivial `TradeFlowFeatures` when fixture trades exist, or golden intermediate state on a frozen slice).

#### Scenario: Contract test for trade-flow inputs

- **WHEN** a fixed fixture of trades and clock position is loaded into `ReplayMarketDataReader`
- **THEN** `get_trade_flow_features()` SHALL match expected aggregates within documented tolerance
