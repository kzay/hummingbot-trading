# Evaluation Report: btc-vol-cluster-mm-v2
**Generated**: 2026-03-26 04:02 UTC
**Run ID**: eafc3cc9

## Candidate Summary
- **Hypothesis**: BTC-USDT exhibits volatility clustering where high-vol periods are followed by continued high volatility, creating predictable bid-ask expansion opportunities. During vol expansion phases (current ATR > 1.5x historical average), wider spreads capture premium while inventory limits prevent adverse selection. The strategy profits from volatility mean-reversion within the clustering regime.
- **Adapter**: atr_mm_v2
- **Entry**: Place quotes at mid +/- vol_scalar * ATR when current ATR exceeds 1.5x the htf_ema-period average ATR, indicating vol expansion regime. Apply trend_bias skew to quote placement based on htf_ema slope direction.
- **Exit**: Reduce inventory aggressively when position exceeds target via asymmetric pricing. Exit all positions when ATR drops below 0.8x historical average, signaling vol regime change.
- **Parameters**: 4 tunable

## Backtest Metrics
| Metric | Value |
|--------|-------|
| Sharpe Ratio | -1.216 |
| Closed Trades | 1032 |
| Max Drawdown | 23.77% |
| Net P&L (realized) | -25.06 |
| Maker Ratio | 1.00 |

## Sweep Top-5
| Rank | Sharpe | Params |
|------|--------|--------|
| 1 | -0.479 | vol_scalar=1.2, htf_ema=50, trend_bias=0.0, atr_period=20 |
| 2 | -0.479 | vol_scalar=1.2, htf_ema=50, trend_bias=0.3, atr_period=20 |
| 3 | -0.479 | vol_scalar=1.2, htf_ema=50, trend_bias=0.6, atr_period=20 |
| 4 | -0.479 | vol_scalar=1.2, htf_ema=100, trend_bias=0.3, atr_period=20 |
| 5 | -0.479 | vol_scalar=1.2, htf_ema=100, trend_bias=0.0, atr_period=20 |

## Walk-Forward OOS
| Window | Train | Test | IS Sharpe | OOS Sharpe |
|--------|-------|------|-----------|------------|
| 0 | 2025-01-01→2025-01-30 | 2025-01-31→2025-03-12 | 3.826 | 2.918 |
| 1 | 2025-01-01→2025-03-12 | 2025-03-13→2025-04-22 | -1.143 | -3.118 |
| 2 | 2025-01-01→2025-04-22 | 2025-04-23→2025-06-02 | -0.293 | 3.335 |
| 3 | 2025-01-01→2025-06-02 | 2025-06-03→2025-07-13 | 0.436 | -8.258 |
| 4 | 2025-01-01→2025-07-13 | 2025-07-14→2025-08-23 | 1.133 | 0.008 |
| 5 | 2025-01-01→2025-08-23 | 2025-08-24→2025-10-03 | 0.776 | -5.337 |
| 6 | 2025-01-01→2025-10-03 | 2025-10-04→2025-11-13 | 0.759 | -3.489 |
| 7 | 2025-01-01→2025-11-13 | 2025-11-14→2025-12-24 | 0.013 | 0.054 |
| 8 | 2025-01-01→2025-12-24 | 2025-12-25→2026-02-03 | -0.282 | 4.472 |
| 9 | 2025-01-01→2026-02-03 | 2026-02-04→2026-03-16 | -0.440 | 2.018 |

- **Mean IS Sharpe**: 0.479
- **Mean OOS Sharpe**: -0.740
- **OOS Degradation Ratio**: -1.546
- **DSR**: -4.187 (p=1.000)
- **Holm-Bonferroni Pass**: False
- **BH FDR Pass**: False

## Robustness Score
**Total: 0.125** → **REJECT**

| Component | Raw | Normalised | Weight | Contribution |
|-----------|-----|------------|--------|-------------|
| oos_sharpe | -0.740 | 0.000 | 0.25 | 0.000 |
| oos_degradation | -1.546 | 0.000 | 0.20 | 0.000 |
| param_stability | 0.833 | 0.833 | 0.15 | 0.125 |
| fee_stress | -18.151 | 0.000 | 0.15 | 0.000 |
| regime_stability | -1.367 | 0.000 | 0.15 | 0.000 |
| dsr_pass | -4.187 | 0.000 | 0.10 | 0.000 |

## Warnings
- ⚠ OOS degradation ratio -1.55 < threshold 0.70 (strategy_type=mm)
- ⚠ Mean OOS Sharpe -0.74 < absolute floor 0.5
- ⚠ Parameter 'trend_bias' CV=0.67 > 0.5 (unstable)
- ⚠ DSR p-value 1.000 > 0.05 — observed Sharpe may be due to selection bias
- ⚠ No OOS window survives Holm-Bonferroni correction — all may be spurious
- ⚠ No OOS window survives BH FDR correction — high false discovery risk
- ⚠ Block bootstrap percentile 0.32 < 0.95 — strategy may not be significant
- ⚠ Fee margin of safety 0.00 < 0.20 — edge is fragile to fee changes
- ⚠ Parameter 'vol_scalar' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'htf_ema' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'trend_bias' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'atr_period' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Regime 'high_vol_shock' OOS Sharpe -0.53 deviates > 20% from overall OOS Sharpe -0.74
- ⚠ Regime 'neutral_low_vol' OOS Sharpe -1.37 deviates > 20% from overall OOS Sharpe -0.74

## Recommendation
**REJECT**: Strategy does not meet minimum robustness thresholds.
