# Evaluation Report: btc-volatility-regime-breakout-v1
**Generated**: 2026-03-26 18:51 UTC
**Run ID**: 2deed3af

## Candidate Summary
- **Hypothesis**: BTC-USDT exhibits distinct volatility regimes on 15m timeframes. During low-volatility  periods (ATR < 20th percentile of 100-bar lookback), breakouts above/below Bollinger  Bands signal regime shifts with strong directional persistence lasting 3-8 bars.  Entry on breakout confirmation with tight ATR-based stops captures early momentum  while limiting whipsaw losses during high-volatility periods.
- **Adapter**: momentum_scalper
- **Entry**: Enter long when price closes above upper Bollinger Band (20-period, 2 std)  AND current ATR(14) is below vol_filter_percentile of 100-bar ATR history  AND momentum burst exceeds burst_threshold * ATR. Enter short on lower  band breakout with same volatility filter. Require breakout confirmation  on bar close to avoid false signals.
- **Exit**: Exit after hold_bars periods OR when trailing stop triggered at  trail_atr * ATR(14) from peak favorable price. Hard stop at 2.5 * ATR  from entry to limit maximum loss per trade.
- **Parameters**: 4 tunable

## Backtest Metrics
| Metric | Value |
|--------|-------|
| Sharpe Ratio | 0.958 |
| Closed Trades | 1590 |
| Max Drawdown | 4.21% |
| Net P&L (realized) | 38.76 |
| Maker Ratio | 1.00 |

## Sweep Top-5
| Rank | Sharpe | Params |
|------|--------|--------|
| 1 | 0.958 | burst_threshold=1.5, hold_bars=3, trail_atr=1.2, vol_filter_percentile=15 |
| 2 | 0.958 | burst_threshold=1.5, hold_bars=3, trail_atr=0.8, vol_filter_percentile=25 |
| 3 | 0.958 | burst_threshold=1.5, hold_bars=3, trail_atr=1.2, vol_filter_percentile=25 |
| 4 | 0.958 | burst_threshold=1.5, hold_bars=3, trail_atr=1.2, vol_filter_percentile=20 |
| 5 | 0.958 | burst_threshold=1.5, hold_bars=3, trail_atr=0.8, vol_filter_percentile=20 |

## Walk-Forward OOS
| Window | Train | Test | IS Sharpe | OOS Sharpe |
|--------|-------|------|-----------|------------|
| 0 | 2025-01-01→2025-01-30 | 2025-01-31→2025-03-12 | -4.704 | 3.215 |
| 1 | 2025-01-01→2025-03-12 | 2025-03-13→2025-04-22 | -1.667 | -3.229 |
| 2 | 2025-01-01→2025-04-22 | 2025-04-23→2025-06-02 | -0.043 | 1.299 |
| 3 | 2025-01-01→2025-06-02 | 2025-06-03→2025-07-13 | 0.841 | -5.045 |
| 4 | 2025-01-01→2025-07-13 | 2025-07-14→2025-08-23 | 0.682 | 0.008 |
| 5 | 2025-01-01→2025-08-23 | 2025-08-24→2025-10-03 | 0.591 | -3.854 |
| 6 | 2025-01-01→2025-10-03 | 2025-10-04→2025-11-13 | -0.295 | -3.672 |
| 7 | 2025-01-01→2025-11-13 | 2025-11-14→2025-12-24 | 0.615 | -2.736 |
| 8 | 2025-01-01→2025-12-24 | 2025-12-25→2026-02-03 | 0.879 | 6.224 |
| 9 | 2025-01-01→2026-02-03 | 2026-02-04→2026-03-16 | 1.013 | 1.370 |

- **Mean IS Sharpe**: -0.209
- **Mean OOS Sharpe**: -0.642
- **OOS Degradation Ratio**: 3.073
- **DSR**: -4.089 (p=1.000)
- **Holm-Bonferroni Pass**: True
- **BH FDR Pass**: True

## Robustness Score
**Total: 0.335** → **REJECT**

| Component | Raw | Normalised | Weight | Contribution |
|-----------|-----|------------|--------|-------------|
| oos_sharpe | -0.642 | 0.000 | 0.25 | 0.000 |
| oos_degradation | 3.073 | 1.000 | 0.20 | 0.200 |
| param_stability | 0.899 | 0.899 | 0.15 | 0.135 |
| fee_stress | -17.071 | 0.000 | 0.15 | 0.000 |
| regime_stability | -1.450 | 0.000 | 0.15 | 0.000 |
| dsr_pass | -4.089 | 0.000 | 0.10 | 0.000 |

## Warnings
- ⚠ Mean OOS Sharpe -0.64 < absolute floor 0.5
- ⚠ DSR p-value 1.000 > 0.05 — observed Sharpe may be due to selection bias
- ⚠ Block bootstrap percentile 0.64 < 0.95 — strategy may not be significant
- ⚠ Fee margin of safety 0.00 < 0.20 — edge is fragile to fee changes
- ⚠ Regime 'neutral_low_vol' OOS Sharpe -1.45 deviates > 20% from overall OOS Sharpe -0.64
- ⚠ Regime 'high_vol_shock' OOS Sharpe -0.44 deviates > 20% from overall OOS Sharpe -0.64

## Recommendation
**REJECT**: Strategy does not meet minimum robustness thresholds.
