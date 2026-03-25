## 1. Core Type Definitions

- [x] 1.1 Create `controllers/runtime/v3/types.py` — define `MarketSnapshot`, `IndicatorSnapshot`, `OrderBookSnapshot`, `PositionSnapshot`, `EquitySnapshot`, `TradeFlowSnapshot`, `RegimeSnapshot`, `FundingSnapshot`, `MlSnapshot` as frozen dataclasses
- [x] 1.2 Create `controllers/runtime/v3/signals.py` — define `TradingSignal`, `SignalLevel`, `TelemetryField`, `TelemetrySchema` as frozen dataclasses
- [x] 1.3 Create `controllers/runtime/v3/orders.py` — define `DeskOrder`, `DeskAction` (typed union: `SubmitOrder`, `CancelOrder`, `ModifyOrder`, `ClosePosition`, `PartialReduce`)
- [x] 1.4 Create `controllers/runtime/v3/risk_types.py` — define `RiskDecision` dataclass with `approved`, `modified_signal`, `reason`, `layer`, `metadata`
- [x] 1.5 Create `controllers/runtime/v3/protocols.py` — define `StrategySignalSource`, `ExecutionAdapter`, `RiskLayer`, `TradingDesk` protocols
- [x] 1.6 Add unit tests for all type definitions — frozen immutability, field validation, default values

## 2. KernelDataSurface

- [x] 2.1 Create `controllers/runtime/v3/data_surface.py` — implement `KernelDataSurface` wrapping `SharedRuntimeKernel`, expose `snapshot()` method
- [x] 2.2 Implement `MarketSnapshot` assembly from kernel state — map `_price_buffer`, `_ob_imbalance`, `_regime_ema_value`, `_position_base`, etc. to typed sub-snapshots
- [x] 2.3 Implement per-tick caching — `snapshot()` computes once per tick, returns cached instance on subsequent calls
- [x] 2.4 Implement lazy sub-snapshot computation — `IndicatorSnapshot`, `TradeFlowSnapshot` computed on first access only
- [x] 2.5 Add unit tests — snapshot immutability, caching behavior, lazy computation, spot vs perp null handling

## 3. Strategy Registry

- [x] 3.1 Create `controllers/runtime/v3/strategy_registry.py` — define `StrategyEntry` dataclass and `STRATEGY_REGISTRY` dict with lazy module loading
- [x] 3.2 Implement `load_strategy(name, config)` factory function — lazy import, config hydration, return `StrategySignalSource` instance
- [x] 3.3 Add unit tests — registry lookup, lazy loading, duplicate key detection, missing module error handling

## 4. Execution Adapters

- [x] 4.1 Create `controllers/runtime/v3/execution/mm_grid.py` — implement `MMGridExecutionAdapter.translate()` with symmetric/skewed grid, spread cap, inventory skew
- [x] 4.2 Create `controllers/runtime/v3/execution/directional.py` — implement `DirectionalExecutionAdapter.translate()` with single-side entries, ATR-scaled barriers
- [x] 4.3 Create `controllers/runtime/v3/execution/hybrid.py` — implement `HybridExecutionAdapter` combining MM grid + directional bias switching
- [x] 4.4 Implement `manage_trailing()` on `DirectionalExecutionAdapter` — trailing stop state machine, partial take-profit, HWM/LWM tracking
- [x] 4.5 Add unit tests — each adapter's translate() with various signal families, inventory skew, barrier computation, no-trade passthrough

## 5. Desk Risk Gate

- [x] 5.1 Create `controllers/runtime/v3/risk/portfolio_gate.py` — implement `PortfolioRiskGate` reading `PORTFOLIO_RISK_STREAM` from Redis
- [x] 5.2 Create `controllers/runtime/v3/risk/bot_gate.py` — implement `BotRiskGate` with daily loss, drawdown, turnover, margin checks
- [x] 5.3 Create `controllers/runtime/v3/risk/signal_gate.py` — implement `SignalRiskGate` with edge gate (EWMA + hysteresis), adverse fill ratio, selective quoting, signal cooldown
- [x] 5.4 Create `controllers/runtime/v3/risk/desk_risk_gate.py` — implement `DeskRiskGate` composing all three layers with short-circuit evaluation
- [x] 5.5 Add unit tests — each layer in isolation, layered composition, rejection cascading, sizing reduction, hysteresis behavior, cooldown timing

## 6. Telemetry Contract

- [x] 6.1 Create `controllers/runtime/v3/telemetry.py` — implement `TelemetryEmitter` accepting `(MarketSnapshot, TradingSignal, RiskDecision)` per tick
- [x] 6.2 Implement CSV output — auto-discover columns from desk base fields + strategy `TelemetrySchema`, write via `CsvSplitLogger`
- [x] 6.3 Implement Redis output — publish `MarketSnapshotEvent` with strategy metadata to `hb.market_data.v1`
- [x] 6.4 Implement fill telemetry — fill WAL + `hb.bot_telemetry.v1` publish with all required fields
- [x] 6.5 Implement daily rollover summary — detect UTC day boundary, write daily.csv row, reset watermarks
- [x] 6.6 Add unit tests — column auto-discovery, missing metadata defaults, fill dedup, daily rollover

## 7. TradingDesk Core

- [x] 7.1 Create `controllers/runtime/v3/trading_desk.py` — implement `TradingDesk` class with the tick loop: snapshot → signal → risk → execute → telemetry
- [x] 7.2 Implement order lifecycle management — submit orders via desk abstraction, track open orders, cancel stale orders, handle fill events
- [x] 7.3 Implement position and P&L tracking — base amount, avg entry, unrealized P&L, daily watermarks, fill WAL dedup
- [x] 7.4 Implement state persistence — write to Redis + disk on state-changing events, restore on restart, replay unprocessed events
- [x] 7.5 Implement `LiveTradingDesk` — wraps HB connector for live/paper modes via existing bridge
- [x] 7.6 Implement `BacktestTradingDesk` — wraps `BacktestPaperDesk` for synchronous backtest execution
- [x] 7.7 Add integration tests — full tick loop with mock strategy, risk gate, adapter; crash recovery; backtest parity

## 8. Strategy Migration Shim

- [x] 8.1 Create `controllers/runtime/v3/migration_shim.py` — implement `StrategyMigrationShim` wrapping legacy controllers
- [x] 8.2 Implement per-bot state extraction rules — map `_bot5_flow_state`, `_bot6_signal_state`, `_pb_state`, bot1 alpha state to `TradingSignal`
- [x] 8.3 Implement snapshot injection — populate legacy controller internal state from `MarketSnapshot` before calling signal update
- [x] 8.4 Implement shadow mode — run shim + native in parallel, compare signals, log divergences
- [x] 8.5 Add unit tests — shim for each bot type, state extraction, no-trade mapping, shadow divergence detection

## 9. Bot Migration — Bot1 (Baseline MM)

- [x] 9.1 Create `controllers/bots/bot1/baseline_signals.py` — extract signal logic from `baseline_v1.py` into pure `StrategySignalSource`
- [x] 9.2 Register `bot1_baseline` in `STRATEGY_REGISTRY` with `execution_family="mm_grid"`
- [ ] 9.3 Run shadow mode comparing shim vs native signals for bot1 — validate equivalence over 24h
- [ ] 9.4 Cut over bot1 to native signal source, remove shim usage

## 10. Bot Migration — Bot7 (Pullback Grid)

- [x] 10.1 Create `controllers/bots/bot7/pullback_signal_source.py` — wrap existing `pullback_signals.py` functions in `StrategySignalSource` protocol
- [x] 10.2 Register `bot7_pullback` in `STRATEGY_REGISTRY` with `execution_family="directional"`
- [ ] 10.3 Migrate trailing stop logic from controller to `DirectionalExecutionAdapter.manage_trailing()`
- [ ] 10.4 Run shadow mode comparing shim vs native signals for bot7 — validate equivalence
- [ ] 10.5 Cut over bot7 to native signal source

## 11. Bot Migration — Bot5 (IFT/JOTA Flow)

- [x] 11.1 Extract `controllers/bots/bot5/flow_signals.py` — pure signal module with flow conviction computation (OB imbalance + trend displacement)
- [x] 11.2 Create `controllers/bots/bot5/flow_signal_source.py` — wrap in `StrategySignalSource` protocol
- [x] 11.3 Register `bot5_ift_jota` in `STRATEGY_REGISTRY` with `execution_family="hybrid"`
- [ ] 11.4 Run shadow mode and cut over

## 12. Bot Migration — Bot6 (CVD Divergence)

- [x] 12.1 Extract `controllers/bots/bot6/cvd_signals.py` — pure signal module with CVD divergence scoring, SMA/ADX trend detection
- [x] 12.2 Create `controllers/bots/bot6/cvd_signal_source.py` — wrap in `StrategySignalSource` protocol
- [x] 12.3 Register `bot6_cvd_divergence` in `STRATEGY_REGISTRY` with `execution_family="directional"`
- [ ] 12.4 Run shadow mode and cut over

## 13. Isolation Contract & CI

- [x] 13.1 Extend `test_strategy_isolation_contract.py` — add rules: signal modules SHALL NOT import from `controllers.runtime`, `hummingbot`, `services`, `simulation`
- [x] 13.2 Add contract test: all registered strategies satisfy `StrategySignalSource` protocol at import time
- [x] 13.3 Add contract test: backtest adapters can instantiate signal modules from the registry (backtest parity validation)

## 14. Cleanup & Legacy Removal

- [ ] 14.1 Remove `StrategyMigrationShim` after all bots are migrated
- [ ] 14.2 Remove legacy bot controller hook overrides (`_compute_alpha_policy`, `_evaluate_all_risk`, `_resolve_regime_and_targets`, `_resolve_quote_side_mode`, `_extend_processed_data_before_log`)
- [ ] 14.3 Remove duplicated gate metrics methods (`_bot1_gate_metrics`, `_bot5_gate_metrics`, etc.)
- [ ] 14.4 Simplify kernel mixins — remove risk logic that moved to `DeskRiskGate`, remove telemetry logic that moved to `TelemetryEmitter`
- [ ] 14.5 Align backtest `adapter_registry` with production `STRATEGY_REGISTRY` — backtest adapters use signal modules + `BacktestTradingDesk`
- [ ] 14.6 Final integration test suite — all bots run through `TradingDesk`, backtest parity confirmed, no legacy code paths remain
