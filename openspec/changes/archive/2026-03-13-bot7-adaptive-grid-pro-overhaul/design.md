## Context

Bot7 is a directional mean-reversion lane that inherits `DirectionalStrategyRuntimeV24Controller` — a stripped-down version of the shared EPP v2.4 kernel with MM-only subsystems (edge gate, PnL governor, selective quoting, alpha policy, auto-calibration) permanently disabled. All signal logic lives in `adaptive_grid_v1.py`, which overrides `_resolve_regime_and_targets` to compute bot7 state before the base class runs its sizing/quoting pipeline.

The current implementation has one central controller class with four key methods:
- `_update_bot7_state` — computes all indicators and fires entry signals (the core to change)
- `_detect_absorption` — trade-flow absorption signal (hardcoded 12-trade window to fix)
- `_detect_delta_trap` — delta reversal signal (window config-wired but too small in config)
- `build_runtime_execution_plan` — translates state to spreads/sizing

The paper engine config has `paper_equity_quote: 5000` with current `total_amount_quote: 140` — deploying only 2.8% of equity. Target is 16% deployment (800/5000) at leverage 1x.

## Goals / Non-Goals

**Goals:**
- Fix all miscalibrated parameters so indicators compute meaningful signals on BTC/USDT 10-min bars
- Add `_detect_bb_squeeze` to gate entries on band width, replacing the flat `bot7_min_reversion_pct` distance check
- Add `_signal_cooldown_active` to prevent thrashing on persistent BB band touches
- Wire `bot7_absorption_window` and `bot7_recent_delta_window` to replace all hardcoded `[-12:]` slices
- Tighten probe path: require primary signal alongside secondary (depth imbalance)
- Replace pure ATR grid spacing with BB-geometry-aware spacing (`bb_width × fraction`)
- Update `Bot7AdaptiveGridV1Config` with new fields (all have safe defaults so existing configs remain valid)
- Raise capital deployment in paper config; recalibrate TP/SL/time_limit to BB geometry
- Add 6+ tests covering the new gates and config wiring

**Non-Goals:**
- Changes to shared runtime kernel, risk evaluator, spread engine, regime detector, or other bots
- Live trading config changes (paper only)
- Adding ML/learned signals or external data feeds
- Changing the executor model (TP/SL is handled by the executor framework, not this code)
- Session/time-of-day filter (deferred — adds operational complexity, off-by-default is enough for paper)

## Decisions

### D1: BB width gate replaces flat reversion-distance gate

**Decision**: Replace `bot7_min_reversion_pct` check with `bot7_min_bb_width_pct` check computed in `_detect_bb_squeeze`.

**Rationale**: The flat reversion-distance check (`|bb_basis - mid| / mid >= 0.16%`) is correct in direction but fragile — it measures the *current* distance from mid to basis, which changes as the band contracts. A width gate measures the band's *capacity* for reversion regardless of where mid is within the band. Width is also a natural proxy for the expected round-trip profit: a 80bps-wide band at a 2σ touch implies ~40bps of expected mean reversion, which comfortably covers a 4bps round-trip fee.

**Alternatives considered**:
- Keep flat gate: rejected — doesn't adapt to band geometry
- Use both gates: rejected — redundant; width gate subsumes reversion-distance gate

**Implementation**: `_detect_bb_squeeze(bb_lower, bb_upper, mid) -> bool` returns `True` (squeeze active = block entry) when `(bb_upper - bb_lower) / mid < bot7_min_bb_width_pct`. Called in `_update_bot7_state` before signal scoring.

---

### D2: Signal cooldown as in-memory per-side timestamps

**Decision**: Track `_bot7_last_signal_ts: dict[str, float]` with keys `"buy"` and `"sell"`. Block new entry if `now - last_signal_ts[side] < bot7_signal_cooldown_s`.

**Rationale**: Prevents the most common failure mode — persistent BB band touch causing the bot to re-enter immediately after TP/SL. A 180s cooldown (3 bars on a 1-min chart, ~3 bars on the 10-min sample interval) is long enough to prevent thrashing while short enough that the next legitimate BB touch within the same session is not blocked.

**Alternatives considered**:
- Cooldown on position close event: more accurate but requires hooking into fill events, which is complex across the executor boundary
- State-machine approach (entry→exit→cooldown states): more correct but significantly more code; over-engineered for a config-tweakable time gate

**Reset**: Cooldown resets on bot restart (in-memory only). This is acceptable — a restart naturally represents a changed context.

---

### D3: Probe path requires primary signal

**Decision**: `long_probe` and `short_probe` require `primary_long` (or `primary_short`) to be `True`. `secondary_long` alone no longer qualifies.

**Rationale**: Current code fires probe on `(primary_long OR secondary_long)` — meaning a depth imbalance reading alone (without any absorption or delta-trap confirmation) can open a position. Depth imbalance at 12% threshold is noisy; the OB at BTC shows >12% imbalance routinely. This created excessive false probes. Requiring primary confirmation means probe is a "lower conviction entry gate" not an "alternative entry path."

**Before**: `long_probe = ... and (primary_long or secondary_long)`
**After**: `long_probe = ... and primary_long and (absorption_long or delta_trap_long or secondary_long)`

Wait — this is equivalent since `primary_long = absorption_long or delta_trap_long`. The actual change:
**After**: `long_probe = ... and primary_long` — depth imbalance only upgrades signal score, no longer independently enables probe.

---

### D4: Grid spacing blends BB geometry with ATR

**Decision**: `spacing_pct = max(floor, min(cap, bb_width * bot7_grid_spacing_bb_fraction, atr_mult))`

where `bb_width = (bb_upper - bb_lower) / mid` and `bot7_grid_spacing_bb_fraction = 0.12`.

**Rationale**: Pure ATR spacing was defaulting to the floor too often in low-vol periods (ATR too small relative to price). BB-width spacing naturally scales with the band's geometry — if the band is 1% wide, legs at 0.12% spacing fit 4 legs within the lower half, which is the right density. The `min()` of ATR-based and BB-based spacing prevents overly wide legs in high-ATR regimes.

**Config fields**:
- `bot7_grid_spacing_bb_fraction: 0.12` (new, default=0.12)
- `bot7_grid_spacing_atr_mult: 0.50` (existing, kept)
- Floor/cap remain unchanged

---

### D5: Config field additions are backward-compatible

**Decision**: All new `Bot7AdaptiveGridV1Config` fields use `Field(default=...)` with safe values that preserve existing behaviour if a YAML doesn't include them.

| New field | Default | Safe-default behaviour |
|-----------|---------|----------------------|
| `bot7_absorption_window` | 20 | Same as old hardcoded 12 (conservative) |
| `bot7_recent_delta_window` | 20 | Same as old hardcoded 12 |
| `bot7_min_bb_width_pct` | `0.0080` | Blocks very tight bands; equivalent to old reversion gate |
| `bot7_signal_cooldown_s` | `180` | Adds protection even if not explicitly configured |
| `bot7_grid_spacing_bb_fraction` | `0.12` | Blends with existing ATR spacing |
| `bot7_session_filter_enabled` | `False` | No behaviour change if not set |

**Rationale**: Existing paper configs for other bots are unaffected. The old `bot7_min_reversion_pct` field is kept in Config but no longer used in the signal path (kept to avoid breaking YAML loads that still include it).

## Risks / Trade-offs

**[Risk] Raising total_amount_quote to $800 on $5k equity = 16% deployment** → At leverage 1x this is 16% of capital in resting orders at any time. With 3 legs and SL at 45bps, max loss per full-grid fill = $800 × 0.0045 = $3.60. Daily loss limit is 2% of $5k = $100, so worst case requires ~28 consecutive full-grid SL hits. Acceptable for paper trading.

**[Risk] Tighter stale threshold (20s) may increase "trade_flow_stale" idle periods** → At 20s, any gap >20s in the trade tape silences the bot. BTC on Bitget typically does >3 trades/second in active sessions; 20s gaps are rare but possible in quiet hours. Mitigation: warmup quotes (1 level) maintain market presence during stale periods.

**[Risk] Signal cooldown (180s) reduces daily entry count** → If BTC oscillates at the lower band for 10 minutes, the bot fires once and waits. This is the intended behaviour — thrashing is worse than missing secondary entries — but it does reduce maximum daily fill count from ~10 to ~5 per side. The larger position sizing compensates.

**[Risk] BB width gate blocks entries in low-vol regimes** → When BTC is in a very tight range (vol compression before breakout), bands may be < 80bps wide and all entries are blocked. This is correct — a breakout regime is dangerous for MR — but the bot will be idle during pre-breakout compression. No mitigation needed; idle is the right response.

**[Trade-off] Removing `bot7_min_reversion_pct` from signal path** → The YAML field still loads without error (kept in Config) but is silently unused. This is a minor UX issue. A future cleanup could remove it and add a deprecation warning.

## Migration Plan

1. Apply code changes to `adaptive_grid_v1.py` (new config fields, new methods, signal path changes)
2. Update YAML config with all new and modified parameters
3. Run full test suite — existing tests must pass, new tests must pass
4. Paper engine picks up changes on next bot restart (state is not persisted across restarts for bot7 signal state)
5. Rollback: revert YAML to previous values; code changes are backward-compatible so no code rollback needed for a config-only rollback

## Open Questions

- None blocking implementation. Session filter (`bot7_session_filter_enabled`) is deferred and can be added as a follow-on change without touching any of the core signal path.
