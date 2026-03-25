## ADDED Requirements

### Requirement: TelemetrySchema declares strategy-specific metrics
The system SHALL define a `TelemetrySchema` as a list of `TelemetryField` entries, each with: `name` (str), `key` (str — maps to signal metadata key), `type` (Literal["decimal", "int", "str", "bool"]), and `default` (Any). Strategies SHALL declare their schema via `telemetry_schema()` at registration time.

#### Scenario: Strategy declares custom fields
- **WHEN** a pullback strategy returns `TelemetrySchema([TelemetryField("pb_conviction", "conviction", "decimal", Decimal("0")), TelemetryField("pb_rsi", "rsi", "decimal", Decimal("0"))])`
- **THEN** the desk includes columns `pb_conviction` and `pb_rsi` in CSV output and Redis snapshots

#### Scenario: Missing metadata key uses default
- **WHEN** a signal's metadata does not contain a key declared in the telemetry schema
- **THEN** the default value from the `TelemetryField` is used in the output

### Requirement: TelemetryEmitter writes CSV, Redis, and Prometheus uniformly
The system SHALL implement a `TelemetryEmitter` that accepts `(MarketSnapshot, TradingSignal, RiskDecision)` per tick and writes to three outputs:
1. **CSV**: Append to minute.csv using `CsvSplitLogger` with columns from the desk's base fields + strategy's telemetry schema
2. **Redis**: Publish `MarketSnapshotEvent` to `hb.market_data.v1` with strategy fields in the `metadata` envelope
3. **Prometheus**: Export gauges for key metrics (equity, position, spread, edge, regime) via the existing `bot_metrics_exporter` scrape path

#### Scenario: Tick produces CSV row with strategy fields
- **WHEN** the desk completes a tick with signal metadata `{"flow_conviction": 0.85}`
- **THEN** minute.csv contains a row with the standard desk columns AND a `flow_conviction` column with value `0.85`

#### Scenario: Redis snapshot includes strategy metadata
- **WHEN** the desk publishes a `MarketSnapshotEvent`
- **THEN** the event payload includes strategy-specific fields from `signal.metadata` under a `strategy_data` key

#### Scenario: Prometheus gauge updates on each tick
- **WHEN** the desk completes a tick
- **THEN** Prometheus gauges for `equity_quote`, `net_base_pct`, `spread_pct`, and `regime` are updated for the bot's metric labels

### Requirement: Fill events are logged and published
The system SHALL log fill events to both the fill WAL (write-ahead log on disk) and the `hb.bot_telemetry.v1` Redis stream. Fill telemetry SHALL include: order_id, side, price, amount, fee, slippage_bps, realized_pnl, timestamp_ms, strategy_name.

#### Scenario: Fill appended to WAL and Redis
- **WHEN** the desk processes a fill event
- **THEN** the fill is appended to the fill WAL (JSON lines file) AND published to `hb.bot_telemetry.v1` with all required fields

#### Scenario: Daily summary logged at rollover
- **WHEN** a UTC day boundary is crossed
- **THEN** the desk writes a daily summary row to daily.csv with: open equity, close equity, daily P&L, fill count, turnover, max drawdown

### Requirement: Telemetry columns are auto-discovered from schema
The system SHALL NOT hardcode strategy-specific column names in `epp_logging.py` or `tick_emitter.py`. Instead, the `TelemetryEmitter` SHALL dynamically construct column lists from the base desk fields + the strategy's `TelemetrySchema`. New strategies SHALL get telemetry output without modifying any logging infrastructure code.

#### Scenario: New strategy gets CSV columns automatically
- **WHEN** a new strategy registers with `TelemetrySchema([TelemetryField("momentum_score", "momentum", "decimal", Decimal("0"))])`
- **THEN** minute.csv includes a `momentum_score` column without any changes to logging code
