# Day 35 - Market Data Freshness Gate (2026-02-22)

## Objective
- Add a promotion-check signal for market-data recency.
- Keep current strict blocking behavior focused on Day2 gate while Day2 is paused.

## Implemented
- New checker:
  - `scripts/release/check_market_data_freshness.py`
- Checker behavior:
  - finds latest `reports/event_store/events_*.jsonl`
  - validates file age against `--max-age-min`
  - validates presence of `hb.market_data.v1` rows
  - writes:
    - `reports/market_data/latest.json`
    - `reports/market_data/market_data_freshness_<timestamp>.json`

- Promotion gate integration:
  - `scripts/release/run_promotion_gates.py`
  - new gate: `market_data_freshness`
  - severity: `warning`
  - rationale: add observability signal without widening hard-block scope during Day2 pause.

## Validation
- checker evidence:
  - `reports/market_data/market_data_freshness_20260222T133935Z.json`
- promotion gate evidence:
  - `reports/promotion_gates/promotion_gates_20260222T134022Z.json`
  - global status remains `FAIL` only on `day2_event_store_gate`

## Outcome
- Market-data freshness now has a first-class gate signal and artifact trail.
- Hard blocking remains unchanged: only critical failures block promotion.
