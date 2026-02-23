# Parity Metrics Spec v1 (Day 4)

## Purpose
Define pass/fail metrics for shadow execution parity between expected execution behavior and realized outcomes.

## Service and Artifacts
- Service: `services/shadow_execution/main.py`
- Thresholds: `config/parity_thresholds.json`
- Reports:
  - `reports/parity/latest.json`
  - `reports/parity/YYYYMMDD/parity_<timestamp>.json`

## Metric Definitions

1. `fill_ratio_delta`
- Realized: `order_filled_count / actionable_execution_intent_count`
- Expected: `expected_fill_ratio`
- Delta: `realized - expected`
- Pass rule: `abs(delta) <= max_fill_ratio_delta`
- Note: if no actionable intents exist, mark as `insufficient_data` and neutral-pass.

2. `slippage_delta_bps`
- Realized: average absolute bps between `order_filled.fill_price` and latest prior `market_snapshot.mid_price`.
- Expected: `expected_slippage_bps`
- Delta: `realized - expected`
- Pass rule: `abs(delta) <= max_slippage_delta_bps`
- Note: if no fills or no matching market snapshots exist, mark as `insufficient_data` and neutral-pass.

3. `reject_rate_delta`
- Realized: `order_failed_count / (order_failed_count + order_filled_count)`.
- Expected: `expected_reject_rate`
- Delta: `realized - expected`
- Pass rule: `abs(delta) <= max_reject_rate_delta`
- Note: if both fills and failures are zero but actionable intents exist, realized reject rate is treated as `1.0`.

4. `realized_pnl_delta_quote`
- Realized: `last_equity_quote - first_equity_quote` from bot `minute.csv`.
- Expected: `expected_realized_pnl_quote`
- Delta: `realized - expected`
- Pass rule: `abs(delta) <= max_realized_pnl_delta_quote`
- Note: this is a day-window proxy, not a trade-by-trade attribution model.

## Policy Scope
- Day 4 default policy is explicit allow-list:
  - `bot1`: enabled
  - `bot4`: enabled
  - all others disabled unless explicitly enabled

## Report Status
- `status=pass`: all enabled bots pass all available metrics.
- `status=fail`: one or more enabled bots fail at least one metric.

## Operational Notes
- This is an MVP parity layer intended for controlled rollouts.
- Threshold values should be tightened as event richness improves (`order_created`/`order_filled` density, richer fills metadata).
