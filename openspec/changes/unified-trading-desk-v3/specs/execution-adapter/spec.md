## ADDED Requirements

### Requirement: ExecutionAdapter protocol translates signals to desk orders
The system SHALL define an `ExecutionAdapter` protocol with two methods:
- `translate(signal: TradingSignal, snapshot: MarketSnapshot) -> list[DeskOrder]` — converts a signal into concrete orders
- `manage_trailing(position: PositionSnapshot, signal: TradingSignal) -> list[DeskAction]` — manages trailing stops and partial exits for open positions

#### Scenario: MM grid adapter produces buy and sell orders
- **WHEN** `MMGridExecutionAdapter.translate()` receives a signal with `family="mm_grid"` and 3 buy levels + 3 sell levels
- **THEN** it returns 6 `DeskOrder` objects with limit prices computed from `snapshot.mid * (1 ± level.spread_pct)` and amounts from `level.size_quote`

#### Scenario: Directional adapter produces single-side orders
- **WHEN** `DirectionalExecutionAdapter.translate()` receives a signal with `family="directional"` and `direction="buy"`
- **THEN** it returns only buy-side `DeskOrder` objects and no sell-side orders

#### Scenario: No-trade signal produces no orders
- **WHEN** any adapter's `translate()` receives a signal with `family="no_trade"`
- **THEN** it returns an empty list

### Requirement: Three execution adapter implementations
The system SHALL provide three concrete `ExecutionAdapter` implementations:
- `MMGridExecutionAdapter` — symmetric/skewed grid with configurable levels, spread competitiveness cap, inventory skew adjustment
- `DirectionalExecutionAdapter` — single-side entries with ATR-scaled barriers (stop-loss, take-profit, time limit)
- `HybridExecutionAdapter` — combines MM grid on one side with directional bias on the other, switching based on signal conviction

#### Scenario: MM grid applies inventory skew
- **WHEN** `MMGridExecutionAdapter.translate()` is called and `snapshot.position.net_base_pct` exceeds the target
- **THEN** sell-side spreads are tightened and buy-side spreads are widened proportional to the inventory skew

#### Scenario: Directional adapter sets ATR-scaled barriers
- **WHEN** `DirectionalExecutionAdapter.translate()` creates a `DeskOrder`
- **THEN** `stop_loss` equals `snapshot.indicators.atr_14 * config.sl_atr_mult` and `take_profit` equals `snapshot.indicators.atr_14 * config.tp_atr_mult`

#### Scenario: Hybrid adapter switches modes
- **WHEN** signal conviction is above the directional threshold
- **THEN** `HybridExecutionAdapter` uses directional mode on the signal side and cancels the opposite side
- **WHEN** signal conviction is below the directional threshold but above the bias threshold
- **THEN** `HybridExecutionAdapter` uses MM grid with skewed sizing toward the signal direction

### Requirement: DeskOrder and DeskAction are typed immutable instructions
The system SHALL define `DeskOrder` as a frozen dataclass with: `side`, `order_type` (limit/market), `price`, `amount_quote`, `level_id`, `stop_loss`, `take_profit`, `time_limit_s`. The system SHALL define `DeskAction` as a typed union of: `SubmitOrder`, `CancelOrder`, `ModifyOrder`, `ClosePosition`, `PartialReduce`.

#### Scenario: Trailing stop triggers partial reduce
- **WHEN** `manage_trailing()` detects the position has reached 1/3 of take-profit
- **THEN** it returns a `PartialReduce` action with the configured partial exit ratio

#### Scenario: Stale order cancellation
- **WHEN** the desk detects an order older than `executor_refresh_time`
- **THEN** the desk creates a `CancelOrder` action for that level_id

### Requirement: Execution adapter is selected by strategy family
The system SHALL select the `ExecutionAdapter` implementation based on the `execution_family` field in the `StrategyEntry` from the registry. The mapping SHALL be:
- `"mm_grid"` → `MMGridExecutionAdapter`
- `"directional"` → `DirectionalExecutionAdapter`
- `"hybrid"` → `HybridExecutionAdapter`

#### Scenario: Registry entry determines adapter
- **WHEN** `StrategyEntry(execution_family="directional")` is loaded for bot7
- **THEN** the desk instantiates `DirectionalExecutionAdapter` for that strategy instance
