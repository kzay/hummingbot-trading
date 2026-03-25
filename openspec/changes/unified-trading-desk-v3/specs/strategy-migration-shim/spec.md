## ADDED Requirements

### Requirement: StrategyMigrationShim wraps legacy controllers as signal sources
The system SHALL implement `StrategyMigrationShim` that adapts any existing bot controller (inheriting `SharedRuntimeKernel`) into a `StrategySignalSource`. The shim SHALL call the legacy controller's signal update method and extract a `TradingSignal` from its internal state dict.

#### Scenario: Bot5 legacy controller wrapped by shim
- **WHEN** `StrategyMigrationShim` wraps `Bot5IftJotaV1Controller`
- **THEN** calling `evaluate(snapshot)` triggers the legacy `_bot5_update_flow_state()` logic and returns a `TradingSignal` with `direction`, `conviction`, and `target_net_base_pct` extracted from `_bot5_flow_state`

#### Scenario: Bot1 legacy controller wrapped by shim
- **WHEN** `StrategyMigrationShim` wraps `Bot1BaselineV1Controller`
- **THEN** calling `evaluate(snapshot)` runs the legacy alpha policy logic and returns a `TradingSignal` with `family="mm_grid"` based on the kernel's regime and edge state

### Requirement: Shim translates legacy state dict to TradingSignal
The system SHALL map legacy bot state dicts to `TradingSignal` fields using per-bot extraction rules:
- `direction` maps from state dict's `"direction"` field (or `"off"` if absent)
- `conviction` maps from state dict's `"conviction"` or `"maker_score"` field
- `target_net_base_pct` maps from state dict's `"target_net_base_pct"` field
- `family` is inferred from the bot's execution family (MM controllers → `"mm_grid"`, directional → `"directional"`)
- `metadata` includes all state dict fields for telemetry continuity

#### Scenario: Directional bot state maps to directional signal
- **WHEN** bot7's `_pb_state` contains `{"active": True, "side": "buy", "signal_score": 0.8, "grid_levels": 2}`
- **THEN** the shim returns `TradingSignal(family="directional", direction="buy", conviction=Decimal("0.8"), levels=[...2 levels...])`

#### Scenario: Inactive bot state maps to no_trade signal
- **WHEN** bot7's `_pb_state` contains `{"active": False, "reason": "no_pullback_zone"}`
- **THEN** the shim returns `TradingSignal(family="no_trade", direction="off", conviction=Decimal("0"), reason="no_pullback_zone")`

### Requirement: Shim injects MarketSnapshot into legacy controller
The system SHALL provide the `MarketSnapshot` data to the legacy controller by populating the kernel's internal state from the snapshot before calling the legacy signal update. This ensures the legacy controller's indicator reads (`self._price_buffer`, `self._ob_imbalance`, etc.) return values consistent with the snapshot.

#### Scenario: Legacy controller reads price buffer through shim
- **WHEN** `evaluate(snapshot)` is called on a shimmed bot5 controller
- **THEN** the legacy controller's `self._price_buffer` returns values consistent with `snapshot.indicators` and `self._ob_imbalance` equals `snapshot.order_book.imbalance`

### Requirement: Shim and native signals coexist during migration
The system SHALL support running some bots via shim and others as native `StrategySignalSource` implementations simultaneously. The `TradingDesk` SHALL treat both identically — the shim's output is a standard `TradingSignal`.

#### Scenario: Mixed deployment during migration
- **WHEN** bot1 runs via shim and bot7 runs as native signal source
- **THEN** both produce `TradingSignal` objects, both are processed by the same `TradingDesk` tick loop, and both emit telemetry through the same `TelemetryEmitter`

### Requirement: Shadow mode validates signal equivalence
The system SHALL support a shadow mode where both the shim and a new native signal source run on the same `MarketSnapshot`. The desk SHALL compare their outputs tick-by-tick and log divergences without affecting execution (the shim's signal is used for actual trading).

#### Scenario: Shadow comparison detects divergence
- **WHEN** shadow mode is active for bot7 and the shim produces `conviction=0.85` while the native module produces `conviction=0.82`
- **THEN** the desk logs a divergence event with both values, the delta, and the tick timestamp — but uses the shim's signal for execution

#### Scenario: Shadow comparison confirms equivalence
- **WHEN** shadow mode runs for 24 hours with max divergence below the configured threshold
- **THEN** the operator can safely cut over to the native signal source and disable the shim
