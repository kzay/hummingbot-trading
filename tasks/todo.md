# Regime Detection System — Improvement Plan

## Audit Summary

| Area | Status | Notes |
|------|--------|-------|
| Feature pipeline | Good architecture, some redundancy | 77 features, clean separation |
| Label generation | **Critical mismatch** | Vol buckets mapped as directional regimes |
| Training pipeline | Solid | Purged walk-forward CV, deployment gates |
| Inference pipeline | Works but semantic bug | ML override applies wrong regime names |
| Rule-based detector | Sound | EMA+ATR with anti-flap, 5 regimes |
| Regime-to-action | Missing | No systematic mapping layer |
| Validation | Incomplete | No per-class metrics, no calibration |
| Feature diagnostics | Missing | No correlation/drift/staleness tools |

---

## Phase 1: Fix Critical Issues

### P0.1 — Fix Label Semantic Mismatch
- [x] Rename REGIME_LABEL_MAP to reflect actual vol predictions
- [x] Map: 0→vol_low, 1→vol_normal, 2→vol_elevated, 3→vol_extreme
- [x] Update inference engine and signal consumer to use correct names
- [x] Update RegimeSpec keys to match new naming

### P0.2 — Build Composite Regime Inference
- [x] At inference time, combine vol prediction + direction hint
- [x] Produce 2D regime: (vol_state, direction_state) → regime name
- [x] Map composite to practical trading regimes:
  - vol_low + up → trend_up_calm
  - vol_low + down → trend_down_calm
  - vol_low + neutral → neutral_compression
  - vol_normal + up → trend_up
  - vol_normal + down → trend_down
  - vol_normal + neutral → neutral
  - vol_elevated + any → volatile (reduce size)
  - vol_extreme + any → shock (widen/halt)

---

## Phase 2: Feature Improvements

### P1.1 — Remove/Fix Redundant Features
- [x] Remove `annualized_funding` (linear transform of funding_rate)
- [x] Remove NaN-only 4h candle features from feature list (or load 4h data)
- [x] Window CVD feature (rolling 60-bar delta instead of cumsum)

### P1.2 — Add Change-of-State Features
- [x] `vol_change_1h` — 1h realized vol minus 4h realized vol (acceleration)
- [x] `funding_rate_zscore` — rolling z-score of funding rate
- [x] `atr_acceleration` — ATR change rate (current / lagged)
- [x] `momentum_exhaustion` — RSI divergence from price trend

### P1.3 — Add Feature Diagnostics
- [x] Correlation heatmap generation (grouped by feature category)
- [x] Feature drift detection (train vs recent distribution shift)
- [x] Missing/stale data detection per feature

---

## Phase 3: Model & Validation Improvements

### P2.1 — Add Per-Class Metrics
- [x] Confusion matrix per CV fold
- [x] Per-class precision, recall, F1
- [x] Class distribution analysis
- [x] Probability calibration curves

### P2.2 — Regime Validation Framework
- [x] Per-regime forward return analysis
- [x] Regime transition probability matrix
- [x] Regime persistence statistics
- [x] Strategy performance conditioned by predicted regime

---

## Phase 4: Regime-to-Action Layer

### P3.1 — Build Configurable Regime Policy
- [x] Define regime_policy.py with per-regime action rules
- [x] For each regime: allowed_strategies, sizing_mult, risk_limits
- [x] Load from config (YAML/JSON), not hardcoded
- [x] Connect to v3 risk gate and strategy selection

---

## Phase 5: Backtest & Validate

### P4.1 — Before/After Comparison
- [ ] Run current model metrics as baseline
- [ ] Run improved model with fixed labels + new features
- [ ] Compare: accuracy, per-class F1, regime stability
- [ ] Analyze: per-regime forward returns with new labels

---

## Progress Log

| Date | Change | Impact |
|------|--------|--------|
| 2026-03-25 | Initial audit complete | Identified critical label mismatch |
| 2026-03-25 | Fixed label semantic mismatch | Vol predictions no longer trigger wrong directional trades |
| 2026-03-25 | Added composite regime resolver | Vol + direction → operating regime, correct semantics |
| 2026-03-25 | Created regime_policy.py | Clean, configurable regime→action mapping layer |
| 2026-03-25 | Fixed CVD feature (windowed) | Non-stationary cumsum replaced with rolling 60-bar sum |
| 2026-03-25 | Removed annualized_funding | Eliminated redundant linear transform of funding_rate |
| 2026-03-25 | Added 5 change-of-state features | vol_change_ratio, atr_acceleration, momentum_exhaustion, funding_rate_zscore, basis_zscore |
| 2026-03-25 | Added per-class metrics to CV | Confusion matrix, precision/recall/F1 per class per fold |
| 2026-03-25 | Created feature_diagnostics.py | Correlation, drift (PSI), missing data, group importance |
| 2026-03-25 | Created regime_validation.py | Forward returns/vol by regime, transitions, persistence, calibration |
| 2026-03-25 | Wired validation into training | Auto-generates validation report in model metadata |
| 2026-03-25 | Wired composite regime into signal_service | Direction from rule-based detector composes with vol model |
| 2026-03-25 | Enhanced ml_feature_service | Publishes composite_regime when both models available |
| 2026-03-25 | Updated signal_consumer | Prefers composite regime, falls back to vol-only mapping |
| 2026-03-25 | Created regime_gate.py | New risk layer enforces regime policy constraints |
| 2026-03-25 | Updated DeskRiskGate | Accepts optional regime layer (portfolio→bot→regime→signal) |
| 2026-03-25 | Updated test_research.py | Fixed label assertions, added per-class metric tests |
| 2026-03-25 | Created retrain_and_compare.py | Script for before/after comparison with full reporting |
