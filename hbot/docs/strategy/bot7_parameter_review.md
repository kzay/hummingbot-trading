# Bot7 (Pullback) Parameter Review

**ID**: P1-QUANT-20260317-1
**Date**: 2026-03-17
**Strategy**: Directional pullback entry with momentum confirmation
**File**: `controllers/bots/bot7/pullback_v1.py`
**Config class**: `PullbackV1Config` (extends `DirectionalStrategyRuntimeV24Config`)

---

## Parameter Inventory

### 1. Indicator Periods (signal)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_bb_period` | int | 20 | [10, 100] | signal | Medium | Bollinger Band SMA lookback; shorter = noisier zones |
| `pb_bb_stddev` | Decimal | 2.0 | unbounded | signal | Medium | BB width multiplier; no Pydantic bounds defined |
| `pb_rsi_period` | int | 14 | [5, 50] | signal | Medium | RSI lookback period |
| `pb_adx_period` | int | 14 | [5, 50] | signal | Low | ADX lookback period; rarely changed from 14 |
| `atr_period` | int | 14 | [5, 50] | signal | Medium | ATR lookback; feeds dynamic barriers, zone, grid spacing |

### 2. RSI Entry Windows (entry)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_rsi_long_min` | Decimal | 35 | unbounded | entry | High | RSI floor for long entry; momentum dip not oversold |
| `pb_rsi_long_max` | Decimal | 55 | unbounded | entry | High | RSI ceiling for long entry |
| `pb_rsi_short_min` | Decimal | 45 | unbounded | entry | High | RSI floor for short entry |
| `pb_rsi_short_max` | Decimal | 65 | unbounded | entry | High | RSI ceiling for short entry |
| `pb_rsi_probe_long_min` | Decimal | 38 | unbounded | entry | Medium | Probe mode RSI floor (long); slightly wider |
| `pb_rsi_probe_long_max` | Decimal | 58 | unbounded | entry | Medium | Probe mode RSI ceiling (long) |
| `pb_rsi_probe_short_min` | Decimal | 42 | unbounded | entry | Medium | Probe mode RSI floor (short) |
| `pb_rsi_probe_short_max` | Decimal | 62 | unbounded | entry | Medium | Probe mode RSI ceiling (short) |

### 3. ADX Range Gate (signal)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_adx_min` | Decimal | 22 | unbounded | signal | High | Minimum ADX for directional structure |
| `pb_adx_max` | Decimal | 40 | unbounded | signal | Medium | Maximum ADX; above = too chaotic |

### 4. Pullback Zone (entry)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_pullback_zone_pct` | Decimal | 0.0015 | unbounded | entry | High | Static floor for pullback zone width around BB basis |
| `pb_band_floor_pct` | Decimal | 0.0010 | unbounded | entry | Medium | Min distance from BB lower/upper band |
| `pb_zone_atr_mult` | Decimal | 0.25 | unbounded | entry | Medium | ATR multiplier for adaptive zone width; zone = max(static, atr*mult/mid) |

### 5. Trade Flow (signal)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_trade_window_count` | int | 160 | [20, 600] | signal | Low | Number of recent trades to load for flow analysis |
| `pb_trade_stale_after_ms` | int | 20000 | [1000, 120000] | signal | Medium | Trades older than this → stale, blocks entry |
| `pb_trade_reader_enabled` | bool | True | — | signal | Low | Master switch for trade flow reader |

### 6. Absorption Detection (signal)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_absorption_window` | int | 20 | [6, 100] | signal | Medium | Window of recent trades for absorption pattern |
| `pb_absorption_min_trade_mult` | Decimal | 2.5 | unbounded | signal | Medium | Fallback multiplier when z-score disabled or stddev=0 |
| `pb_absorption_max_price_drift_pct` | Decimal | 0.0015 | unbounded | signal | Medium | Max price drift during absorption window |

### 7. Delta Trap Detection (signal)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_delta_trap_window` | int | 24 | [8, 120] | signal | Medium | Trade window for delta trap pattern |
| `pb_delta_trap_reversal_share` | Decimal | 0.30 | unbounded | signal | Medium | Share of window for "late" reversal segment |
| `pb_delta_trap_max_price_drift_pct` | Decimal | 0.0020 | unbounded | signal | Low | Max price drift tolerance for delta trap |
| `pb_recent_delta_window` | int | 20 | [6, 100] | signal | Low | Window for recent delta computation (secondary) |

### 8. Depth Imbalance (signal)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_depth_imbalance_threshold` | Decimal | 0.20 | unbounded | signal | Low | Threshold for secondary depth-based confirmation |

### 9. Grid Sizing (sizing)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_max_grid_legs` | int | 3 | [1, 6] | sizing | High | Maximum grid levels per entry signal |
| `pb_per_leg_risk_pct` | Decimal | 0.008 | unbounded | sizing | **Critical** | Position size per grid leg as % of equity |
| `pb_total_grid_exposure_cap_pct` | Decimal | 0.025 | unbounded | sizing | **Critical** | Hard cap on total grid exposure |
| `pb_grid_spacing_atr_mult` | Decimal | 0.50 | unbounded | grid | Medium | ATR multiplier for grid spacing |
| `pb_grid_spacing_floor_pct` | Decimal | 0.0015 | unbounded | grid | Medium | Minimum grid spacing |
| `pb_grid_spacing_cap_pct` | Decimal | 0.0100 | unbounded | grid | Low | Maximum grid spacing |
| `pb_grid_spacing_bb_fraction` | Decimal | 0.12 | unbounded | grid | Medium | Fraction of BB width used for spacing |

### 10. Risk / Hedging (risk)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_hedge_ratio` | Decimal | 0.30 | unbounded | risk | Medium | Hedge target as fraction of directional exposure |
| `pb_funding_long_bias_threshold` | Decimal | -0.0003 | unbounded | risk | Low | Funding rate below which bias = "long" |
| `pb_funding_short_bias_threshold` | Decimal | 0.0003 | unbounded | risk | Low | Funding rate above which bias = "short" |
| `pb_funding_vol_reduce_threshold` | Decimal | 0.0010 | unbounded | risk | Low | Funding rate delta that triggers 50% size reduction |
| `pb_block_contra_funding` | bool | True | — | risk | Medium | Block entry when funding opposes trade direction |

### 11. Probe Mode (entry)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_probe_enabled` | bool | True | — | entry | Medium | Enable/disable probe entry mode |
| `pb_probe_grid_legs` | int | 1 | [1, 2] | entry | Low | Grid legs in probe mode (always small) |
| `pb_probe_size_mult` | Decimal | 0.50 | unbounded | sizing | Medium | Size multiplier for probe entries |

### 12. Signal Cooldown (timing)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_signal_cooldown_s` | int | 180 | [0, 3600] | timing | Medium | Static cooldown between signals (when adaptive disabled) |

### 13. Warmup Quotes (timing)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_warmup_quote_levels` | int | 0 | [0, 2] | timing | Low | Passive quote levels during indicator warmup; disabled by default |
| `pb_warmup_quote_max_bars` | int | 3 | [0, 20] | timing | Low | Max price buffer bars before warmup quotes stop |

### 14. ATR-Scaled Dynamic Barriers (exit/risk)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_dynamic_barriers_enabled` | bool | True | — | exit | High | Enable ATR-scaled SL/TP instead of static barriers |
| `pb_sl_atr_mult` | Decimal | 1.5 | unbounded | risk | **Critical** | SL = ATR × mult / mid; primary loss control |
| `pb_tp_atr_mult` | Decimal | 3.0 | unbounded | exit | High | TP = ATR × mult / mid; reward target |
| `pb_sl_floor_pct` | Decimal | 0.003 | unbounded | risk | **Critical** | Minimum SL percentage (hard floor) |
| `pb_sl_cap_pct` | Decimal | 0.01 | unbounded | risk | Medium | Maximum SL percentage (hard cap) |
| `pb_tp_floor_pct` | Decimal | 0.006 | unbounded | exit | Medium | Minimum TP percentage |
| `pb_tp_cap_pct` | Decimal | 0.02 | unbounded | exit | Low | Maximum TP percentage |

### 15. Trend Quality Gates (signal)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_trend_quality_enabled` | bool | True | — | signal | High | Master switch for basis slope + SMA trend gates |
| `pb_basis_slope_bars` | int | 5 | [2, 30] | signal | Medium | Lookback bars for BB basis slope computation |
| `pb_min_basis_slope_pct` | Decimal | 0.0002 | unbounded | signal | Medium | Minimum basis slope to confirm trend direction |
| `pb_trend_sma_period` | int | 50 | [10, 200] | signal | Medium | Long-period SMA for trend confirmation |

### 16. Trailing Stop (exit)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_trailing_stop_enabled` | bool | True | — | exit | High | Enable trailing stop state machine |
| `pb_trail_activate_atr_mult` | Decimal | 1.0 | unbounded | exit | High | ATR mult for trail activation threshold |
| `pb_trail_offset_atr_mult` | Decimal | 0.5 | unbounded | exit | High | ATR mult for trail offset (retrace distance) |

### 17. Partial Profit-Taking (exit)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_partial_take_pct` | Decimal | 0.33 | unbounded | exit | Medium | Fraction of position to close at 1R |

### 18. Entry Quality (entry)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_limit_entry_enabled` | bool | True | — | entry | High | Use limit orders at zone boundary for entry |
| `pb_entry_offset_pct` | Decimal | 0.001 | unbounded | entry | Medium | Offset from BB basis for limit entry price |
| `pb_entry_timeout_s` | int | 30 | [5, 300] | entry | Medium | Executor refresh/cancel timeout for limit entries |
| `pb_adverse_selection_enabled` | bool | True | — | entry | Medium | Enable spread + depth adverse selection filter |
| `pb_max_entry_spread_pct` | Decimal | 0.0008 | unbounded | entry | Medium | Max top-of-book spread to allow entry |
| `pb_max_entry_imbalance` | Decimal | 0.5 | unbounded | entry | Medium | Max depth imbalance against trade direction |

### 19. Z-Score Absorption (signal)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_absorption_zscore_enabled` | bool | True | — | signal | Medium | Use z-score for absorption instead of fixed mult |
| `pb_absorption_zscore_threshold` | Decimal | 2.0 | unbounded | signal | Medium | Z-score threshold for statistically significant trade |

### 20. Probe SL Tightening (risk)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_probe_sl_mult` | Decimal | 0.75 | unbounded | risk | Medium | Tighter SL multiplier for probe mode entries |

### 21. Limit-Order Exits (exit)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_trail_exit_order_type` | str | "LIMIT" | LIMIT/MARKET | exit | Low | Order type for trailing stop close |
| `pb_partial_exit_order_type` | str | "LIMIT" | LIMIT/MARKET | exit | Low | Order type for partial profit-take close |
| `pb_exit_limit_timeout_s` | int | 15 | [1, 120] | exit | Low | Timeout for limit exit before fallback to MARKET |

### 22. Volume-Declining Pullback Filter (signal)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_vol_decline_enabled` | bool | True | — | signal | Medium | Require declining volume during pullback |
| `pb_vol_decline_lookback` | int | 5 | [2, 20] | signal | Low | Number of windows to split trades into |

### 23. Time-of-Day Quality Filter (timing)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_session_filter_enabled` | bool | True | — | timing | Medium | Enable time-of-day session quality filter |
| `pb_quality_hours_utc` | str | "1-4,8-16,20-23" | — | timing | Medium | UTC hour ranges considered "quality" |
| `pb_low_quality_size_mult` | Decimal | 0.5 | unbounded | sizing | Medium | Size multiplier during off-hours |

### 24. Gradient Trend Confidence (signal)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_trend_confidence_enabled` | bool | True | — | signal | Medium | Enable gradient trend confidence scoring |
| `pb_trend_confidence_min_mult` | Decimal | 0.5 | unbounded | sizing | Medium | Floor multiplier at lowest confidence |

### 25. RSI Divergence Booster (signal)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_rsi_divergence_enabled` | bool | True | — | signal | Low | Enable RSI divergence detection |
| `pb_rsi_divergence_lookback` | int | 10 | [4, 40] | signal | Low | Lookback bars for divergence comparison |

### 26. Signal Freshness Timeout (timing)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_signal_freshness_enabled` | bool | True | — | timing | Medium | Expire stale signals |
| `pb_signal_max_age_s` | int | 120 | [10, 600] | timing | Medium | Max signal age before considered stale |

### 27. Adaptive Cooldown (timing)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_adaptive_cooldown_enabled` | bool | True | — | timing | Medium | Scale cooldown by trend confidence |
| `pb_cooldown_min_s` | int | 90 | [0, 3600] | timing | Medium | Minimum cooldown (high confidence) |
| `pb_cooldown_max_s` | int | 360 | [0, 3600] | timing | Medium | Maximum cooldown (low confidence) |

### 28. Signal Diagnostics (timing)

| Parameter | Type | Default | Range | Category | Sensitivity | Notes |
|-----------|------|---------|-------|----------|-------------|-------|
| `pb_signal_diagnostics_enabled` | bool | True | — | timing | Low | Enable 24h signal frequency tracking |
| `pb_min_signals_warn` | int | 3 | [0, 100] | timing | Low | Warn if fewer than this many signals in 24h |

---

## Parameter Complexity Score

| Metric | Value |
|--------|-------|
| **Total strategy-specific parameters** | **90** |
| **Inherited parameters** | additional (from `DirectionalStrategyRuntimeV24Config`) |
| **Feature toggles (bool)** | 18 |
| **Numeric tuning params** | 72 |
| **Complexity grade** | **Very High** (> 40) — simplification recommended |

The 90-parameter count is more than double the "Very High" threshold.
Even with all 18 feature toggles at their defaults, there are still 72 numeric parameters that form a large combinatorial tuning surface.

---

## Category Distribution

| Category | Count | Params |
|----------|-------|--------|
| **signal** | 30 | indicator periods, ADX gate, absorption, delta trap, depth, z-score, vol decline, trend quality, trend confidence, RSI divergence |
| **entry** | 17 | RSI windows (8), pullback zone (3), probe mode (2), entry quality (4) |
| **exit** | 11 | dynamic barriers TP side (3), trailing stop (3), partial take (1), limit exits (3), dynamic barriers enable (1) |
| **risk** | 10 | dynamic barriers SL side (3), funding (4), hedge ratio (1), probe SL (1), exposure cap (1) |
| **sizing** | 8 | grid legs, per-leg risk, exposure cap, spacing (4), probe size, session/confidence mults |
| **timing** | 11 | cooldown (4), warmup (2), session filter (3), signal freshness (2) |
| **grid** | 3 | spacing ATR mult, floor, cap (counted under sizing above) |

---

## Redundancy Analysis

### 1. Overlapping Effect: Dual Price Drift Caps
- `pb_absorption_max_price_drift_pct` (0.0015) and `pb_delta_trap_max_price_drift_pct` (0.0020) serve the same concept (max allowed price movement during pattern detection) on two nearly identical flow-analysis patterns.
- **Impact**: Tuning one without the other creates inconsistent pattern sensitivity.

### 2. Overlapping Effect: RSI Windows × 8
- 8 RSI boundary params (`pb_rsi_long_min/max`, `pb_rsi_short_min/max`, `pb_rsi_probe_long_min/max`, `pb_rsi_probe_short_min/max`) define 4 overlapping windows.
- Probe windows are mechanically "slightly wider" than primary windows (only 3 units apart).
- **Impact**: 8 interdependent parameters where 2 (center + width) or 3 (center + primary_width + probe_widen) would suffice.

### 3. Overlapping Effect: Absorption Detection Dual Mode
- `pb_absorption_min_trade_mult` (2.5) is the fallback for when `pb_absorption_zscore_enabled` is False or stddev=0.
- When z-score is enabled, `pb_absorption_zscore_threshold` (2.0) controls detection.
- **Impact**: Two parallel detection paths sharing the same behavioral goal; one is a legacy fallback.

### 4. Always-Same-Value Candidates
- `pb_adx_period` and `atr_period` both default to 14 and are conceptually the same lookback for momentum indicators.
- `pb_bb_period` (20) is always used for both band computation and basis slope SMA — the slope code re-derives the SMA from `pb_bb_period`, so `pb_basis_slope_bars` is a lookback offset within the same SMA.

### 5. Overlapping Effect: Static Cooldown vs Adaptive Cooldown
- `pb_signal_cooldown_s` (180) is only used when `pb_adaptive_cooldown_enabled` is False.
- `pb_cooldown_min_s` (90) / `pb_cooldown_max_s` (360) replace it when adaptive is on.
- **Impact**: 3 params where the static one is dead code under default settings.

### 6. Complex Interaction: Grid Spacing Triple Source
- Grid spacing is derived from `min(bb_spacing, atr_spacing)`, then clamped by `pb_grid_spacing_floor_pct` and `pb_grid_spacing_cap_pct`.
- BB spacing = `bb_width × pb_grid_spacing_bb_fraction`.
- ATR spacing = `atr × pb_grid_spacing_atr_mult / mid`.
- **Impact**: 4 interacting params (bb_fraction, atr_mult, floor, cap) for a single output value; hard to reason about which dominates.

### 7. Complex Interaction: Size Multiplier Chain
- Final size = `pnl_governor × funding_risk_scale × session_size_mult × trend_confidence`.
- Each stage is independently tunable, but cascading multipliers make the final effect hard to predict.
- Probe mode adds another `× pb_probe_size_mult`.

### 8. Overlapping Effect: Pullback Zone Static vs Adaptive
- `pb_pullback_zone_pct` (0.0015) is the static floor.
- `pb_zone_atr_mult` (0.25) produces an adaptive width.
- The effective zone is `max(static, adaptive)`, so the static floor is only binding in low-vol.
- **Impact**: In most market conditions, one of these two params is irrelevant.

---

## Simplification Recommendations

### Merge Candidates

| Current Params | Proposed Merge | Rationale |
|---------------|----------------|-----------|
| `pb_rsi_long_min/max` + `pb_rsi_short_min/max` | `pb_rsi_center` (50) + `pb_rsi_half_width` (10) | Symmetric around center; 2 params instead of 4 |
| `pb_rsi_probe_long_min/max` + `pb_rsi_probe_short_min/max` | `pb_rsi_probe_widen` (3) | Single offset added to primary window; 1 param instead of 4 |
| `pb_absorption_max_price_drift_pct` + `pb_delta_trap_max_price_drift_pct` | `pb_flow_max_drift_pct` (0.0018) | Single drift tolerance for all flow-pattern detectors |
| `pb_adx_period` + `atr_period` | `pb_momentum_period` (14) | Both serve same lookback concept |
| `pb_signal_cooldown_s` + `pb_cooldown_min_s` + `pb_cooldown_max_s` | `pb_cooldown_min_s` + `pb_cooldown_max_s` | Remove dead `pb_signal_cooldown_s`; adaptive is always on |

**Net reduction**: 8 → 12 fewer parameters.

### Hardcode Candidates

| Parameter | Current Default | Recommendation |
|-----------|----------------|----------------|
| `pb_trade_reader_enabled` | True | Hardcode True; disabling breaks the entire signal pipeline |
| `pb_probe_grid_legs` | 1 | Hardcode 1; range is [1,2] and probe by definition is minimal |
| `pb_trail_exit_order_type` | "LIMIT" | Hardcode "LIMIT"; MARKET close on trail is suboptimal |
| `pb_partial_exit_order_type` | "LIMIT" | Hardcode "LIMIT"; same rationale |
| `pb_signal_diagnostics_enabled` | True | Hardcode True; diagnostics have zero performance cost |
| `pb_absorption_zscore_enabled` | True | Hardcode True; z-score is strictly better than fixed mult |
| `pb_warmup_quote_levels` | 0 | Hardcode 0; default is disabled, enabling risks unmanaged fills |

**Net reduction**: 7 fewer parameters.

### Derived Candidates

| Parameter | Derivation | Rationale |
|-----------|-----------|-----------|
| `pb_tp_floor_pct` | `pb_sl_floor_pct × 2` | TP floor should always be ≥ 1.5× SL floor (already enforced in code) |
| `pb_tp_cap_pct` | `pb_sl_cap_pct × 2` | Consistent R:R relationship |
| `pb_grid_spacing_floor_pct` | `pb_pullback_zone_pct` | Zone width and spacing floor serve related purposes |
| `pb_probe_sl_mult` | Constant 0.75 or derive from `pb_probe_size_mult` | Probe tightening tracks probe sizing |
| `pb_absorption_min_trade_mult` | `pb_absorption_zscore_threshold + 0.5` | Fallback mult should approximate z-score |

**Net reduction**: 5 fewer parameters.

### Total Simplification Potential

| Action | Reduction |
|--------|-----------|
| Merge candidates | −10 |
| Hardcode candidates | −7 |
| Derived candidates | −5 |
| **Total** | **−22 params (90 → 68)** |

Further reduction to ~40 params would require consolidating feature toggle patterns (many `_enabled` flags could become a single bitmask or feature set).

---

## Risk Parameters Audit

### Position Sizing Bounds

| Parameter | Default | Bounds | Assessment |
|-----------|---------|--------|------------|
| `pb_per_leg_risk_pct` | 0.008 (0.8%) | **unbounded** | **WARN**: No `ge`/`le` constraints. Negative or >100% values are accepted by Pydantic. Should have `ge=0.001, le=0.05`. |
| `pb_total_grid_exposure_cap_pct` | 0.025 (2.5%) | **unbounded** | **WARN**: No Pydantic bounds. Should have `ge=0.005, le=0.10`. |
| `pb_max_grid_legs` | 3 | [1, 6] | OK — bounded. |
| `pb_probe_size_mult` | 0.50 | **unbounded** | **WARN**: Could be set >1, defeating probe purpose. Should have `ge=0.1, le=1.0`. |
| `pb_low_quality_size_mult` | 0.50 | **unbounded** | **WARN**: No bounds. Should have `ge=0.0, le=1.0`. |

### Stop Loss Bounds

| Parameter | Default | Bounds | Assessment |
|-----------|---------|--------|------------|
| `pb_sl_atr_mult` | 1.5 | **unbounded** | **WARN**: Could be set to 0 (no SL) or very large. Should have `ge=0.5, le=5.0`. |
| `pb_sl_floor_pct` | 0.003 (30bps) | **unbounded** | **WARN**: No min bound; could be 0. Should have `ge=0.001`. |
| `pb_sl_cap_pct` | 0.01 (100bps) | **unbounded** | **WARN**: No max bound. Should have `le=0.05`. |
| `pb_probe_sl_mult` | 0.75 | **unbounded** | Minor: could be >1, widening probe SL. Should have `ge=0.3, le=1.0`. |

### Leverage Bounds
- **Not defined in this config class.** Inherited from `DirectionalStrategyRuntimeV24Config`. Verify parent has `leverage` bounded (typically `ge=1, le=20`).

### Hedge Ratio
| Parameter | Default | Bounds | Assessment |
|-----------|---------|--------|------------|
| `pb_hedge_ratio` | 0.30 | **unbounded** | **WARN**: Could be >1 (over-hedge) or negative. Should have `ge=0.0, le=1.0`. |

### Funding Risk Controls
| Parameter | Default | Bounds | Assessment |
|-----------|---------|--------|------------|
| `pb_funding_long_bias_threshold` | -0.0003 | **unbounded** | OK for threshold, but no guard against nonsensical values. |
| `pb_funding_short_bias_threshold` | 0.0003 | **unbounded** | Same. |
| `pb_block_contra_funding` | True | — | OK — enabled by default. |

### Summary: Risk Audit Findings

| Severity | Finding | Affected Params |
|----------|---------|-----------------|
| **HIGH** | Missing Pydantic bounds on critical sizing params | `pb_per_leg_risk_pct`, `pb_total_grid_exposure_cap_pct` |
| **HIGH** | Missing Pydantic bounds on SL params | `pb_sl_atr_mult`, `pb_sl_floor_pct`, `pb_sl_cap_pct` |
| **MEDIUM** | Missing bounds on multiplier params | `pb_probe_size_mult`, `pb_low_quality_size_mult`, `pb_hedge_ratio`, `pb_probe_sl_mult` |
| **MEDIUM** | Missing bounds on all 8 RSI entry window params | `pb_rsi_*_min/max` (could be set to 0/100) |
| **MEDIUM** | Missing bounds on BB stddev | `pb_bb_stddev` (could be 0 or negative) |
| **LOW** | `pb_absorption_min_trade_mult` unbounded | Could be 0, disabling absorption detection |
| **INFO** | Leverage not defined locally | Must verify in parent config class |

### Recommended Bounds Additions

```python
pb_per_leg_risk_pct: Decimal = Field(default=Decimal("0.008"), ge=Decimal("0.001"), le=Decimal("0.05"))
pb_total_grid_exposure_cap_pct: Decimal = Field(default=Decimal("0.025"), ge=Decimal("0.005"), le=Decimal("0.10"))
pb_sl_atr_mult: Decimal = Field(default=Decimal("1.5"), ge=Decimal("0.5"), le=Decimal("5.0"))
pb_sl_floor_pct: Decimal = Field(default=Decimal("0.003"), ge=Decimal("0.001"), le=Decimal("0.02"))
pb_sl_cap_pct: Decimal = Field(default=Decimal("0.01"), ge=Decimal("0.003"), le=Decimal("0.05"))
pb_hedge_ratio: Decimal = Field(default=Decimal("0.30"), ge=Decimal("0.0"), le=Decimal("1.0"))
pb_bb_stddev: Decimal = Field(default=Decimal("2.0"), ge=Decimal("0.5"), le=Decimal("4.0"))
```

---

## Appendix: Feature Toggle Matrix

All 18 feature toggles with their effect scope:

| Toggle | Default | Controls | Safe to hardcode? |
|--------|---------|----------|-------------------|
| `pb_trade_reader_enabled` | True | Trade flow data input | Yes (True) |
| `pb_probe_enabled` | True | Probe entry mode | No — tuning lever |
| `pb_dynamic_barriers_enabled` | True | ATR-scaled SL/TP | No — critical feature |
| `pb_trend_quality_enabled` | True | Basis slope + SMA gates | No — tuning lever |
| `pb_trailing_stop_enabled` | True | Trail stop state machine | No — critical feature |
| `pb_limit_entry_enabled` | True | Limit vs market entry | No — tuning lever |
| `pb_adverse_selection_enabled` | True | Spread + depth filter | No — tuning lever |
| `pb_absorption_zscore_enabled` | True | Z-score absorption mode | Yes (True) |
| `pb_vol_decline_enabled` | True | Volume decline filter | No — tuning lever |
| `pb_session_filter_enabled` | True | Time-of-day filter | No — tuning lever |
| `pb_trend_confidence_enabled` | True | Gradient confidence scaling | No — tuning lever |
| `pb_rsi_divergence_enabled` | True | RSI divergence booster | No — tuning lever |
| `pb_signal_freshness_enabled` | True | Stale signal expiry | No — tuning lever |
| `pb_adaptive_cooldown_enabled` | True | Confidence-scaled cooldown | No — tuning lever |
| `pb_signal_diagnostics_enabled` | True | 24h signal frequency tracking | Yes (True) |
| `pb_block_contra_funding` | True | Contra-funding entry block | No — risk control |
| `pb_warmup_quote_levels` | 0 | Warmup quote count (quasi-toggle) | Yes (0) |
| `pb_warmup_quote_max_bars` | 3 | Warmup bar limit | Conditional on above |
