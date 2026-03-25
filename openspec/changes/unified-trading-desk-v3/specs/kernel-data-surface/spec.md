## ADDED Requirements

### Requirement: KernelDataSurface provides typed read-only market state
The system SHALL define a `KernelDataSurface` class that wraps the existing `SharedRuntimeKernel` and exposes market state through typed, read-only properties. Strategy code SHALL access market data exclusively through `MarketSnapshot` — never through kernel private attributes.

#### Scenario: Strategy reads mid price through snapshot
- **WHEN** a strategy calls `snapshot.mid`
- **THEN** it receives the current mid price as a `Decimal` computed from the kernel's top-of-book

#### Scenario: Strategy cannot mutate snapshot
- **WHEN** a strategy attempts to modify any field on `MarketSnapshot`
- **THEN** a `FrozenInstanceError` is raised because all snapshot dataclasses are frozen

### Requirement: MarketSnapshot is assembled once per tick
The system SHALL compute `MarketSnapshot` exactly once per tick inside `KernelDataSurface.snapshot()` and cache it for the duration of that tick. Sub-snapshots (indicators, order book, position, equity, trade flow) SHALL be lazily computed on first access.

#### Scenario: Multiple snapshot reads in one tick
- **WHEN** the desk reads `snapshot.indicators.ema_20` and later reads `snapshot.indicators.atr_14` within the same tick
- **THEN** both reads use the same cached `IndicatorSnapshot` instance — PriceBuffer is queried only once

#### Scenario: Snapshot expires on next tick
- **WHEN** a new tick begins
- **THEN** the previous tick's cached snapshot is discarded and `snapshot()` computes a fresh one

### Requirement: MarketSnapshot contains all data strategies need
The system SHALL include the following sub-snapshots in `MarketSnapshot`:
- `IndicatorSnapshot`: EMA (configurable periods), ATR, RSI, ADX, Bollinger Bands, MACD from PriceBuffer
- `OrderBookSnapshot`: best bid/ask, spread, depth levels, bid/ask imbalance ratio
- `PositionSnapshot`: base amount, quote balance, net base pct, gross base pct, avg entry price
- `EquitySnapshot`: equity_quote, daily_loss_pct, max_drawdown_pct, daily_pnl_quote
- `TradeFlowSnapshot`: recent trades list, CVD, absorption flags, delta trap flags, stacked imbalance counts
- `RegimeSnapshot`: regime name, regime spec, band_pct, EMA value, ATR value
- `FundingSnapshot`: funding rate, next funding time, mark price (perp only)
- `MlSnapshot`: ML features dict, model version, confidence (if ML enabled)

#### Scenario: Spot strategy receives null perp fields
- **WHEN** a strategy runs on a spot connector
- **THEN** `snapshot.funding` is `None` and `snapshot.position.is_perp` is `False`

#### Scenario: Strategy without ML receives null ML snapshot
- **WHEN** ML features are not configured for a strategy
- **THEN** `snapshot.ml` is `None`

### Requirement: KernelDataSurface wraps existing kernel without rewrite
The system SHALL implement `KernelDataSurface` as a facade over the existing `SharedRuntimeKernel`. The kernel's internal mixin architecture SHALL remain unchanged. The surface SHALL read kernel state through its existing computed values (not re-computing indicators independently).

#### Scenario: Surface reads from kernel's PriceBuffer
- **WHEN** `snapshot.indicators.ema_20` is accessed
- **THEN** the value comes from `self._kernel._price_buffer.ema(20)` — the same PriceBuffer instance the kernel uses

#### Scenario: Kernel refactor does not break surface contract
- **WHEN** a kernel mixin is refactored (e.g., `RegimeMixin` renames an internal variable)
- **THEN** `KernelDataSurface` adapts internally and `MarketSnapshot.regime` continues to work without strategy changes
