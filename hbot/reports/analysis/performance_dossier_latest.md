# Performance Dossier

- Generated: `2026-03-22T22:54:29.495034+00:00`
- Status: **WARNING**
- Data source: `csv`
- Days included: `6`
- Total net PnL: `-5.7665`
- Mean fee bps: `4.20`
- Maker ratio (weighted): `14.86%`
- Maker ratio (mean daily): `51.11%`
- Max p95 slippage: `7.00` bps
- Max drawdown: `0.23%`
- Soft-pause (state): `96.19%`
- Soft-pause (edge): `0.21%`
- Selective quote block: `0.00%`
- Selective quote reduced: `0.00%`
- Alpha no-trade: `3.83%`
- Alpha aggressive: `0.00%`
- Cancel-before-fill: `0.00%`
- Rolling expectancy/fill (74 rows): `-0.077925` (95% CI: `-0.132798` .. `-0.023053`)
- Rolling maker expectancy/fill: `-0.000211` (95% CI: `-0.041144` .. `0.040722`)
- Rolling taker expectancy/fill: `-0.091495` (95% CI: `-0.155058` .. `-0.027931`)

## Expectancy Buckets
- Alpha policy: `{"maker_bias_buy": {"ci95_high_quote": -0.02872598803194321, "ci95_low_quote": -0.0741282510839614, "expectancy_per_fill_quote": -0.0514271195579523, "fills": 36.0}, "maker_bias_sell": {"ci95_high_quote": -0.0015361166064748188, "ci95_low_quote": -0.2996390508392749, "expectancy_per_fill_quote": -0.15058758372287487, "fills": 25.0}, "maker_two_sided": {"ci95_high_quote": 0.2071875990733333, "ci95_low_quote": -0.14777038228104286, "expectancy_per_fill_quote": 0.029708608396145225, "fills": 7.0}, "no_trade": {"ci95_high_quote": -0.02317436545792989, "ci95_low_quote": -0.09628143610874074, "expectancy_per_fill_quote": -0.059727900783335314, "fills": 6.0}}`
- Regime: `{"down": {"ci95_high_quote": 0.11046399686066488, "ci95_low_quote": -0.30688441626890584, "expectancy_per_fill_quote": -0.09821020970412048, "fills": 19.0}, "high_vol_shock": {"ci95_high_quote": 0.03240000236937203, "ci95_low_quote": -0.1773678547140266, "expectancy_per_fill_quote": -0.0724839261723273, "fills": 8.0}, "neutral_low_vol": {"ci95_high_quote": -0.05421683257649998, "ci95_low_quote": -0.1023138658286005, "expectancy_per_fill_quote": -0.07826534920255024, "fills": 32.0}, "up": {"ci95_high_quote": -0.03044519375309579, "ci95_low_quote": -0.07837033622645552, "expectancy_per_fill_quote": -0.054407764989775655, "fills": 15.0}}`

## Checks
- [FAIL] `net_pnl_non_negative` value=`-5.766473043085151` threshold=`0.0`
- [PASS] `mean_fee_bps_within_0_to_12` value=`4.196504913319862` threshold=`[0.0, 12.0]`
- [FAIL] `maker_ratio_at_least_45pct` value=`0.14864864864864866` threshold=`0.45`
- [PASS] `slippage_p95_below_25bps` value=`7.0025883431993154` threshold=`25.0`
- [PASS] `drawdown_below_2pct` value=`0.0023463535273015044` threshold=`0.02`
- [FAIL] `soft_pause_state_ratio_below_30pct` value=`0.9619200858138911` threshold=`0.3`
- [PASS] `reconciliation_not_critical` value=`0.0` threshold=`0.0`
- [PASS] `portfolio_risk_not_critical` value=`0.0` threshold=`0.0`
- [FAIL] `rolling_expectancy_ci95_upper_non_negative` value=`-0.023052573354775292` threshold=`0.0`

## Daily Breakdown
| day | fills | net_pnl | fee_bps | maker_ratio | slippage_p95_bps |
|---|---:|---:|---:|---:|---:|
| 2026-03-17 | 2 | 0.1516 | 2.00 | 100.00% | 0.20 |
| 2026-03-18 | 3 | 0.0571 | 2.00 | 100.00% | 3.22 |
| 2026-03-19 | 3 | -1.9389 | 4.19 | 66.67% | 2.65 |
| 2026-03-20 | 10 | -0.1087 | 4.99 | 40.00% | 7.00 |
| 2026-03-21 | 52 | -4.6204 | 6.00 | 0.00% | 3.58 |
| 2026-03-22 | 4 | 0.6928 | 6.00 | 0.00% | 4.52 |
