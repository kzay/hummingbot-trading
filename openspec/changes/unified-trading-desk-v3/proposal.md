## Why

The current bot framework (SharedRuntimeKernel, ~13K LOC) grew organically through mixin composition. Bots couple tightly to kernel internals via private attributes (`_ob_imbalance`, `_regime_ema_value`, `_selective_quote_state`), making refactors fragile and untestable. Bot5 and Bot6 embed signal logic directly in their controllers — unlike Bot7's clean `pullback_signals.py` separation — blocking isolated testing and backtest parity. There is no unified abstraction for the trading desk: each bot independently manages order lifecycle, risk checks, and telemetry through inherited mixins, creating duplicated gate metrics, inconsistent state naming, and no portfolio-level risk coordination across bots.

This redesign separates **what to trade** (strategy signals) from **how to trade** (desk execution), enforcing a single integration contract for all current and future bots.

## What Changes

- **BREAKING**: Introduce `TradingDesk` — a single abstraction owning order lifecycle, position tracking, P&L accounting, risk enforcement, and telemetry for all bots. Bots never submit orders directly.
- **BREAKING**: Redefine bot strategies as pure signal generators: `(MarketSnapshot) -> TradingSignal`. No framework imports in strategy code. Enforced via import linting (extending `test_strategy_isolation_contract.py`).
- Introduce `KernelDataSurface` — typed, read-only interface replacing all direct private attribute access from bot code into the kernel.
- Introduce `StrategyRegistry` — declarative production strategy registration (mirroring the backtesting `adapter_registry` pattern). New strategy = 1 signal module + 1 registry entry.
- Introduce `ExecutionAdapter` layer — translates typed signals into orders. Pluggable per strategy family (MM grid, directional single-side, hybrid). Replaces current `RuntimeFamilyAdapter` with a cleaner contract.
- Introduce `DeskRiskGate` — layered risk enforcement at desk level: portfolio-wide (cross-bot), per-bot (daily loss, drawdown, turnover), and per-signal (edge gate, adverse fill). Removes risk logic from strategy code.
- Introduce `TelemetryContract` — typed schema declaration per strategy. The desk handles CSV logging, Redis streaming, and Prometheus export uniformly. Replaces per-bot `_extend_processed_data_before_log()` overrides.
- **Backtest parity**: same signal function runs in production and backtest; only the desk implementation is swapped (live vs simulated).
- Migration is incremental: a compatibility shim wraps existing bots so old and new patterns coexist during transition.

## Capabilities

### New Capabilities
- `trading-desk`: Unified desk abstraction — order lifecycle, position tracking, P&L accounting, fill dedup, state persistence. Single entry point for all bot execution.
- `kernel-data-surface`: Typed read-only market state API — replaces direct private attribute access. Provides mid price, order book, regime, indicators, funding rate, position, equity.
- `strategy-signal-protocol`: Pure signal protocol and registry — strategy reduces to `(MarketSnapshot) -> TradingSignal`. Typed, versioned, no framework imports.
- `execution-adapter`: Signal-to-order translation layer — MM grid builder, directional entry builder, hybrid adapter. Pluggable per strategy family.
- `desk-risk-gate`: Layered risk enforcement at desk level — portfolio risk (cross-bot via Redis), per-bot risk (daily loss, drawdown, turnover), per-signal risk (edge gate, adverse fill, selective quoting).
- `telemetry-contract`: Typed telemetry schema per strategy — desk handles CSV, Redis streams, Prometheus export uniformly.
- `strategy-migration-shim`: Compatibility layer wrapping existing bot controllers as signal generators during incremental migration.

### Modified Capabilities
<!-- No existing spec requirements change — new capabilities wrap/replace internals -->

## Impact

- **Core framework**: `hbot/controllers/runtime/kernel/` — all mixins refactored behind `KernelDataSurface`; `SupervisoryMixin` risk logic moves to `DeskRiskGate`
- **Bot strategies**: `hbot/controllers/bots/bot{1,5,6,7}/` — migrated to pure signal modules one at a time; existing controllers wrapped by shim during transition
- **Backtesting**: `hbot/controllers/backtesting/adapter_registry.py` — aligned with production `StrategyRegistry`; adapters can reuse signal modules directly
- **Services**: `hbot/services/paper_exchange_service/` — becomes one `TradingDesk` implementation (paper desk); live desk wraps HB connectors
- **Contracts**: `hbot/platform_lib/contracts/` — new event schemas for `TradingSignal`, `DeskAction`, `RiskDecision`
- **Tests**: `hbot/tests/controllers/test_strategy_isolation_contract.py` — extended to enforce no-framework-import rule for signal modules
- **Deployment**: No Docker/infra changes — desk runs in-process per bot container
- **Dependencies**: No new external dependencies; only internal restructuring
