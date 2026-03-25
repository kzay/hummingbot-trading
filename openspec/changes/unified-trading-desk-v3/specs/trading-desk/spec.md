## ADDED Requirements

### Requirement: TradingDesk protocol defines the unified execution interface
The system SHALL define a `TradingDesk` protocol that all desk implementations (live, paper, backtest) satisfy. The protocol SHALL expose methods for order submission, position query, equity query, and state persistence. Bots SHALL NOT submit orders through any path other than `TradingDesk`.

#### Scenario: Live desk wraps HB connector
- **WHEN** `LiveTradingDesk` is instantiated with a Hummingbot connector
- **THEN** all `submit_order()` calls route through the connector's order API and `get_position()` returns the connector's tracked position

#### Scenario: Paper desk wraps Paper Exchange Service
- **WHEN** `PaperTradingDesk` is instantiated with a PES client
- **THEN** all `submit_order()` calls publish to `PAPER_EXCHANGE_COMMAND_STREAM` and fills arrive via `PAPER_EXCHANGE_EVENT_STREAM`

#### Scenario: Backtest desk wraps simulated matching
- **WHEN** `BacktestTradingDesk` is instantiated with a `BacktestPaperDesk`
- **THEN** all `submit_order()` calls execute against the simulated order book and fills are synchronous within the same tick

### Requirement: TradingDesk owns the tick loop orchestration
The system SHALL implement the tick loop inside `TradingDesk` as a fixed sequence: snapshot → signal → risk → execute → telemetry. The desk SHALL call `StrategySignalSource.evaluate()` exactly once per tick. The desk SHALL NOT expose the tick loop internals to strategy code.

#### Scenario: Normal tick produces signal and executes
- **WHEN** the desk runs a tick and the strategy returns a `TradingSignal` with `family != "no_trade"` and risk gate approves
- **THEN** the desk passes the signal to the `ExecutionAdapter`, submits the resulting `DeskOrder` objects, and emits telemetry

#### Scenario: Strategy returns no_trade signal
- **WHEN** the strategy returns a `TradingSignal` with `family == "no_trade"`
- **THEN** the desk cancels stale orders, emits telemetry, and does NOT invoke the execution adapter

#### Scenario: Risk gate rejects signal
- **WHEN** the `DeskRiskGate` returns `approved == False` for a signal
- **THEN** the desk does NOT invoke the execution adapter, logs the rejection reason, and emits the risk decision in telemetry

### Requirement: TradingDesk tracks position and P&L
The system SHALL track per-instrument position (base amount, average entry price, unrealized P&L) and per-day equity watermarks (open, peak, current) within the desk. Fill deduplication SHALL use the existing order-ID-based WAL pattern from `CsvSplitLogger._FillWal`.

#### Scenario: Fill updates position
- **WHEN** the desk receives a fill event for 0.01 BTC at 65000 USDT on a flat position
- **THEN** `get_position().base_amount` equals `0.01` and `get_position().avg_entry_price` equals `65000`

#### Scenario: Daily equity rollover
- **WHEN** a new UTC day begins during a tick
- **THEN** the desk logs the previous day's P&L summary, resets daily watermarks, and persists state to Redis + disk

#### Scenario: Fill deduplication on restart
- **WHEN** the desk restarts and replays pending events
- **THEN** fills with order IDs already in the WAL are skipped and position remains consistent

### Requirement: TradingDesk persists state for crash recovery
The system SHALL persist desk state (position, daily watermarks, open orders, fill WAL cursor) to Redis and local disk on every state-changing event. On restart, the desk SHALL restore state from the latest snapshot and replay unprocessed events.

#### Scenario: Clean restart after crash
- **WHEN** the desk process crashes and restarts
- **THEN** the desk loads the last persisted state, reconciles with the exchange/PES, and resumes from the correct position without duplicate fills

#### Scenario: State persistence on every fill
- **WHEN** a fill event is processed
- **THEN** the desk writes updated state to Redis within the same tick and flushes the fill WAL to disk
