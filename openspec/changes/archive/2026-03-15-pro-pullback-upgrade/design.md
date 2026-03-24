## Context

Bot7's `pullback_v1.py` is a trend-aligned pullback grid strategy with correct signal infrastructure: regime gates, ADX range filtering, BB-basis pullback zone detection, absorption/delta-trap detectors, contra-funding gate, and adaptive grid sizing. However, fixed SL/TP (45/90bps), market-order entries, no trailing stop, and no trend quality filtering leave ~15-25bps of edge on the table per trade. These gaps compound to negative expected value despite correct signal logic.

The strategy runs on the `DirectionalRuntimeController` → `DirectionalRuntimeAdapter` → `MarketMakingRuntimeAdapter` chain. Executor SL/TP flows through `MarketMakingRuntimeAdapter.get_executor_config()` at `runtime/market_making_core.py:107`, reading `controller.config.triple_barrier_config`. PositionExecutor barriers are **immutable after creation** — any dynamic SL/TP must be set before the executor is created.

All changes are confined to `pullback_v1.py` (controller + config) and its YAML config. No shared runtime, base class, or executor framework modifications.

## Goals / Non-Goals

**Goals:**
- ATR-scaled SL/TP that adapts to current volatility (biggest single edge improvement)
- Trend quality filtering to eliminate flat/counter-trending false signals
- Code-side trailing stop to let winners run beyond the initial TP
- Partial profit-taking at 1R to lock in edge and reduce drawdown
- Limit-order entries to improve average fill by 5-10bps
- Multi-timeframe trend confirmation via long-period SMA
- Adverse selection entry filter (spread width + depth)
- Signal frequency diagnostics for observability

**Non-Goals:**
- Modifying shared runtime kernel, base classes, or executor framework
- Adding new indicator methods to PriceBuffer (compute from existing `.bars` and `.sma()`)
- Dynamic executor stop updates (immutable after creation — trailing stop is code-side only)
- Multi-symbol or cross-pair correlation signals
- ML-based signal generation or parameter optimization

## Decisions

### D1: ATR-scaled SL/TP injection via `_dynamic_triple_barrier_config()` property

**Decision**: Override the `triple_barrier_config` property on `PullbackV1Config` to return ATR-scaled values dynamically, rather than overriding the adapter's `get_executor_config()`.

**Rationale**: `market_making_core.py:107` reads `controller.config.triple_barrier_config` — if the config object returns a dynamically-computed value, the adapter picks it up without any adapter-level override. This is the cleanest injection point. The controller stores the latest ATR in `_pb_state["atr"]` each tick, which the config property can reference via the controller backref.

**Alternative considered**: Override `_make_runtime_family_adapter()` to return a custom adapter. Rejected because it adds a new class in the adapter chain and couples the strategy to adapter internals.

**Implementation**: Add a method `_dynamic_triple_barrier_config()` on the controller that computes ATR-scaled SL/TP each tick and caches the result. The `build_runtime_execution_plan()` and `_resolve_regime_and_targets()` methods already run each tick and update `_pb_state["atr"]`. Before returning, store the dynamic TBC on `self.config._pb_dynamic_tbc`. Override `triple_barrier_config` as a `@property` on `PullbackV1Config` that returns `_pb_dynamic_tbc` when set, else falls back to the parent's static config.

**Clamping**: `SL = clamp(pb_sl_atr_mult * ATR / mid, pb_sl_floor_pct, pb_sl_cap_pct)`, same pattern for TP. Defaults: `pb_sl_atr_mult=1.5`, `pb_tp_atr_mult=3.0`, floor=30bps/60bps, cap=100bps/200bps.

### D2: BB basis slope computed from raw PriceBuffer bars

**Decision**: Compute slope directly from `self._price_buffer.bars` OHLC close prices rather than adding a new PriceBuffer method.

**Rationale**: `bars` returns `list[MinuteBar]` with `.close` attribute. Slope = `(bars[-1].close - bars[-N].close) / bars[-N].close`. This needs ~5 lines of code in the controller, no PriceBuffer modification. The `sma()` method already exists for the long-period SMA gate.

**Lookback**: `pb_basis_slope_bars` (default 5) — how many bars back to measure the slope. Short enough to react to recent direction changes, long enough to filter noise.

### D3: Code-side trailing stop as state machine in `_manage_trailing_stop()`

**Decision**: Implement trailing stop as a state machine called from `_resolve_regime_and_targets()` that emits `StopExecutorAction` when triggered, rather than modifying executor barriers.

**Rationale**: PositionExecutor barriers are immutable after creation. The only way to implement a trailing stop is to track the high-water mark externally and emit a close action (market order) when price retraces beyond the trail offset. This runs in the existing tick loop.

**State machine states**:
1. `inactive` — no position or position not yet in profit
2. `tracking` — position profit ≥ `pb_trail_activate_atr_mult * ATR`; tracking high-water mark
3. `triggered` — price retraced by `pb_trail_offset_atr_mult * ATR` from HWM; emit close action

**Position tracking**: Use `self._position_base` (already available from `PositionMixin`) and current mid price to compute unrealized PnL. Entry price stored at signal activation time.

**Interaction with partial take**: Trailing stop tracks the *remaining* position after partial take. The partial take at 1R reduces position size, then the trailing stop manages the remainder.

### D4: Partial profit-taking via close executor at 1R

**Decision**: When unrealized PnL reaches 1x the SL distance (1R), emit a `CreateExecutorAction` with a market close for `pb_partial_take_pct` (default 33%) of position size.

**Rationale**: Locking in 33% at 1R reduces variance and ensures positive EV even if the remaining 67% trails out at breakeven. The partial close uses the same `PositionExecutorConfig` pattern as `position_mixin.py:71-87` (model_copy with MARKET order type, no barriers).

**One-shot guard**: Track `_pb_partial_taken` flag per position to prevent repeated partial closes on the same position.

### D5: Limit entry at zone boundary via execution plan spread override

**Decision**: When signal fires, instead of using the current grid spacing as the spread (which results in a market-like entry), set the first level's spread to place the limit order at the BB basis zone boundary: `entry_spread = (mid - bb_basis * (1 - pb_entry_offset_pct)) / mid` for longs.

**Rationale**: The existing `build_runtime_execution_plan()` already constructs `buy_spreads`/`sell_spreads` which translate to limit order prices via the adapter. By setting the first spread to target the zone boundary instead of a fixed grid spacing, we get limit entry without changing the adapter or executor creation path. Timeout handled by `executor_refresh_time` — if not filled within `pb_entry_timeout_s`, the executor refreshes (cancels and re-evaluates).

**Alternative considered**: Override `get_executor_config()` to set a specific entry price. Rejected because it requires adapter modification and the spread-based approach works within the existing flow.

### D6: Long-period SMA gate from existing PriceBuffer.sma()

**Decision**: Use `self._price_buffer.sma(pb_trend_sma_period)` (default 50) as a trend filter. Long only when `mid > sma_50`. Short only when `mid < sma_50`.

**Rationale**: `PriceBuffer.sma()` already exists and works. A 50-period SMA on 1-minute bars approximates a higher timeframe trend direction. No new code in PriceBuffer needed.

**Gate position**: Checked in `_update_pb_state()` after regime gate, before RSI gate. If SMA is unavailable (insufficient bars), the gate passes (permissive during warmup).

### D7: Adverse selection filter checks spread + depth before entry

**Decision**: Add a pre-entry check: if `current_spread > pb_max_entry_spread_pct` or `abs(depth_imbalance) > pb_max_entry_imbalance` opposing the trade direction, block entry for that tick.

**Rationale**: Wide spreads and thin books mean adverse selection eats the edge. The depth imbalance and spread data are already available in `_update_pb_state()` from the trade reader.

**Implementation**: Additional gate in the signal conjunction, after all other gates and before cooldown. Adds `reason = "adverse_selection"` when blocked.

### D8: Signal frequency counter — observability only

**Decision**: Maintain a rolling 24h counter of signal activations. Log warning when below `pb_min_signals_warn` threshold. No behavioral change.

**Rationale**: If the gate conjunction is too tight, we need to know. A simple deque of timestamps with 24h TTL and a periodic log check is sufficient.

## Risks / Trade-offs

**[Risk] ATR unavailable during warmup → fallback to static SL/TP**
→ Mitigation: When `_pb_state["atr"]` is None, fall back to `config.stop_loss` / `config.take_profit` (the existing static values). This is the current behavior, so no regression.

**[Risk] Trailing stop emits close action while executor has open SL → double close**
→ Mitigation: Before emitting trailing stop close, check if active executors exist for this position. Cancel active executors first via `_cancel_active_quote_executors()`, then emit the close action. Also cap the close amount at the current actual position size.

**[Risk] Limit entry timeout too short → signals fire but never fill**
→ Mitigation: Default `pb_entry_timeout_s = 30` matches `executor_refresh_time`. If signal persists across ticks, new limit orders are placed at updated zone boundary prices. Configurable via YAML.

**[Risk] Partial take at 1R + trailing stop adds complexity → potential state bugs**
→ Mitigation: Clear state machine with explicit transitions. Reset all trailing/partial state when position goes flat. Unit test each state transition independently.

**[Risk] ~20 new config params increase misconfiguration surface**
→ Mitigation: All params have sensible defaults that match current behavior when not set. Static SL/TP remains as the floor/cap, so misconfigured ATR multipliers can't produce absurd values.

**[Trade-off] Code-side trailing stop has tick-level granularity (10s sample interval)**
→ In extreme moves, the trailing stop may trigger 10s late. Acceptable for a paper-first strategy; production deployment can tighten `sample_interval_s`.

**[Trade-off] Limit entry reduces fill rate but improves fill quality**
→ Signal frequency diagnostics (D8) will surface if fill rate drops too low. `pb_entry_offset_pct` is tunable.
