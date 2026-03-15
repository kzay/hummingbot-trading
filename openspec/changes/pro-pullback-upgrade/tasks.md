## 1. Config Parameters

- [x] 1.1 Add ATR-scaled barrier config fields to PullbackV1Config: `pb_sl_atr_mult`, `pb_tp_atr_mult`, `pb_sl_floor_pct`, `pb_sl_cap_pct`, `pb_tp_floor_pct`, `pb_tp_cap_pct`, `pb_dynamic_barriers_enabled`
- [x] 1.2 Add trend quality gate config fields: `pb_basis_slope_bars`, `pb_min_basis_slope_pct`, `pb_trend_sma_period`, `pb_trend_quality_enabled`
- [x] 1.3 Add trailing stop config fields: `pb_trail_activate_atr_mult`, `pb_trail_offset_atr_mult`, `pb_trailing_stop_enabled`
- [x] 1.4 Add partial take config field: `pb_partial_take_pct` (Decimal, default 0.33)
- [x] 1.5 Add entry quality config fields: `pb_limit_entry_enabled`, `pb_entry_offset_pct`, `pb_entry_timeout_s`, `pb_max_entry_spread_pct`, `pb_max_entry_imbalance`, `pb_adverse_selection_enabled`
- [x] 1.6 Add signal diagnostics config fields: `pb_min_signals_warn`, `pb_signal_diagnostics_enabled`

## 2. ATR-Scaled Dynamic Barriers

- [x] 2.1 Implement `_compute_dynamic_barriers()` method on controller: reads `_pb_state["atr"]` and mid, computes clamped SL/TP, returns TripleBarrierConfig with dynamic values
- [x] 2.2 Store dynamic TBC on config object (`self.config._pb_dynamic_tbc`) each tick from `_resolve_regime_and_targets()`, with fallback to static config when ATR unavailable
- [x] 2.3 Override `triple_barrier_config` as `@property` on PullbackV1Config to return `_pb_dynamic_tbc` when set, else parent's static config
- [x] 2.4 Add TP >= SL * 1.5 guard to ensure minimum reward-to-risk ratio

## 3. Trend Quality Gates

- [x] 3.1 Implement `_check_basis_slope()` method: compute slope from `_price_buffer.bars` close prices over `pb_basis_slope_bars`, return True if slope direction matches trade side
- [x] 3.2 Implement `_check_trend_sma()` method: use `_price_buffer.sma(pb_trend_sma_period)`, return True if mid is on correct side of SMA for trade direction
- [x] 3.3 Integrate both gates into `_update_pb_state()` after ADX gate and before pullback zone check; block with "basis_slope_flat" or "trend_sma_against" reasons

## 4. Trailing Stop State Machine

- [x] 4.1 Add trailing stop state fields to `__init__`: `_pb_trail_state` (inactive/tracking/triggered), `_pb_trail_hwm`, `_pb_trail_entry_price`, `_pb_partial_taken`
- [x] 4.2 Implement `_manage_trailing_stop()` method with state machine: inactive → tracking (on profit threshold), tracking → triggered (on retrace from HWM)
- [x] 4.3 Implement close action emission in triggered state: cancel active executors, emit MARKET close for remaining position, use `model_copy()` pattern from position_mixin
- [x] 4.4 Add state reset logic when position goes flat (abs(_position_base) < epsilon)
- [x] 4.5 Call `_manage_trailing_stop()` from `_resolve_regime_and_targets()` each tick

## 5. Partial Profit-Taking at 1R

- [x] 5.1 Implement `_check_partial_take()` method: compute unrealized PnL vs SL distance, emit partial close when PnL >= 1R and `_pb_partial_taken` is False
- [x] 5.2 Set `_pb_partial_taken = True` after emitting partial close action
- [x] 5.3 Integrate with trailing stop: trailing stop tracks remaining position after partial take

## 6. Entry Quality (Limit Entry + Adverse Selection)

- [x] 6.1 Modify `build_runtime_execution_plan()` to compute limit entry spread from BB basis zone boundary when `pb_limit_entry_enabled` is True: first spread targets `bb_basis * (1 - pb_entry_offset_pct)` for longs
- [x] 6.2 Set `executor_refresh_time` to `pb_entry_timeout_s` when limit entry is active
- [x] 6.3 Implement adverse selection gate in `_update_pb_state()`: check spread width (`pb_max_entry_spread_pct`) and opposing depth imbalance (`pb_max_entry_imbalance`), block with "adverse_selection_spread" or "adverse_selection_depth" reason

## 7. Signal Diagnostics

- [x] 7.1 Add `_pb_signal_counter` deque to `__init__`, implement 24h TTL pruning logic
- [x] 7.2 Append timestamp to counter in `_update_pb_state()` when side != "off"
- [x] 7.3 Implement hourly rate-limited warning log when count < `pb_min_signals_warn`
- [x] 7.4 Add `pb_signal_count_24h` to `_extend_processed_data_before_log()` telemetry output
- [x] 7.5 Add signal count to `to_format_status()` output

## 8. State Management Integration

- [x] 8.1 Add new state fields to `_empty_pb_state()`: `basis_slope`, `trend_sma`, `trail_state`, `signal_count_24h`, `dynamic_sl`, `dynamic_tp`
- [x] 8.2 Add all new telemetry keys to `_extend_processed_data_before_log()`
- [x] 8.3 Update `to_format_status()` to include dynamic SL/TP, trail state, signal count

## 9. YAML Config Update

- [x] 9.1 Add all new `pb_*` config params to `epp_v2_4_bot7_pullback_paper.yml` with documented defaults

## 10. Tests

- [x] 10.1 Add tests for ATR-scaled barrier computation (normal, floor clamp, cap clamp, ATR unavailable fallback, TP >= SL * 1.5 guard)
- [x] 10.2 Add tests for basis slope gate (positive slope passes long, flat blocks, insufficient bars permissive)
- [x] 10.3 Add tests for SMA trend gate (above SMA passes long, below blocks, unavailable permissive)
- [x] 10.4 Add tests for trailing stop state machine (activation, HWM tracking, trigger on retrace, short symmetric, reset on flat)
- [x] 10.5 Add tests for partial take at 1R (triggers once, flag prevents re-trigger, amount correct)
- [x] 10.6 Add tests for limit entry spread computation (long, short, floor clamp, disabled fallback)
- [x] 10.7 Add tests for adverse selection filter (wide spread blocks, opposing depth blocks, normal passes, disabled passes)
- [x] 10.8 Add tests for signal frequency counter (counting, pruning, warning threshold, disabled returns -1)

## 11. Win-Rate Improvements (Phase 2)

- [x] 11.1 Z-score absorption: add `pb_absorption_zscore_enabled`, `pb_absorption_zscore_threshold` config; modify `_detect_absorption()` to use z-score when enabled
- [x] 11.2 Tighter probe SL: add `pb_probe_sl_mult` config; modify `_compute_dynamic_barriers()` to apply probe multiplier
- [x] 11.3 Limit-order exits: add `pb_trail_exit_order_type`, `pb_partial_exit_order_type`, `pb_exit_limit_timeout_s` config; modify `_emit_close_action()` to support LIMIT with timeout fallback
- [x] 11.4 Volume-declining pullback filter: add `pb_vol_decline_enabled`, `pb_vol_decline_lookback` config; implement `_check_volume_decline()` method; integrate as gate in `_update_pb_state()`
- [x] 11.5 Time-of-day quality filter: add `pb_session_filter_enabled`, `pb_quality_hours_utc`, `pb_low_quality_size_mult` config; implement `_in_quality_session()` method; integrate in signal conjunction + size scaling
- [x] 11.6 Gradient trend confidence: add `pb_trend_confidence_enabled`, `pb_trend_confidence_min_mult` config; implement `_compute_trend_confidence()` method; apply as size multiplier in `build_runtime_execution_plan()`
- [x] 11.7 RSI divergence booster: add `pb_rsi_divergence_enabled`, `pb_rsi_divergence_lookback` config; implement `_detect_rsi_divergence()` method; boost trend confidence by 20% on divergence
- [x] 11.8 Signal freshness timeout: add `pb_signal_freshness_enabled`, `pb_signal_max_age_s` config; track signal timestamp; block stale signals in `build_runtime_execution_plan()`
- [x] 11.9 Adaptive cooldown: add `pb_adaptive_cooldown_enabled`, `pb_cooldown_min_s`, `pb_cooldown_max_s` config; modify `_signal_cooldown_active()` to scale by trend confidence

## 12. Win-Rate Improvement Tests

- [x] 12.1 TestZScoreAbsorption: z-score fires on large spike, no fire on small, disabled uses multiplier, zero stddev fallback
- [x] 12.2 TestProbeSL: probe reduces SL, non-probe unchanged, floor still applies
- [x] 12.3 TestLimitOrderExits: LIMIT close action, MARKET close action, config reads correctly
- [x] 12.4 TestVolumeDecline: declining passes, increasing blocks, insufficient data permissive, disabled passes
- [x] 12.5 TestTimeOfDay: quality hours pass, off-hours reduce, hard block, disabled passes
- [x] 12.6 TestTrendConfidence: strong trend high mult, weak trend low mult, disabled returns 1
- [x] 12.7 TestRSIDivergence: disabled returns false, insufficient bars returns false
- [x] 12.8 TestSignalFreshness: fresh signal passes, stale blocks, disabled passes
- [x] 12.9 TestAdaptiveCooldown: high confidence short cooldown, low confidence long, disabled uses fixed, disabled expired

## 13. Config + Telemetry Updates

- [x] 13.1 Add all 20 new `pb_*` config params to PullbackV1Config
- [x] 13.2 Add all 20 new params to `epp_v2_4_bot7_pullback_paper.yml`
- [x] 13.3 Add 7 new state fields to `_empty_pb_state()`
- [x] 13.4 Add 7 new telemetry keys to `_extend_processed_data_before_log()`
- [x] 13.5 Add 2 new status lines to `to_format_status()`
