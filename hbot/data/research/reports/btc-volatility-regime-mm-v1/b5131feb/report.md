# Evaluation Report: btc-volatility-regime-mm-v1
**Generated**: 2026-03-26 01:54 UTC
**Run ID**: b5131feb

## Candidate Summary
- **Hypothesis**: BTC-USDT exhibits distinct volatility regimes where low-volatility periods (BB width <1.5% of mid) favor tight market-making spreads, while high-volatility periods (BB width >3% of mid) require wider spreads and inventory bias toward the mean-reverting direction. The smc_mm adapter's regime detection captures these transitions and adjusts quoting behavior accordingly.
- **Adapter**: smc_mm
- **Entry**: Detect volatility regime using Bollinger Band width as percentage of mid price. In low-vol regime (BB width < regime_threshold), quote tight spreads at base_spread_bps. In high-vol regime (BB width > regime_threshold), widen spreads by 2x and bias quotes toward BB middle band direction. Use FVG detection over fvg_lookback bars to identify institutional flow direction and skew inventory accordingly.
- **Exit**: Maintain inventory target near zero in low-vol regimes for pure market-making. In high-vol regimes, allow temporary directional bias up to 30% of equity toward mean-reversion direction. Force inventory reduction when regime switches or when position exceeds 50% of equity via aggressive pricing.
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
| 1 | -1.216 | bb_period=15, regime_threshold=0.015, fvg_lookback=3, base_spread_bps=15 |
| 2 | -1.216 | bb_period=15, regime_threshold=0.015, fvg_lookback=5, base_spread_bps=15 |
| 3 | -1.216 | bb_period=15, regime_threshold=0.015, fvg_lookback=3, base_spread_bps=8 |
| 4 | -1.216 | bb_period=15, regime_threshold=0.015, fvg_lookback=5, base_spread_bps=25 |
| 5 | -1.216 | bb_period=15, regime_threshold=0.015, fvg_lookback=5, base_spread_bps=8 |

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
**Total: 0.324** → **REJECT**

| Component | Raw | Normalised | Weight | Contribution |
|-----------|-----|------------|--------|-------------|
| oos_sharpe | -0.596 | 0.000 | 0.25 | 0.000 |
| oos_degradation | 1.314 | 1.000 | 0.20 | 0.200 |
| param_stability | 0.829 | 0.829 | 0.15 | 0.124 |
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
- ⚠ Parameter 'bb_period' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'regime_threshold' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'fvg_lookback' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Parameter 'base_spread_bps' fails plateau test (optimum is a spike, not a plateau)
- ⚠ Regime 'high_vol_shock' OOS Sharpe -0.34 deviates > 20% from overall OOS Sharpe -0.60
- ⚠ Regime 'neutral_low_vol' OOS Sharpe -1.33 deviates > 20% from overall OOS Sharpe -0.60

## Recommendation
**REJECT**: Strategy does not meet minimum robustness thresholds.
