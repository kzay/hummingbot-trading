# Evaluation Report: btc-volatility-regime-momentum-v1
**Generated**: 2026-03-25 19:54 UTC
**Run ID**: 13b40a25

## Candidate Summary
- **Hypothesis**: BTC-USDT exhibits distinct momentum persistence patterns during different volatility regimes. During high volatility periods (ATR > 20-period MA), momentum bursts lasting 2-6 bars show continuation with 60%+ win rate. Strategy enters on initial momentum spike, holds for fixed duration with trailing stop, then exits. Higher volatility requires tighter trail stops to capture quick reversals.
- **Adapter**: momentum_scalper
- **Entry**: Enter long when current bar's range exceeds burst_threshold * ATR(14) AND ATR(14) > vol_filter_mult * SMA(ATR(14), 20) indicating high volatility regime. Enter short on same conditions but negative price movement. Only one position at a time.
- **Exit**: Exit after hold_bars completed bars OR when price trails back trail_atr * ATR(14) from the most favorable level reached. Force exit if volatility regime ends (ATR drops below vol_filter_mult threshold).
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
| 1 | -1.216 | burst_threshold=1.5, hold_bars=2, trail_atr=1.2, vol_filter_mult=1.6 |
| 2 | -1.216 | burst_threshold=1.5, hold_bars=2, trail_atr=1.2, vol_filter_mult=1.3 |
| 3 | -1.216 | burst_threshold=1.5, hold_bars=2, trail_atr=0.8, vol_filter_mult=1.3 |
| 4 | -1.216 | burst_threshold=1.5, hold_bars=2, trail_atr=1.2, vol_filter_mult=1.0 |
| 5 | -1.216 | burst_threshold=1.5, hold_bars=2, trail_atr=0.8, vol_filter_mult=1.0 |

## Walk-Forward OOS
| Window | Train | Test | IS Sharpe | OOS Sharpe |
|--------|-------|------|-----------|------------|
| 0 | 2025-01-01→2025-01-30 | 2025-01-31→2025-03-12 | 1.737 | 3.175 |
| 1 | 2025-01-01→2025-03-12 | 2025-03-13→2025-04-22 | -1.399 | -2.420 |
| 2 | 2025-01-01→2025-04-22 | 2025-04-23→2025-06-02 | -1.320 | 3.335 |
| 3 | 2025-01-01→2025-06-02 | 2025-06-03→2025-07-13 | -0.991 | -8.258 |
| 4 | 2025-01-01→2025-07-13 | 2025-07-14→2025-08-23 | 0.457 | 0.008 |
| 5 | 2025-01-01→2025-08-23 | 2025-08-24→2025-10-03 | -0.042 | -5.337 |
| 6 | 2025-01-01→2025-10-03 | 2025-10-04→2025-11-13 | 0.416 | -3.626 |
| 7 | 2025-01-01→2025-11-13 | 2025-11-14→2025-12-24 | -0.806 | 0.605 |
| 8 | 2025-01-01→2025-12-24 | 2025-12-25→2026-02-03 | -1.162 | 4.472 |
| 9 | 2025-01-01→2026-02-03 | 2026-02-04→2026-03-16 | -1.421 | 2.091 |

- **Mean IS Sharpe**: -0.453
- **Mean OOS Sharpe**: -0.596
- **OOS Degradation Ratio**: 1.314
- **DSR**: -4.043 (p=1.000)
- **Holm-Bonferroni Pass**: False
- **BH FDR Pass**: False

## Robustness Score
**Total: 0.334** → **REJECT**

| Component | Raw | Normalised | Weight | Contribution |
|-----------|-----|------------|--------|-------------|
| oos_sharpe | -0.596 | 0.000 | 0.25 | 0.000 |
| oos_degradation | 1.314 | 1.000 | 0.20 | 0.200 |
| param_stability | 0.896 | 0.896 | 0.15 | 0.134 |
| fee_stress | -18.006 | 0.000 | 0.15 | 0.000 |
| regime_stability | -1.333 | 0.000 | 0.15 | 0.000 |
| dsr_pass | -4.043 | 0.000 | 0.10 | 0.000 |

## Warnings
- ⚠ Mean OOS Sharpe -0.60 < absolute floor 0.5
- ⚠ DSR p-value 1.000 > 0.05 — observed Sharpe may be due to selection bias
- ⚠ No OOS window survives Holm-Bonferroni correction — all may be spurious
- ⚠ No OOS window survives BH FDR correction — high false discovery risk
- ⚠ Block bootstrap percentile 0.26 < 0.95 — strategy may not be significant
- ⚠ Fee margin of safety 0.00 < 0.20 — edge is fragile to fee changes
- ⚠ Parameter 'burst_threshold' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'hold_bars' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'trail_atr' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'vol_filter_mult' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Regime 'high_vol_shock' OOS Sharpe -0.34 deviates > 20% from overall OOS Sharpe -0.60
- ⚠ Regime 'neutral_low_vol' OOS Sharpe -1.33 deviates > 20% from overall OOS Sharpe -0.60

## Recommendation
**REJECT**: Strategy does not meet minimum robustness thresholds.
