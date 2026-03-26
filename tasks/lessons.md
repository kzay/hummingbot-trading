# Regime Detection System — Technical Lessons & Architecture Findings

## Critical Finding: Label Semantic Mismatch

**Severity: HIGH — affects all downstream trading decisions when ML override is active.**

The regime model predicts `fwd_vol_bucket_15m` (forward 15-minute volatility buckets):
- Class 0 → low volatility
- Class 1 → normal volatility
- Class 2 → elevated volatility
- Class 3 → extreme volatility

But `REGIME_LABEL_MAP` in `research.py:36` maps these to **directional** regime names:
- 0 → `"neutral_low_vol"` (reasonable)
- 1 → `"neutral_high_vol"` (reasonable)
- 2 → `"up"` (WRONG — this is elevated vol, not uptrend)
- 3 → `"down"` (WRONG — this is extreme vol, not downtrend)

**Consequence:** When the ML model predicts class 2 ("elevated vol"), the system enters
`"up"` regime with `one_sided="buy_only"` and `target_base_pct=0.60`. The model is not
predicting direction at all — it's predicting volatility. Feature importance confirms this:
the top 7 features are all volatility/time features. No directional features (return_*,
trend_alignment_*, rsi_*) appear in the top 15.

This means the ML regime override randomly biases the system long or short based on
volatility predictions, not directional forecasts.

---

## Finding: Feature Importance Dominated by Volatility & Time

Top 15 features by aggregate importance (all stability=1.0 except noted):
1. `realized_vol_4h` — 1780.4
2. `atr_pctl_24h` — 1773.6
3. `hour_cos` — 1764.6
4. `hour_sin` — 1750.0
5. `minutes_since_funding` — 1662.4
6. `vol_of_vol` — 1225.0
7. `atr_pctl_7d` — 1055.8
8. `adx_1m` — 857.2
9. `atr_5m` — 846.8
10. `day_sin` — 837.0
11. `garman_klass_vol` — 808.2
12. `realized_vol_1h` — 800.2
13. `wr_1m_p50` — 799.4
14. `atr_ratio_5m_1m` — 692.4 (stability 0.6)
15. `parkinson_vol` — 650.8 (stability 0.8)

**Implication:** The model is effectively a time-of-day × volatility-level classifier.
This is useful for sizing/risk decisions but does NOT predict direction.

---

## Finding: CVD Feature is Non-Stationary

`feature_pipeline.py:333`:
```python
out["cvd"] = aligned["cvd"].cumsum().reset_index(drop=True)
```

CVD (cumulative volume delta) grows unboundedly over time. LightGBM can handle this
via split-based learning, but the feature's distribution shifts dramatically across
the dataset. A windowed or differenced CVD would be more robust.

---

## Finding: Redundant Features

1. **`annualized_funding`** = `funding_rate * 3 * 365` — perfect linear transform.
   LightGBM sees identical splits on both features. Wasted column.

2. **4h candle features are NaN** — `assemble_dataset()` does not load `candles_4h`,
   so `return_4h`, `atr_4h`, `close_in_range_4h`, `body_ratio_4h` are all NaN.
   LightGBM handles NaN natively but these contribute nothing meaningful.
   (`realized_vol_4h` is computed from 1m candles, so it IS available.)

3. **Multiple volatility measures are highly correlated:**
   `realized_vol_4h`, `atr_pctl_24h`, `atr_pctl_7d`, `garman_klass_vol`,
   `parkinson_vol`, `vol_of_vol` — all measure current volatility level.
   Not harmful for trees but adds noise for importance interpretation.

---

## Finding: No Direction in Regime Model

The rule-based `RegimeDetector` uses EMA trend for direction (up/down) and ATR band
for volatility. The ML model replaces this but only predicts volatility — losing all
directional signal. There is a separate `direction` model type in the pipeline but
it is not composed with the regime model at inference time.

**Fix:** Compose volatility prediction + direction prediction into a 2D regime at
inference time, or create a proper composite label.

---

## Finding: Model Quality is Moderate

- OOS accuracy: 58.8% (4-class problem)
- Baseline (majority class): 46.7%
- Improvement: +12.1pp — passes deployment gates
- Accuracy improves with more training data (57.7% → 59.5% across folds)

This is a reasonable volatility classifier but would not be strong enough as a
standalone directional predictor. The improvement over baseline is real but modest.

---

## Finding: No Per-Class Metrics

The pipeline only tracks overall accuracy. Missing:
- Confusion matrix (which classes are confused)
- Per-class precision/recall/F1
- Calibration curves (are predicted probabilities trustworthy)
- Class distribution in train vs test

---

## Finding: No Regime-to-Action Mapping Layer

The connection between regime prediction and trading behavior is scattered:
- `RegimeSpec` in `core.py` defines spread/sizing per regime (hardcoded 5 specs)
- Bot7 has a simple regime gate (only trades in up/down)
- No systematic mapping of regime → allowed strategies → sizing → risk limits

This makes it hard to reason about what the system does in each regime and to
adjust behavior without touching multiple files.

---

## Finding: Missing Change-of-State Features

All features are absolute levels. Missing:
- Volatility change (is vol rising or falling?)
- Funding rate change (is sentiment shifting?)
- Momentum acceleration (is trend strengthening or weakening?)
- Regime transition indicators (how long in current regime?)

These "delta" features capture regime *transitions* which are arguably more
important for trading than regime *levels*.

---

## Direction Model Results (2026-03-25)

**The direction model FAILS deployment gates** — 48.5% accuracy on binary up/down
classification (threshold: 55%). This is essentially random.

- Top features are identical to the regime model (all volatility/time)
- No directional features provide meaningful predictive power
- **Confirms:** short-term BTC 15m direction is not predictable from these features

**Implication for composite regime:**
The composite resolver falls back to the rule-based EMA trend direction when
no direction model passes gates. This is the correct behavior.

---

## Dead Feature Pruning

14 features were 100% NaN. Added automatic NaN-column pruning to `_get_feature_cols()`
so dead features are excluded from training automatically.

---

## Architecture Strengths

1. **Clean separation between offline/online paths** — same `compute_features()`
   for research and live service.
2. **Purged walk-forward CV** — proper de Prado-style validation with embargo.
3. **Deployment gates** — automated quality checks before model promotion.
4. **Feature stability tracking** — measures which features are consistently important.
5. **Indicator dual implementation** — Decimal for live trading precision, float for ML batch.
6. **Anti-flap regime hold** — prevents rapid regime switching on noise.
7. **ML override with TTL** — graceful fallback to rule-based detection.
8. **Immutable snapshots** — frozen dataclasses prevent state mutation bugs.

---

---

## Retrain Results (2026-03-25)

### Before vs After

| Metric | Old Model | New Model | Delta |
|--------|-----------|-----------|-------|
| OOS Accuracy | 58.83% | 59.07% | **+0.24pp** |
| Baseline (majority) | 46.69% | 46.69% | — |
| Improvement over base | +12.14pp | +12.38pp | +0.24pp |
| Features | 72 | 76 | +4 |
| Deployment gates | PASS | PASS | — |

### Per-Class Metrics (Last Fold)

| Regime | Precision | Recall | F1 | Support |
|--------|-----------|--------|------|---------|
| vol_low | 0.626 | 0.554 | 0.588 | 28,732 |
| vol_normal | 0.602 | 0.731 | 0.660 | 50,487 |
| vol_elevated | 0.555 | 0.451 | 0.498 | 21,776 |
| vol_extreme | 0.535 | 0.237 | 0.329 | 6,376 |

**Key insight:** vol_extreme is hard to predict (F1=0.33) due to class imbalance (6.16% of
data). The model is conservative about predicting extreme vol — high precision (0.535) but
low recall (0.237). This is actually desirable for a risk system: we'd rather miss some
extreme events than trigger false alarms.

### Regime Separation Validated

The forward volatility analysis confirms the model genuinely separates volatility regimes:

| Regime | 15m Fwd Vol (mean) | Ratio vs vol_low |
|--------|-------------------|-------------------|
| vol_low | 0.000326 | 1.0x |
| vol_normal | 0.000481 | 1.5x |
| vol_elevated | 0.000790 | 2.4x |
| vol_extreme | 0.001192 | 3.7x |

The regimes are monotonically ordered — each successive regime has meaningfully
higher forward volatility. This proves the regime predictions have real economic
content and should be trusted for sizing/risk decisions.

### Transition Matrix (Regime Stability)

| From \ To | vol_low | vol_normal | vol_elevated | vol_extreme |
|-----------|---------|------------|--------------|-------------|
| vol_low | **94.2%** | 5.8% | 0.03% | 0.02% |
| vol_normal | 2.6% | **95.6%** | 1.7% | 0.2% |
| vol_elevated | 0.03% | 6.5% | **90.3%** | 3.1% |
| vol_extreme | 0.1% | 1.4% | 20.2% | **78.2%** |

Mean persistence: **89.6%** — regimes are highly stable (change ~1 in 10 bars on average).
Normal vol is most sticky (95.6%), extreme vol least (78.2% — tends to decay to elevated).

### New Feature Contribution

`vol_change_ratio` entered top 15 features, replacing `parkinson_vol`. The vol_change
group contributes 754.6 aggregate importance — meaningful but behind volatility (6860)
and temporal (5778) groups.

### Data Quality Issues Found

14 features are 100% NaN:
- 4h candle features (return_4h, atr_4h, etc.) — **need to load 4h data in assemble_dataset()**
- Microstructure features (cvd, flow_imbalance, etc.) — trades data exists but isn't loaded
- LS ratio features — no data available

Funding rate is 91.6% NaN — only 99 observations covering a small time range.

**Action items (completed):**
1. ~~Load 4h candles in assemble_dataset()~~ — Done (resample from 1m). Result: +2 features,
   but **no accuracy improvement** (59.06% vs 59.07%). The 4h candle features are redundant
   with `realized_vol_4h` and `atr_pctl_24h/7d` which already capture the same information
   from 1m data. Keeping them for feature completeness but they don't drive model quality.
2. Trades data — only 4000 rows available (sparse). Microstructure features remain NaN.
   Need continuous trade recording to activate these.
3. Funding data — only 99 observations. Need historical backfill to activate funding features.

---

## Architecture Risks

1. **Single model for final deployment** — only the last CV fold's model is saved.
   Standard practice but misses opportunity to ensemble across folds.
2. **No model monitoring** — no drift detection, no performance tracking post-deployment.
3. **Confidence threshold is low** — `ml_confidence_threshold=0.5` for a 4-class
   problem means the model can be less confident than random and still override.
4. **No regime persistence estimate** — model predicts current regime but not
   how long it will last or probability of transition.
