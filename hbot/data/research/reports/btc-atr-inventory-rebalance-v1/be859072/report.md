# Evaluation Report: btc-atr-inventory-rebalance-v1
**Generated**: 2026-03-26 19:40 UTC
**Run ID**: be859072

## Candidate Summary
- **Hypothesis**: BTC-USDT perpetual exhibits predictable mean-reversion patterns around fair value after volatility spikes. Market-making with ATR-based spread adjustment and aggressive inventory rebalancing during low-volatility periods captures spread while minimizing adverse selection during trending moves.
- **Adapter**: atr_mm
- **Entry**: Place bid/ask quotes at mid price +/- (spread_mult * ATR(atr_period) * vol_scalar). Increase spread_mult by 50% when current bar ATR exceeds 1.5x rolling average to avoid adverse fills during volatility spikes.
- **Exit**: Aggressively rebalance inventory when position exceeds inv_target of equity by tightening spread on heavy side. Force flatten if position reaches 90% of max allowed exposure.
- **Parameters**: 4 tunable

## Backtest Metrics
| Metric | Value |
|--------|-------|
| Sharpe Ratio | -0.516 |
| Closed Trades | 256 |
| Max Drawdown | 5.70% |
| Net P&L (realized) | -10.62 |
| Maker Ratio | 1.00 |

## Sweep Top-5
| Rank | Sharpe | Params |
|------|--------|--------|
| 1 | 0.943 | atr_period=20, spread_mult=1.2, inv_target=0.2, vol_scalar=0.8 |
| 2 | 0.943 | atr_period=20, spread_mult=1.2, inv_target=0.2, vol_scalar=1.2 |
| 3 | 0.943 | atr_period=20, spread_mult=1.2, inv_target=0.2, vol_scalar=1.8 |
| 4 | 0.943 | atr_period=20, spread_mult=1.2, inv_target=0.5, vol_scalar=0.8 |
| 5 | 0.943 | atr_period=20, spread_mult=1.2, inv_target=0.5, vol_scalar=1.2 |

## Walk-Forward OOS
| Window | Train | Test | IS Sharpe | OOS Sharpe |
|--------|-------|------|-----------|------------|
| 0 | 2025-01-01→2025-01-30 | 2025-01-31→2025-03-12 | 2.372 | -1.934 |
| 1 | 2025-01-01→2025-03-12 | 2025-03-13→2025-04-22 | 1.501 | -2.811 |
| 2 | 2025-01-01→2025-04-22 | 2025-04-23→2025-06-02 | 1.185 | 2.456 |
| 3 | 2025-01-01→2025-06-02 | 2025-06-03→2025-07-13 | 1.469 | -4.485 |
| 4 | 2025-01-01→2025-07-13 | 2025-07-14→2025-08-23 | 1.996 | 0.968 |
| 5 | 2025-01-01→2025-08-23 | 2025-08-24→2025-10-03 | 1.275 | -4.357 |
| 6 | 2025-01-01→2025-10-03 | 2025-10-04→2025-11-13 | 1.375 | -4.713 |
| 7 | 2025-01-01→2025-11-13 | 2025-11-14→2025-12-24 | 0.565 | -5.757 |
| 8 | 2025-01-01→2025-12-24 | 2025-12-25→2026-02-03 | 0.647 | 2.930 |
| 9 | 2025-01-01→2026-02-03 | 2026-02-04→2026-03-16 | 0.998 | 1.501 |

- **Mean IS Sharpe**: 1.338
- **Mean OOS Sharpe**: -1.620
- **OOS Degradation Ratio**: -1.211
- **DSR**: -5.067 (p=1.000)
- **Holm-Bonferroni Pass**: False
- **BH FDR Pass**: False

## Robustness Score
**Total: 0.119** → **REJECT**

| Component | Raw | Normalised | Weight | Contribution |
|-----------|-----|------------|--------|-------------|
| oos_sharpe | -1.620 | 0.000 | 0.25 | 0.000 |
| oos_degradation | -1.211 | 0.000 | 0.20 | 0.000 |
| param_stability | 0.793 | 0.793 | 0.15 | 0.119 |
| fee_stress | -18.206 | 0.000 | 0.15 | 0.000 |
| regime_stability | -2.171 | 0.000 | 0.15 | 0.000 |
| dsr_pass | -5.067 | 0.000 | 0.10 | 0.000 |

## Warnings
- ⚠ OOS degradation ratio -1.21 < threshold 0.70 (strategy_type=mm)
- ⚠ Mean OOS Sharpe -1.62 < absolute floor 0.5
- ⚠ DSR p-value 1.000 > 0.05 — observed Sharpe may be due to selection bias
- ⚠ No OOS window survives Holm-Bonferroni correction — all may be spurious
- ⚠ No OOS window survives BH FDR correction — high false discovery risk
- ⚠ Block bootstrap percentile 0.21 < 0.95 — strategy may not be significant
- ⚠ Fee margin of safety 0.00 < 0.20 — edge is fragile to fee changes
- ⚠ Regime 'neutral_low_vol' OOS Sharpe -2.17 deviates > 20% from overall OOS Sharpe -1.62

## Recommendation
**REJECT**: Strategy does not meet minimum robustness thresholds.
