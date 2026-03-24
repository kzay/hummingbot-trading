## 1. Config Schema — New Fields

- [x] 1.1 Add `bot7_absorption_window: int = Field(default=20, ge=6, le=100)` to `Bot7AdaptiveGridV1Config`
- [x] 1.2 Add `bot7_recent_delta_window: int = Field(default=20, ge=6, le=100)` to `Bot7AdaptiveGridV1Config`
- [x] 1.3 Add `bot7_min_bb_width_pct: Decimal = Field(default=Decimal("0.0080"))` to `Bot7AdaptiveGridV1Config`
- [x] 1.4 Add `bot7_signal_cooldown_s: int = Field(default=180, ge=0, le=3600)` to `Bot7AdaptiveGridV1Config`
- [x] 1.5 Add `bot7_grid_spacing_bb_fraction: Decimal = Field(default=Decimal("0.12"), ge=Decimal("0.01"), le=Decimal("0.50"))` to `Bot7AdaptiveGridV1Config`
- [x] 1.6 Keep `bot7_min_reversion_pct` in Config (backward-compat) but add inline comment marking it as unused in signal path

## 2. Controller Init — Cooldown State

- [x] 2.1 Add `self._bot7_last_signal_ts: dict[str, float] = {}` to `Bot7AdaptiveGridV1Controller.__init__`

## 3. New Methods

- [x] 3.1 Implement `_detect_bb_squeeze(self, bb_lower, bb_upper, mid) -> bool` — returns `True` when `(bb_upper - bb_lower) / mid < bot7_min_bb_width_pct`; returns `False` when `mid <= 0`
- [x] 3.2 Implement `_signal_cooldown_active(self, side: str, now: float) -> bool` — returns `True` when `now - self._bot7_last_signal_ts.get(side, 0.0) < bot7_signal_cooldown_s`

## 4. Wire Configurable Windows in Existing Methods

- [x] 4.1 In `_detect_absorption`: replace `recent = trades[-12:]` with `recent = trades[-absorption_window:]` where `absorption_window = int(getattr(self.config, "bot7_absorption_window", 20))`
- [x] 4.2 In `_update_bot7_state`: replace `recent_delta = sum(trade.delta for trade in trades[-12:], _ZERO)` with `recent_delta_window = int(getattr(self.config, "bot7_recent_delta_window", 20))` and `recent_delta = sum(trade.delta for trade in trades[-recent_delta_window:], _ZERO)`

## 5. Signal Path — BB Squeeze Gate

- [x] 5.1 In `_update_bot7_state`, after computing `bb_lower, bb_basis, bb_upper`, call `bb_squeeze = self._detect_bb_squeeze(bb_lower, bb_upper, mid)`
- [x] 5.2 Remove the existing `bot7_min_reversion_pct` reversion-distance gate block (lines 436–446 in current file)
- [x] 5.3 Add squeeze gate: after signal scoring, if `side != "off"` and `bb_squeeze`, set `side = "off"`, `probe_mode = False`, `reason = "bb_squeeze"`

## 6. Signal Path — Probe Tightening

- [x] 6.1 Update `long_probe` condition: remove `or secondary_long` from the gate; keep only `and primary_long`
- [x] 6.2 Update `short_probe` condition: remove `or secondary_short`; keep only `and primary_short`
- [x] 6.3 Verify `secondary_long` / `secondary_short` still contributes to `signal_components` count (no change needed there — this is already separated from the gate)

## 7. Signal Path — Cooldown Gate

- [x] 7.1 Obtain current timestamp: `now_float = float(provider.time()) if provider else time.time()` (reuse pattern already in `_trade_age_ms`)
- [x] 7.2 After full signal / probe signal resolves to `side != "off"`, check `self._signal_cooldown_active(side, now_float)`; if active: `side = "off"`, `probe_mode = False`, `reason = "signal_cooldown"`
- [x] 7.3 When `side != "off"` after all gates (cooldown not active), update `self._bot7_last_signal_ts[side] = now_float`

## 8. Signal Path — Adaptive Grid Spacing

- [x] 8.1 In `_update_bot7_state` spacing computation, extract `bb_width = (bb_upper - bb_lower) / mid if mid > _ZERO else _ZERO`
- [x] 8.2 Compute `bb_spacing = bb_width * to_decimal(getattr(self.config, "bot7_grid_spacing_bb_fraction", Decimal("0.12")))`
- [x] 8.3 Replace `spacing_pct = clip(atr_based, floor, cap)` with `spacing_pct = clip(min(bb_spacing, atr_based) if atr is not None else bb_spacing, floor, cap)` — ATR-only fallback when ATR unavailable

## 9. YAML Config Update

- [x] 9.1 Update indicator periods: `bot7_bb_period: 20`, `bot7_rsi_period: 14`, `bot7_adx_activate_below: 22`, `bot7_adx_neutral_fallback_below: 30`, `atr_period: 14`
- [x] 9.2 Update trade flow timing: `bot7_trade_window_count: 160`, `bot7_trade_stale_after_ms: 20000`
- [x] 9.3 Update signal windows: `bot7_delta_trap_window: 24`, `bot7_depth_imbalance_reversal_threshold: 0.20`
- [x] 9.4 Update warmup: `bot7_warmup_quote_levels: 1`, `bot7_warmup_quote_max_bars: 3`
- [x] 9.5 Update capital: `total_amount_quote: 800`, `max_order_notional_quote: 400`, `max_total_notional_quote: 800`
- [x] 9.6 Update grid sizing: `bot7_max_grid_legs: 3`, `bot7_per_leg_risk_pct: 0.008`, `bot7_total_grid_exposure_cap_pct: 0.025`
- [x] 9.7 Update TP/SL/time: `stop_loss: 0.0045`, `take_profit: 0.0090`, `time_limit: 2400`
- [x] 9.8 Add new fields to YAML: `bot7_absorption_window: 20`, `bot7_recent_delta_window: 20`, `bot7_min_bb_width_pct: 0.0080`, `bot7_signal_cooldown_s: 180`, `bot7_grid_spacing_bb_fraction: 0.12`

## 10. Tests — New Coverage

- [x] 10.1 `test_bot7_bb_squeeze_blocks_entry_when_bands_too_tight`: bands with width < 80bps + valid absorption signal → `active=False`, `reason="bb_squeeze"`
- [x] 10.2 `test_bot7_bb_squeeze_permits_entry_when_bands_wide_enough`: bands width ≥ 80bps + valid absorption → signal fires normally
- [x] 10.3 `test_bot7_signal_cooldown_suppresses_reentry`: activate signal, set `_bot7_last_signal_ts` to recent timestamp, call again → `reason="signal_cooldown"`
- [x] 10.4 `test_bot7_signal_cooldown_not_active_after_expiry`: activate signal, set `_bot7_last_signal_ts` to `now - cooldown_s - 1`, call again → signal fires normally
- [x] 10.5 `test_bot7_probe_requires_primary_signal`: secondary (depth imbalance) with no primary, probe_enabled=True → `active=False` (probe does not fire)
- [x] 10.6 `test_bot7_absorption_window_wired_to_config`: set `bot7_absorption_window=8`, provide exactly 8 trades where last 8 show absorption but last 12 would not → absorption detected
- [x] 10.7 `test_bot7_recent_delta_window_wired_to_config`: set `bot7_recent_delta_window=8`, verify `recent_delta` sums only last 8 trades
- [x] 10.8 `test_bot7_adx_22_gates_trending_regime`: `adx=25`, `regime_name="up"` → `regime_active=False` (ADX above 22 in non-neutral regime)

## 11. Regression Verification

- [x] 11.1 Run full test suite: `pytest hbot/tests/controllers/test_epp_v2_4_bot7.py -v` — all existing tests must pass
- [x] 11.2 Run full test suite: `pytest hbot/tests/controllers/ -v` — no regressions in other controller tests
