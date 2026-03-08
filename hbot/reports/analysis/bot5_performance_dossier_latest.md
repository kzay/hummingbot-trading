# Performance Dossier

- Generated: `2026-03-07T15:28:14.017355+00:00`
- Status: **WARNING**
- Data source: `csv`
- Days included: `4`
- Total net PnL: `3.1945`
- Mean fee bps: `1.00`
- Maker ratio (weighted): `85.99%`
- Maker ratio (mean daily): `96.39%`
- Max p95 slippage: `161.00` bps
- Max drawdown: `0.38%`
- Soft-pause (state): `45.14%`
- Soft-pause (edge): `0.00%`
- Selective quote block: `0.00%`
- Selective quote reduced: `0.00%`
- Alpha no-trade: `0.00%`
- Alpha aggressive: `0.00%`
- Cancel-before-fill: `0.00%`
- Rolling expectancy/fill (300 rows): `0.002842` (95% CI: `-0.000451` .. `0.006135`)
- Rolling maker expectancy/fill: `0.005394` (95% CI: `0.002487` .. `0.008300`)
- Rolling taker expectancy/fill: `-0.007222` (95% CI: `-0.010581` .. `-0.003864`)

## Expectancy Buckets
- Alpha policy: `{"unknown": {"ci95_high_quote": 0.00291875295941796, "ci95_low_quote": 0.0012246109250127408, "expectancy_per_fill_quote": 0.0020716819422153506, "fills": 1542.0}}`
- Regime: `{"unknown": {"ci95_high_quote": 0.00291875295941796, "ci95_low_quote": 0.0012246109250127408, "expectancy_per_fill_quote": 0.0020716819422153506, "fills": 1542.0}}`

## Checks
- [PASS] `net_pnl_non_negative` value=`3.194533554896069` threshold=`0.0`
- [PASS] `mean_fee_bps_within_0_to_12` value=`1.0021536174643102` threshold=`[0.0, 12.0]`
- [PASS] `maker_ratio_at_least_45pct` value=`0.8599221789883269` threshold=`0.45`
- [FAIL] `slippage_p95_below_25bps` value=`160.99821977001466` threshold=`25.0`
- [PASS] `drawdown_below_2pct` value=`0.0038426098623071656` threshold=`0.02`
- [FAIL] `soft_pause_state_ratio_below_30pct` value=`0.45136186770428016` threshold=`0.3`
- [FAIL] `reconciliation_not_critical` value=`2.0` threshold=`0.0`
- [PASS] `portfolio_risk_not_critical` value=`0.0` threshold=`0.0`
- [PASS] `rolling_expectancy_ci95_upper_non_negative` value=`0.006135484931061164` threshold=`0.0`

## Daily Breakdown
| day | fills | net_pnl | fee_bps | maker_ratio | slippage_p95_bps |
|---|---:|---:|---:|---:|---:|
| 2026-03-03 | 1497 | 2.5469 | 0.01 | 85.57% | 161.00 |
| 2026-03-04 | 12 | 0.8154 | 0.00 | 100.00% | -196.25 |
| 2026-03-06 | 2 | 0.2002 | 2.00 | 100.00% | -5.76 |
| 2026-03-07 | 31 | -0.3679 | 2.00 | 100.00% | 8.99 |
