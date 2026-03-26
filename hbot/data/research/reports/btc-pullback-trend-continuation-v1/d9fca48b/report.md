# Evaluation Report: btc-pullback-trend-continuation-v1
**Generated**: 2026-03-26 03:30 UTC
**Run ID**: d9fca48b

## Candidate Summary
- **Hypothesis**: BTC-USDT shows reliable trend continuation after shallow pullbacks in strong trends. When price pulls back 1-2 ATR from trend highs but stays above the 50-period EMA, buying the pullback with tight stops yields positive Sharpe as the trend resumes. This exploits institutional re-entry behavior during healthy corrections.
- **Adapter**: pullback
- **Entry**: Enter long when price has pulled back pullback_depth_atr from recent highs but remains above trend_ema, AND the EMA slope indicates uptrend strength exceeding min_trend_strength. Only trade pullbacks in established uptrends.
- **Exit**: Exit on stop loss at entry - stop_atr_mult * ATR, or when price breaks below trend_ema on a closing basis, or after maximum hold period if no clear trend resumption occurs.
- **Parameters**: 4 tunable

## Backtest Metrics
| Metric | Value |
|--------|-------|
| Sharpe Ratio | -1.218 |
| Closed Trades | 1032 |
| Max Drawdown | 23.77% |
| Net P&L (realized) | -25.06 |
| Maker Ratio | 1.00 |

## Sweep Top-5
| Rank | Sharpe | Params |
|------|--------|--------|
| 1 | -1.218 | pullback_depth_atr=1.0, trend_ema=34, stop_atr_mult=1.2, min_trend_strength=0.06 |
| 2 | -1.218 | pullback_depth_atr=1.0, trend_ema=34, stop_atr_mult=1.8, min_trend_strength=0.06 |
| 3 | -1.218 | pullback_depth_atr=1.0, trend_ema=34, stop_atr_mult=1.2, min_trend_strength=0.04 |
| 4 | -1.218 | pullback_depth_atr=1.0, trend_ema=34, stop_atr_mult=1.2, min_trend_strength=0.02 |
| 5 | -1.218 | pullback_depth_atr=1.0, trend_ema=34, stop_atr_mult=1.8, min_trend_strength=0.04 |

## Walk-Forward OOS
| Window | Train | Test | IS Sharpe | OOS Sharpe |
|--------|-------|------|-----------|------------|
| 0 | 2025-01-01→2025-01-30 | 2025-01-31→2025-03-12 | 1.766 | 3.215 |
| 1 | 2025-01-01→2025-03-12 | 2025-03-13→2025-04-22 | -1.409 | -3.229 |
| 2 | 2025-01-01→2025-04-22 | 2025-04-23→2025-06-02 | -1.326 | 1.947 |
| 3 | 2025-01-01→2025-06-02 | 2025-06-03→2025-07-13 | -0.995 | -5.045 |
| 4 | 2025-01-01→2025-07-13 | 2025-07-14→2025-08-23 | 0.458 | 0.008 |
| 5 | 2025-01-01→2025-08-23 | 2025-08-24→2025-10-03 | -0.042 | -3.123 |
| 6 | 2025-01-01→2025-10-03 | 2025-10-04→2025-11-13 | 0.417 | -3.672 |
| 7 | 2025-01-01→2025-11-13 | 2025-11-14→2025-12-24 | -0.808 | -0.324 |
| 8 | 2025-01-01→2025-12-24 | 2025-12-25→2026-02-03 | -1.164 | 1.709 |
| 9 | 2025-01-01→2026-02-03 | 2026-02-04→2026-03-16 | -1.423 | 1.370 |

- **Mean IS Sharpe**: -0.453
- **Mean OOS Sharpe**: -0.715
- **OOS Degradation Ratio**: 1.579
- **DSR**: -4.162 (p=1.000)
- **Holm-Bonferroni Pass**: False
- **BH FDR Pass**: False

## Robustness Score
**Total: 0.326** → **REJECT**

| Component | Raw | Normalised | Weight | Contribution |
|-----------|-----|------------|--------|-------------|
| oos_sharpe | -0.715 | 0.000 | 0.25 | 0.000 |
| oos_degradation | 1.579 | 1.000 | 0.20 | 0.200 |
| param_stability | 0.843 | 0.843 | 0.15 | 0.126 |
| fee_stress | -19.682 | 0.000 | 0.15 | 0.000 |
| regime_stability | -2.023 | 0.000 | 0.15 | 0.000 |
| dsr_pass | -4.162 | 0.000 | 0.10 | 0.000 |

## Warnings
- ⚠ Mean OOS Sharpe -0.71 < absolute floor 0.5
- ⚠ DSR p-value 1.000 > 0.05 — observed Sharpe may be due to selection bias
- ⚠ No OOS window survives Holm-Bonferroni correction — all may be spurious
- ⚠ No OOS window survives BH FDR correction — high false discovery risk
- ⚠ Block bootstrap percentile 0.53 < 0.95 — strategy may not be significant
- ⚠ Fee margin of safety 0.00 < 0.20 — edge is fragile to fee changes
- ⚠ Parameter 'pullback_depth_atr' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'trend_ema' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'stop_atr_mult' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'min_trend_strength' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Regime 'neutral_low_vol' OOS Sharpe -2.02 deviates > 20% from overall OOS Sharpe -0.71
- ⚠ Regime 'high_vol_shock' OOS Sharpe -0.41 deviates > 20% from overall OOS Sharpe -0.71

## Recommendation
**REJECT**: Strategy does not meet minimum robustness thresholds.
