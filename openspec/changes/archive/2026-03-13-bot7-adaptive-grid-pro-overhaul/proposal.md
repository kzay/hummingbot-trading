## Why

Bot7's adaptive absorption grid strategy has the right architecture but is miscalibrated at every layer: indicator periods are too short, capital utilisation is 2.8% of equity, TP/SL don't match BB geometry, and a timing incoherence between the trade window (40 trades ≈ 40s) and stale threshold (90s) causes signals to fire on stale market data. The result is a strategy that either sits idle or takes low-quality entries too small to generate meaningful P&L. This overhaul targets 0.5–1%/day on the $5k paper engine by fixing calibration, adding a volatility-compression filter, and raising capital deployment to levels where the math works.

## What Changes

- **Recalibrate all indicator periods** to standard values: BB(20), RSI(14), ATR(14), ADX activate-below=22 — eliminates noisy signals from over-short periods
- **Fix timing incoherence**: trade_window=160 trades, stale_after=20s — signal detection now operates on fresh, sufficient market data
- **Replace flat reversion gate with BB width filter** (`_detect_bb_squeeze`): only enter when BB width > 80bps, ensuring expected reversion covers round-trip fees
- **Add signal cooldown tracker**: reject re-entry on the same BB touch within 180s — prevents thrashing on persistent band touches
- **Wire absorption and delta windows to config** — remove hardcoded `recent[-12:]` in `_detect_absorption` and `recent_delta`
- **Tighten probe signal**: secondary (depth imbalance) alone no longer fires probe; primary confirmation required
- **Adaptive grid spacing from BB geometry**: `spacing = max(floor, bb_width × 0.12)` instead of ATR-only
- **Raise capital deployment**: total_amount_quote $140→$800, 3 grid legs, per-leg risk 0.3%→0.8% of equity
- **Recalibrate TP/SL to BB geometry**: TP=90bps (60–80% of expected half-band reversion), SL=45bps (below BB + noise buffer), time_limit=2400s

## Capabilities

### New Capabilities

- `bot7-bb-squeeze-filter`: BB width gate that blocks entries when bands are too tight for fee-covering reversion — includes `_detect_bb_squeeze` method and `bot7_min_bb_width_pct` config field
- `bot7-signal-cooldown`: Per-side timestamp tracker that enforces minimum time between entries on the same BB touch — prevents signal thrashing
- `bot7-configurable-signal-windows`: Config-driven absorption and delta windows (`bot7_absorption_window`, `bot7_recent_delta_window`) replacing hardcoded 12-trade lookbacks
- `bot7-adaptive-grid-spacing`: BB-geometry-aware grid spacing (`bot7_grid_spacing_bb_fraction`) blended with ATR-based spacing

### Modified Capabilities

- `bot7-probe-signal`: Probe now requires primary signal confirmation — secondary (depth imbalance) alone no longer qualifies as probe trigger

## Impact

- **Modified files**: `hbot/controllers/bots/bot7/adaptive_grid_v1.py`, `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_adaptive_grid_paper.yml`, `hbot/tests/controllers/test_epp_v2_4_bot7.py`
- **No interface changes**: `Bot7AdaptiveGridV1Config` gains new optional fields with safe defaults; existing callers unaffected
- **Paper engine only**: all changes are isolated to bot7's strategy lane; shared runtime kernel, risk evaluator, and other bots are untouched
- **Test surface**: 6+ new unit tests covering new gates and config wiring; existing tests must continue to pass
