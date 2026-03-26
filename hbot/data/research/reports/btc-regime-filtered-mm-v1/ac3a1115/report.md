# Evaluation Report: btc-regime-filtered-mm-v1
**Generated**: 2026-03-25 21:31 UTC
**Run ID**: ac3a1115

## Candidate Summary
- **Hypothesis**: BTC-USDT perpetual exhibits predictable mean-reversion during low-volatility regimes but momentum continuation during high-volatility regimes. A market-making strategy that widens spreads during high ATR periods (>1.5x 20-period average) and tightens during low ATR periods (<0.8x average) captures both behaviors while avoiding adverse selection during breakouts.
- **Adapter**: atr_mm_v2
- **Entry**: Place quotes at mid +/- (vol_scalar * ATR(14)) distance. When current ATR exceeds regime_threshold * SMA(ATR, 20), widen spreads by 50% to avoid adverse fills during breakouts. Apply trend_bias_strength skew toward HTF EMA direction when price is more than 1 ATR away from htf_ema_period EMA.
- **Exit**: Reduce inventory via aggressive pricing when position exceeds 70% of max equity allocation. Hard stop at 2x ATR from average fill price. Flatten all positions if drawdown exceeds 15% to preserve capital during regime shifts.
- **Parameters**: 4 tunable

## Backtest Metrics
| Metric | Value |
|--------|-------|
| Sharpe Ratio | -1.467 |
| Closed Trades | 1054 |
| Max Drawdown | 14.23% |
| Net P&L (realized) | -42.40 |
| Maker Ratio | 1.00 |

## Sweep Top-5
| Rank | Sharpe | Params |
|------|--------|--------|
| 1 | -1.467 | vol_scalar=0.8, htf_ema_period=50, trend_bias_strength=0.1, regime_threshold=2.0 |
| 2 | -1.467 | vol_scalar=0.8, htf_ema_period=50, trend_bias_strength=0.3, regime_threshold=2.0 |
| 3 | -1.467 | vol_scalar=0.8, htf_ema_period=50, trend_bias_strength=0.1, regime_threshold=1.5 |
| 4 | -1.467 | vol_scalar=0.8, htf_ema_period=50, trend_bias_strength=0.3, regime_threshold=1.2 |
| 5 | -1.467 | vol_scalar=0.8, htf_ema_period=50, trend_bias_strength=0.1, regime_threshold=1.2 |

## Walk-Forward OOS
| Window | Train | Test | IS Sharpe | OOS Sharpe |
|--------|-------|------|-----------|------------|
| 0 | 2025-01-01→2025-01-30 | 2025-01-31→2025-03-12 | 2.951 | -2.136 |
| 1 | 2025-01-01→2025-03-12 | 2025-03-13→2025-04-22 | -1.265 | -1.894 |
| 2 | 2025-01-01→2025-04-22 | 2025-04-23→2025-06-02 | -1.818 | 0.980 |
| 3 | 2025-01-01→2025-06-02 | 2025-06-03→2025-07-13 | -2.419 | 3.891 |
| 4 | 2025-01-01→2025-07-13 | 2025-07-14→2025-08-23 | -2.698 | 0.387 |
| 5 | 2025-01-01→2025-08-23 | 2025-08-24→2025-10-03 | -2.132 | -4.014 |
| 6 | 2025-01-01→2025-10-03 | 2025-10-04→2025-11-13 | -2.031 | -0.865 |
| 7 | 2025-01-01→2025-11-13 | 2025-11-14→2025-12-24 | -1.410 | 0.376 |
| 8 | 2025-01-01→2025-12-24 | 2025-12-25→2026-02-03 | -1.478 | 6.310 |
| 9 | 2025-01-01→2026-02-03 | 2026-02-04→2026-03-16 | -1.624 | 2.445 |

- **Mean IS Sharpe**: -1.392
- **Mean OOS Sharpe**: 0.548
- **OOS Degradation Ratio**: -0.394
- **DSR**: -2.899 (p=1.000)
- **Holm-Bonferroni Pass**: True
- **BH FDR Pass**: True

## Robustness Score
**Total: 0.167** → **REJECT**

| Component | Raw | Normalised | Weight | Contribution |
|-----------|-----|------------|--------|-------------|
| oos_sharpe | 0.548 | 0.183 | 0.25 | 0.046 |
| oos_degradation | -0.394 | 0.000 | 0.20 | 0.000 |
| param_stability | 0.808 | 0.808 | 0.15 | 0.121 |
| fee_stress | -15.881 | 0.000 | 0.15 | 0.000 |
| regime_stability | -0.623 | 0.000 | 0.15 | 0.000 |
| dsr_pass | -2.899 | 0.000 | 0.10 | 0.000 |

## Warnings
- ⚠ OOS degradation ratio -0.39 < threshold 0.70 (strategy_type=mm)
- ⚠ Parameter 'trend_bias_strength' CV=0.53 > 0.5 (unstable)
- ⚠ DSR p-value 1.000 > 0.05 — observed Sharpe may be due to selection bias
- ⚠ Block bootstrap percentile 0.63 < 0.95 — strategy may not be significant
- ⚠ Fee margin of safety 0.07 < 0.20 — edge is fragile to fee changes
- ⚠ Regime 'neutral_low_vol' OOS Sharpe -0.62 deviates > 20% from overall OOS Sharpe 0.55

## Recommendation
**REJECT**: Strategy does not meet minimum robustness thresholds.
