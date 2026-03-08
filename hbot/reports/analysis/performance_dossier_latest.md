# Performance Dossier

- Generated: `2026-03-08T01:22:00.006703+00:00`
- Status: **WARNING**
- Data source: `csv`
- Days included: `2`
- Total net PnL: `-2.7310`
- Mean fee bps: `2.74`
- Maker ratio (weighted): `31.46%`
- Maker ratio (mean daily): `28.38%`
- Max p95 slippage: `2.73` bps
- Max drawdown: `0.12%`
- Soft-pause (state): `13.55%`
- Soft-pause (edge): `1.65%`
- Selective quote block: `0.00%`
- Selective quote reduced: `0.00%`
- Alpha no-trade: `36.26%`
- Alpha aggressive: `0.00%`
- Cancel-before-fill: `0.37%`
- Rolling expectancy/fill (89 rows): `-0.030685` (95% CI: `-0.042046` .. `-0.019324`)
- Rolling maker expectancy/fill: `-0.020581` (95% CI: `-0.030912` .. `-0.010251`)
- Rolling taker expectancy/fill: `-0.035323` (95% CI: `-0.051127` .. `-0.019519`)

## Expectancy Buckets
- Alpha policy: `{"maker_bias_buy": {"ci95_high_quote": -0.01588638704140153, "ci95_low_quote": -0.0370478774219086, "expectancy_per_fill_quote": -0.026467132231655064, "fills": 27.0}, "maker_bias_sell": {"ci95_high_quote": -0.015444125814582502, "ci95_low_quote": -0.029301871157257423, "expectancy_per_fill_quote": -0.022372998485919962, "fills": 18.0}, "maker_two_sided": {"ci95_high_quote": -0.0011797281168442753, "ci95_low_quote": -0.09943529170971267, "expectancy_per_fill_quote": -0.050307509913278474, "fills": 19.0}, "no_trade": {"ci95_high_quote": -0.016689678466407353, "ci95_low_quote": -0.03593426100428003, "expectancy_per_fill_quote": -0.026311969735343693, "fills": 25.0}}`
- Regime: `{"down": {"ci95_high_quote": -0.020917311322172952, "ci95_low_quote": -0.0556006452616699, "expectancy_per_fill_quote": -0.038258978291921424, "fills": 13.0}, "high_vol_shock": {"ci95_high_quote": -0.0001350272, "ci95_low_quote": -0.0001350272, "expectancy_per_fill_quote": -0.0001350272, "fills": 1.0}, "neutral_low_vol": {"ci95_high_quote": -0.017087597575299977, "ci95_low_quote": -0.04518845486798874, "expectancy_per_fill_quote": -0.03113802622164436, "fills": 69.0}, "up": {"ci95_high_quote": 0.014620095963412563, "ci95_low_quote": -0.04293440277964244, "expectancy_per_fill_quote": -0.014157153408114938, "fills": 6.0}}`

## Checks
- [FAIL] `net_pnl_non_negative` value=`-2.7309684747371294` threshold=`0.0`
- [PASS] `mean_fee_bps_within_0_to_12` value=`2.742939288036775` threshold=`[0.0, 12.0]`
- [FAIL] `maker_ratio_at_least_45pct` value=`0.3146067415730337` threshold=`0.45`
- [PASS] `slippage_p95_below_25bps` value=`2.732479905961875` threshold=`25.0`
- [PASS] `drawdown_below_2pct` value=`0.0012283157501984951` threshold=`0.02`
- [PASS] `soft_pause_state_ratio_below_30pct` value=`0.13553113553113552` threshold=`0.3`
- [FAIL] `reconciliation_not_critical` value=`11.0` threshold=`0.0`
- [PASS] `portfolio_risk_not_critical` value=`0.0` threshold=`0.0`
- [FAIL] `rolling_expectancy_ci95_upper_non_negative` value=`-0.01932440977307106` threshold=`0.0`

## Daily Breakdown
| day | fills | net_pnl | fee_bps | maker_ratio | slippage_p95_bps |
|---|---:|---:|---:|---:|---:|
| 2026-03-07 | 85 | -2.6814 | 3.49 | 31.76% | 2.73 |
| 2026-03-08 | 4 | -0.0495 | 2.00 | 25.00% | -0.29 |
