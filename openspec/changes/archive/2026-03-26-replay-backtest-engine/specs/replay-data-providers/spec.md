## ADDED Requirements

### Requirement: ReplayClock provides controlled time

`ReplayClock` SHALL provide a single source of time for all replay components. It SHALL expose `time() -> float` (seconds since epoch), `now_ns -> int` (nanoseconds), and `advance(step_ns: int)` to move time forward. All replay data providers SHALL reference the same `ReplayClock` instance.

#### Scenario: Time advances by one step

- **WHEN** `clock.advance(60_000_000_000)` is called (60 seconds in nanoseconds)
- **THEN** `clock.time()` SHALL return the previous value plus 60.0 seconds and `clock.now_ns` SHALL reflect the new nanosecond timestamp

#### Scenario: Initial time matches data start

- **WHEN** the `ReplayClock` is initialized with `start_ns`
- **THEN** `clock.time()` SHALL return `start_ns / 1e9` and `clock.now_ns` SHALL return `start_ns`

### Requirement: Staleness and freshness use replay time

`ReplayMarketDataReader` SHALL compute staleness, freshness, and age using **replay time** (`ReplayClock.now_ms` or equivalent), not `time.time()`. Copy-pasted logic from production `CanonicalMarketDataReader` MUST replace wall-clock “now” with replay “now” so `stale`, `TradeFlowFeatures.stale`, and thresholds keyed to `stale_after_ms` behave deterministically under replay.

#### Scenario: Stale when latest trade is older than threshold

- **WHEN** the replay clock is T and the newest visible trade has `exchange_ts_ms` such that `T - exchange_ts_ms > stale_after_ms`
- **THEN** `get_trade_flow_features()` SHALL return `stale=True` (or equivalent) consistent with production semantics but using replay T

#### Scenario: Not stale when within threshold

- **WHEN** the newest trade is within `stale_after_ms` of replay T
- **THEN** `get_trade_flow_features()` SHALL return `stale=False` when sufficient trade data exists

### Requirement: ReplayMarketDataReader parity with CanonicalMarketDataReader

`ReplayMarketDataReader` SHALL implement the **full public surface** of `CanonicalMarketDataReader` that the runtime and `ConnectorRuntimeAdapter` may call, not only methods used by `PullbackV1Controller` directly. This includes at minimum:

- `latest_quote()`, `latest_depth()`, `latest_quote_state()`, `latest_depth_state()`, `get_market_state()`, `market_state_debug()`, `latest_payloads()`
- `recent_trade_payloads()`, `recent_trades()`
- `get_mid_price()`, `get_top_of_book()`, `get_depth_imbalance()`
- `get_trade_flow_features()`, `get_directional_trade_features()`

Methods that require a **second** connector (e.g. spot) for `get_directional_trade_features()` SHALL either: (a) return a well-defined `DirectionalTradeFeatures` with `stale=True` and documented “unsupported in replay v1”, or (b) accept optional replay data for the spot leg when config provides it, or (c) cause the harness to **fail fast** if the strategy invokes multi-connector features without replay support.

#### Scenario: recent_trades returns historical trades before current time

- **WHEN** `reader.recent_trades(count=120)` is called with the replay clock at time T
- **THEN** the reader SHALL return up to 120 `MarketTrade` objects with `exchange_ts_ms <= T`, ordered oldest-to-newest to match production `CanonicalMarketDataReader` behavior

#### Scenario: get_depth_imbalance computed from trade aggregation

- **WHEN** `reader.get_depth_imbalance(depth=5)` is called
- **THEN** the reader SHALL compute imbalance from recent buy vs sell trade volumes, returning a value in `[-1, 1]`

#### Scenario: get_top_of_book derived from recent trades

- **WHEN** `reader.get_top_of_book()` is called
- **THEN** the reader SHALL return a `MarketTopOfBook` with `best_bid` from the maximum recent sell-trade price and `best_ask` from the minimum recent buy-trade price (documented approximation vs live L2 — see design)

#### Scenario: get_market_state returns coherent state

- **WHEN** `reader.get_market_state()` is called
- **THEN** the reader SHALL return `None` or a `CanonicalMarketState`-compatible structure sufficient for `ConnectorRuntimeAdapter` paths that call `get_mark_price` / `get_last_trade_price` fallbacks as documented in design

#### Scenario: get_trade_flow_features computes full feature set

- **WHEN** `reader.get_trade_flow_features(count=120)` is called
- **THEN** the reader SHALL return a `TradeFlowFeatures` dataclass with `buy_volume`, `sell_volume`, `delta_volume`, `cvd`, `imbalance_ratio`, `stacked_buy_count`, `stacked_sell_count`, `delta_spike_ratio`, and `stale` per replay-time rules

#### Scenario: get_mid_price returns latest trade mid

- **WHEN** `reader.get_mid_price()` is called
- **THEN** the reader SHALL return the midpoint between the best bid and best ask derived from recent trades when available

#### Scenario: enabled property returns True

- **WHEN** `reader.enabled` is accessed
- **THEN** it SHALL return `True`

#### Scenario: No trades available yet

- **WHEN** the clock is before the first trade timestamp
- **THEN** `recent_trades()` SHALL return an empty list, `get_trade_flow_features()` SHALL return a `TradeFlowFeatures` with `stale=True`, and `get_top_of_book()` SHALL return `None`

#### Scenario: Golden fixture parity (optional CI)

- **WHEN** a frozen list of trades is fed to `ReplayMarketDataReader` at a fixed replay clock
- **THEN** `get_trade_flow_features()` outputs SHALL match expected values from a shared test fixture (same inputs as a unit test for production aggregation logic where feasible)

### Requirement: ReplayConnector provides mock exchange interface

`ReplayConnector` SHALL implement the connector methods that `ConnectorRuntimeAdapter` and `SharedRuntimeKernel` call: `get_mid_price()`, `get_order_book()` (returning an adapter-compatible object with `.best_bid`, `.best_ask`, `.bid_entries()`, `.ask_entries()` — see scenario below), `get_funding_info()`, `get_balance()`, `get_available_balance()`, `get_position()`, `account_positions`, `trading_rules`, `ready`, and `status_dict`. Additional methods the adapter invokes (e.g. `get_price_by_type`, `status_dict` shape) SHALL be implemented or delegated so the adapter does not receive accidental mocks. `_run_startup_position_sync()` also calls `connector.get_position()` and `account_positions` at startup, so these MUST be backed by `PaperPortfolio` from the start. Prices and funding come from replay data; balances and positions come from `PaperPortfolio`.

#### Scenario: get_order_book returns adapter-compatible object

- **WHEN** `connector.get_order_book(pair)` is called by `ConnectorRuntimeAdapter`
- **THEN** it SHALL return an object with `.best_bid` (Decimal price), `.best_ask` (Decimal price), `.bid_entries()` (iterable of objects with `.amount`), and `.ask_entries()` (iterable of objects with `.amount`) — matching the Hummingbot `OrderBook` interface that the adapter expects. This MAY be a lightweight wrapper around `OrderBookSnapshot` or a stub class.

#### Scenario: get_mid_price returns current candle mid

- **WHEN** `connector.get_mid_price(pair)` is called
- **THEN** it SHALL return the mid price from the current replay candle/trade data

#### Scenario: get_funding_info returns historical funding

- **WHEN** `connector.get_funding_info(pair)` is called
- **THEN** it SHALL return funding info with the rate from the historical funding series at the current replay time

#### Scenario: get_balance delegates to PaperPortfolio

- **WHEN** `connector.get_balance("USDT")` is called
- **THEN** it SHALL return the current quote balance from the `PaperPortfolio`

#### Scenario: get_position delegates to PaperPortfolio

- **WHEN** `connector.get_position(pair)` is called
- **THEN** it SHALL return the current position amount from the `PaperPortfolio`

#### Scenario: ready always returns True

- **WHEN** `connector.ready` is accessed
- **THEN** it SHALL return `True`

#### Scenario: trading_rules returns instrument spec

- **WHEN** `connector.trading_rules` is accessed
- **THEN** it SHALL return a dict containing the trading pair's rules with `min_order_size`, `min_price_increment`, and `min_base_amount_increment`

### Requirement: ReplayMarketDataProvider wraps ReplayClock

`ReplayMarketDataProvider` SHALL provide `time() -> float` returning the replay clock time. It SHALL also provide `get_connector(name)` returning the `ReplayConnector`. It SHALL implement `get_candles_df(connector, pair, interval, count)` returning a DataFrame of historical OHLCV candles ending at the current replay time. Any other methods `SharedRuntimeKernel` calls on `market_data_provider` SHALL be implemented as no-op or replay-backed per design.

#### Scenario: time returns replay clock time

- **WHEN** `mdp.time()` is called during replay
- **THEN** it SHALL return the same value as `clock.time()`, not the wall clock

#### Scenario: get_connector returns ReplayConnector

- **WHEN** `mdp.get_connector(connector_name)` is called
- **THEN** it SHALL return the `ReplayConnector` instance

#### Scenario: get_candles_df returns historical OHLCV up to current replay time

- **WHEN** `mdp.get_candles_df(connector, pair, "1m", count)` is called during replay
- **THEN** it SHALL return a DataFrame with the most recent `count` completed 1m candles ending at or before the current replay time. Columns SHALL match production format (`open`, `high`, `low`, `close`, `volume`, `timestamp`). This is required because `SharedRuntimeKernel._get_ohlcv_ema_and_atr()` calls this every tick for EMA/ATR regime detection.

#### Scenario: get_candles_df before warm-up period

- **WHEN** `get_candles_df` is called and fewer than `count` candles exist before the current replay time
- **THEN** it SHALL return the available candles (regime detection handles short DataFrames by returning `None`)

### Requirement: ConnectorRuntimeAdapter wall-clock coupling mitigated

During replay, `ConnectorRuntimeAdapter` (or modules it uses) SHALL NOT use wall-clock `time.time()` in ways that invalidate mid-price cache, staleness, or logging relative to `ReplayClock`. The implementation SHALL satisfy the replay-harness requirement for wall-clock alignment (patch, time-source injection, or documented narrow path).

#### Scenario: Documented mitigation is tested

- **WHEN** replay runs with a controlled `ReplayClock` and frozen wall clock in CI
- **THEN** mid-price and connector adapter behavior SHALL remain consistent across steps as specified in harness tests
