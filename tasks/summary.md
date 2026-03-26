# Regime Detection System — Change Summary

## What Was Wrong

### Critical: Label Semantic Mismatch
The regime model predicts **forward volatility levels** (low/normal/elevated/extreme)
but the label mapping pretended these were **directional regimes** (up/down). When the
ML override was active:
- Class 2 ("elevated vol") → mapped to `"up"` → system entered `buy_only` mode
- Class 3 ("extreme vol") → mapped to `"down"` → system entered `sell_only` mode

This caused the system to take directional positions based on volatility predictions,
which is fundamentally wrong. Feature importance confirmed: the top 7 features are
ALL volatility/time features. Zero directional features in the top 15.

### Feature Issues
- **CVD was cumulative** — unbounded sum that grows over time, making the feature
  non-stationary and less useful for ML.
- **`annualized_funding`** — perfect linear transform of `funding_rate`, wasting a
  feature column with zero additional information.
- **No change-of-state features** — all features measured absolute levels, but regime
  *transitions* (vol rising/falling, funding shifting) are arguably more important.

### Missing Infrastructure
- **No regime-to-action mapping** — regime-dependent behavior scattered across files.
- **No per-class metrics** — only overall accuracy tracked, no confusion matrix or
  per-class precision/recall.
- **No feature diagnostics** — no correlation analysis, drift detection, or
  missing data monitoring.
- **No regime validation** — no analysis of forward returns by predicted regime,
  no transition matrices, no persistence statistics.

---

## What Was Changed

### 1. Fixed Label Semantic Mismatch
**File:** [research.py](hbot/controllers/ml/research.py)

`REGIME_LABEL_MAP` now correctly maps:
- 0 → `"vol_low"`, 1 → `"vol_normal"`, 2 → `"vol_elevated"`, 3 → `"vol_extreme"`

Legacy map preserved as `_LEGACY_REGIME_LABEL_MAP` for backward compatibility.

### 2. Composite Regime Inference
**File:** [inference_engine.py](hbot/services/signal_service/inference_engine.py)

New `resolve_composite_regime(vol_label, direction_hint)` function:
- Combines volatility prediction + direction hint → operating regime name
- Low/normal vol + direction → directional regime (up/down)
- Elevated vol + any → `neutral_high_vol` (protective)
- Extreme vol + any → `high_vol_shock` (defensive)

The `predict_regime()` function now accepts a `direction_hint` parameter and
routes through the composite resolver.

### 3. Regime-to-Action Policy Layer
**New file:** [regime_policy.py](hbot/controllers/ml/regime_policy.py)

Clean, configurable mapping from regime → trading constraints:
- `RegimeAction` dataclass: sizing_mult, max_leverage, stop_loss_style, allowed_strategies, etc.
- `RegimePolicy` class: loads from built-in defaults or JSON config
- Per-regime rules:
  - `neutral_low_vol`: full operation (sizing=1.0, all strategies)
  - `neutral_high_vol`: reduced size (0.6), wider spreads (1.5x), no breakouts
  - `up/down`: directional only, no mean reversion (sizing=0.8)
  - `high_vol_shock`: minimal size (0.3), MM-only, wide spreads (3x)

### 4. Feature Fixes & Additions
**File:** [feature_pipeline.py](hbot/controllers/ml/feature_pipeline.py)

**Removed:**
- `annualized_funding` (redundant linear transform)

**Fixed:**
- `cvd` now uses rolling 60-bar sum instead of unbounded cumsum

**Added (change-of-state features):**
- `vol_change_ratio` — short-term vol / long-term vol (vol expanding/contracting)
- `atr_acceleration` — current ATR / lagged ATR (volatility trend)
- `momentum_exhaustion` — price slope vs RSI slope divergence
- `funding_rate_zscore` — rolling z-score of funding rate
- `basis_zscore` — rolling z-score of perp-spot basis

### 5. Per-Class Metrics in Training
**File:** [research.py](hbot/controllers/ml/research.py)

New `_compute_per_class_metrics()` function generates per fold:
- Confusion matrix
- Per-class precision, recall, F1, support
- Results stored in CV metadata for each window

### 6. Feature Diagnostics Module
**New file:** [feature_diagnostics.py](hbot/controllers/ml/feature_diagnostics.py)

- `compute_correlation_report()` — finds highly correlated pairs + group mean correlation
- `compute_drift_report()` — PSI-based distribution shift detection
- `compute_missing_report()` — NaN/missing data per feature
- `feature_group_importance()` — aggregates importances by feature group
- `FEATURE_GROUPS` — structured feature categorization

### 7. Regime Validation Framework
**New file:** [regime_validation.py](hbot/controllers/ml/regime_validation.py)

- `per_regime_forward_returns()` — mean/std/sharpe/skew by predicted regime
- `per_regime_volatility_stats()` — validates vol-based regimes separate vol levels
- `regime_transition_matrix()` — P(next_regime | current_regime)
- `regime_persistence_stats()` — run-length analysis (how long regimes last)
- `regime_class_distribution()` — class balance analysis
- `ablation_feature_groups()` — train with each group removed, measure impact
- `calibration_analysis()` — predicted confidence vs actual accuracy (ECE metric)

### 8. Integrated Validation in Training Pipeline
**File:** [research.py](hbot/controllers/ml/research.py)

The `train_and_evaluate()` function now automatically generates:
- Class distribution report
- Transition matrix and persistence stats
- Forward returns/volatility by predicted regime
- Feature missing data report
- Group importance analysis
- High correlation pairs

All stored in model metadata JSON.

### 9. Signal Consumer Fix
**File:** [signal_consumer.py](hbot/simulation/bridge/signal_consumer.py)

`REGIME_VOL_BUCKET_MAP` updated: class 1 (vol_normal) now maps to `neutral_low_vol`
instead of `neutral_high_vol`, since normal vol doesn't warrant elevated-vol treatment.

---

## Why Each Change Was Made

| Change | Why |
|--------|-----|
| Fix label mismatch | Prevented random directional positions from vol predictions |
| Composite resolver | Correctly separates volatility risk from directional signal |
| Regime policy | Centralizes regime-dependent behavior, makes it configurable |
| CVD windowing | Non-stationary features degrade ML model performance over time |
| Remove annualized_funding | Zero information gain, wasted model capacity |
| Change-of-state features | Regime transitions matter more than absolute levels for timing |
| Per-class metrics | Overall accuracy masks class-specific weaknesses |
| Feature diagnostics | Detect data quality issues before they degrade model |
| Regime validation | Proves regime predictions have economic meaning (or not) |

---

## Expected Impact on Trading Performance

### Immediate (from label fix):
- **Eliminates incorrect directional bias** — the system will no longer randomly go
  long or short when volatility is elevated/extreme.
- **More appropriate risk behavior** — elevated vol triggers protective measures
  (wider spreads, reduced size) instead of directional bets.

### Medium-term (from new features & validation):
- **Better regime transition detection** — change-of-state features capture when
  the market is shifting, not just where it is.
- **Funding rate z-score** — detects unusually crowded positioning before it unwinds.
- **Momentum exhaustion** — early warning of trend reversal.

### Structural (from new modules):
- **Regime policy makes behavior explicit and tunable** — can adjust sizing/risk
  per regime without code changes.
- **Feature diagnostics catch data quality issues** — drift detection, missing data
  monitoring prevent silent model degradation.
- **Validation framework proves model value** — per-regime forward returns show
  whether regime predictions improve trading, not just classification accuracy.

### Robustness:
- All changes are backward-compatible with existing runtime regimes.
- The rule-based detector is unchanged and remains the fallback.
- New features are additive — existing features are preserved (except annualized_funding).
- Composite resolver maps back to the 5 operating regimes the system already understands.

---

## Files Changed

| File | Type | Change |
|------|------|--------|
| `controllers/ml/research.py` | Modified | Fixed label map, added per-class metrics, wired validation |
| `controllers/ml/feature_pipeline.py` | Modified | Fixed CVD, removed annualized_funding, added 5 features |
| `controllers/ml/regime_policy.py` | **New** | Regime-to-action configurable mapping layer |
| `controllers/ml/feature_diagnostics.py` | **New** | Correlation, drift, missing data diagnostics |
| `controllers/ml/regime_validation.py` | **New** | Forward returns, transitions, persistence, calibration |
| `controllers/runtime/v3/risk/regime_gate.py` | **New** | Regime-aware risk layer for TradingDesk |
| `controllers/runtime/v3/risk/desk_risk_gate.py` | Modified | Added optional regime layer slot |
| `services/signal_service/inference_engine.py` | Modified | Fixed labels, added composite resolver |
| `services/signal_service/main.py` | Modified | Wired direction hint into composite regime |
| `services/ml_feature_service/main.py` | Modified | Publishes composite_regime in predictions |
| `simulation/bridge/signal_consumer.py` | Modified | Prefers composite regime, fixed vol bucket mapping |
| `scripts/ml/retrain_and_compare.py` | **New** | Retrain + before/after comparison script |
| `tests/controllers/test_ml/test_research.py` | Modified | Fixed label assertions, added per-class tests |
| `tasks/todo.md` | **New** | Audit and improvement plan |
| `tasks/lessons.md` | **New** | Technical findings and architecture risks |
| `tasks/summary.md` | **New** | This document |

## Next Steps

1. **Retrain model**: `python -m scripts.ml.retrain_and_compare --exchange bitget --pair BTC-USDT`
2. **Enable direction model** training alongside vol model for full composite inference
3. **Tune confidence threshold** — current 0.5 is too low for 4-class problem
4. **Wire RegimeRiskGate** into TradingDesk instantiation (pass `regime=RegimeRiskGate()` to `DeskRiskGate`)
5. **Load regime policy from config** — create `config/regime_policy.json` for per-environment tuning
6. **Monitor feature drift** in production using the new diagnostics
7. **Run ablation tests** to measure contribution of new change-of-state features
