## ADDED Requirements

### Requirement: StrategySignalSource protocol defines the strategy contract
The system SHALL define a `StrategySignalSource` runtime-checkable protocol with three methods:
- `evaluate(snapshot: MarketSnapshot) -> TradingSignal` — the primary signal generation method
- `warmup_bars_required() -> int` — number of historical bars needed before first signal
- `telemetry_schema() -> TelemetrySchema` — typed declaration of strategy-specific metrics

#### Scenario: Strategy generates a directional buy signal
- **WHEN** `evaluate()` is called with a snapshot showing a pullback to BB basis in an uptrend
- **THEN** the strategy returns `TradingSignal(family="directional", direction="buy", conviction=Decimal("0.85"), ...)` with grid levels and metadata

#### Scenario: Strategy generates no-trade signal
- **WHEN** `evaluate()` is called with a snapshot where no signal conditions are met
- **THEN** the strategy returns `TradingSignal(family="no_trade", direction="off", conviction=Decimal("0"), reason="no_signal_conditions_met")`

#### Scenario: Strategy declares warmup requirement
- **WHEN** the desk initializes a strategy that needs 200 bars for Bollinger Bands
- **THEN** `warmup_bars_required()` returns `200` and the desk seeds the PriceBuffer with at least 200 historical bars before the first `evaluate()` call

### Requirement: Strategy signal modules have zero framework imports
The system SHALL enforce that strategy signal modules (files implementing `StrategySignalSource`) do NOT import from `controllers.runtime`, `hummingbot`, `services`, or `simulation`. Allowed imports are: standard library, `decimal`, `dataclasses`, `typing`, the signal protocol types (`MarketSnapshot`, `TradingSignal`, etc.), and pure utility libraries (numpy, pandas for computation).

#### Scenario: CI rejects signal module with framework import
- **WHEN** a signal module contains `from controllers.runtime.kernel.controller import SharedRuntimeKernel`
- **THEN** the `test_strategy_isolation_contract.py` test fails with a clear error message identifying the forbidden import

#### Scenario: Signal module imports Decimal and dataclasses
- **WHEN** a signal module contains `from decimal import Decimal` and `from dataclasses import dataclass`
- **THEN** the isolation test passes because these are allowed standard library imports

### Requirement: TradingSignal is a typed immutable dataclass
The system SHALL define `TradingSignal` as a frozen dataclass with the following required fields:
- `family`: Literal["mm_grid", "directional", "hybrid", "no_trade"]
- `direction`: Literal["buy", "sell", "both", "off"]
- `conviction`: Decimal in [0, 1]
- `target_net_base_pct`: Decimal (signed position target)
- `levels`: list[SignalLevel] (spread + size per level, may be empty for no_trade)
- `metadata`: dict[str, Any] (strategy-specific telemetry values)
- `reason`: str (human-readable explanation)

`SignalLevel` SHALL be a frozen dataclass with: `side`, `spread_pct`, `size_quote`, `level_id`.

#### Scenario: Signal with MM grid levels
- **WHEN** a market-making strategy generates a signal
- **THEN** `levels` contains entries for both buy and sell sides with spread percentages and sizes in quote currency

#### Scenario: Signal metadata flows to telemetry
- **WHEN** a strategy sets `metadata={"flow_conviction": 0.85, "ob_imbalance": 0.3}`
- **THEN** these values appear in the CSV and Redis telemetry output for that tick

### Requirement: StrategyRegistry enables declarative strategy registration
The system SHALL define a `STRATEGY_REGISTRY` dict mapping strategy names to `StrategyEntry` dataclasses. Each entry SHALL specify: `module_path`, `signal_class`, `config_class`, `execution_family`, and optional `risk_profile`. The registry SHALL support lazy module loading (import on first use).

#### Scenario: Register a new strategy
- **WHEN** a developer adds an entry `"bot8_momentum": StrategyEntry(module_path="controllers.bots.bot8.momentum_signals", ...)` to the registry
- **THEN** the desk can instantiate and run the strategy without any other code changes

#### Scenario: Registry rejects duplicate names
- **WHEN** two entries share the same key in `STRATEGY_REGISTRY`
- **THEN** Python raises a dict key conflict at module load time (standard dict behavior)

#### Scenario: Lazy loading defers import cost
- **WHEN** the desk starts with strategy "bot7_pullback"
- **THEN** only `controllers.bots.bot7.pullback_signals` is imported — other strategy modules are NOT loaded
