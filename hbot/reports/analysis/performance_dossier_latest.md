# Performance Dossier

- Generated: `2026-03-10T00:40:50.218494+00:00`
- Status: **WARNING**
- Data source: `csv`
- Days included: `4`
- Total net PnL: `-7.1304`
- Mean fee bps: `2.37`
- Maker ratio (weighted): `77.82%`
- Maker ratio (mean daily): `81.36%`
- Max p95 slippage: `4.16` bps
- Max drawdown: `0.30%`
- Soft-pause (state): `0.15%`
- Soft-pause (edge): `0.00%`
- Selective quote block: `0.00%`
- Selective quote reduced: `0.00%`
- Alpha no-trade: `1.64%`
- Alpha aggressive: `0.00%`
- Cancel-before-fill: `0.89%`
- Rolling expectancy/fill (284 rows): `-0.025107` (95% CI: `-0.035268` .. `-0.014947`)
- Rolling maker expectancy/fill: `-0.022393` (95% CI: `-0.034689` .. `-0.010097`)
- Rolling taker expectancy/fill: `-0.034628` (95% CI: `-0.049956` .. `-0.019300`)

## Expectancy Buckets
- Alpha policy: `{"maker_bias_buy": {"ci95_high_quote": -0.017359299956455472, "ci95_low_quote": -0.06348393595880433, "expectancy_per_fill_quote": -0.0404216179576299, "fills": 29.0}, "maker_bias_sell": {"ci95_high_quote": 0.008926393911940167, "ci95_low_quote": -0.17370783850531393, "expectancy_per_fill_quote": -0.08239072229668688, "fills": 21.0}, "maker_two_sided": {"ci95_high_quote": -0.007532439452791412, "ci95_low_quote": -0.026632183763972195, "expectancy_per_fill_quote": -0.017082311608381803, "fills": 209.0}, "no_trade": {"ci95_high_quote": -0.016689678466407353, "ci95_low_quote": -0.03593426100428003, "expectancy_per_fill_quote": -0.026311969735343693, "fills": 25.0}}`
- Regime: `{"down": {"ci95_high_quote": 0.001442648885120485, "ci95_low_quote": -0.05452523586884121, "expectancy_per_fill_quote": -0.026541293491860365, "fills": 71.0}, "high_vol_shock": {"ci95_high_quote": 0.004707941743412821, "ci95_low_quote": -0.043404772946625356, "expectancy_per_fill_quote": -0.019348415601606266, "fills": 32.0}, "neutral_low_vol": {"ci95_high_quote": -0.017058092781824227, "ci95_low_quote": -0.04168064698239271, "expectancy_per_fill_quote": -0.02936936988210847, "fills": 112.0}, "up": {"ci95_high_quote": 0.0008743335510719499, "ci95_low_quote": -0.0396419826689689, "expectancy_per_fill_quote": -0.019383824558948475, "fills": 69.0}}`

## Checks
- [FAIL] `net_pnl_non_negative` value=`-7.130434458537085` threshold=`0.0`
- [PASS] `mean_fee_bps_within_0_to_12` value=`2.371469644018388` threshold=`[0.0, 12.0]`
- [PASS] `maker_ratio_at_least_45pct` value=`0.778169014084507` threshold=`0.45`
- [PASS] `slippage_p95_below_25bps` value=`4.163225042650315` threshold=`25.0`
- [PASS] `drawdown_below_2pct` value=`0.0030448211251818927` threshold=`0.02`
- [PASS] `soft_pause_state_ratio_below_30pct` value=`0.001488095238095238` threshold=`0.3`
- [PASS] `reconciliation_not_critical` value=`0.0` threshold=`0.0`
- [PASS] `portfolio_risk_not_critical` value=`0.0` threshold=`0.0`
- [FAIL] `rolling_expectancy_ci95_upper_non_negative` value=`-0.01494677709010942` threshold=`0.0`

## Daily Breakdown
| day | fills | net_pnl | fee_bps | maker_ratio | slippage_p95_bps |
|---|---:|---:|---:|---:|---:|
| 2026-03-07 | 85 | -2.6814 | 3.49 | 31.76% | 2.73 |
| 2026-03-08 | 79 | -2.7311 | 2.00 | 93.67% | 3.91 |
| 2026-03-09 | 119 | -1.7069 | 2.00 | 100.00% | 4.16 |
| 2026-03-10 | 1 | -0.0111 | 2.00 | 100.00% | -0.70 |
