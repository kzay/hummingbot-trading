# Bitget Live Micro-Cap Run - 2026-02-22

## Scope
Day 15 execution package for Bitget live micro-cap rollout with explicit no-trade safety validation and rollback path.

## Planned Capital Envelope
- Venue: `bitget_perpetual`
- Pair: `BTC-USDT`
- Bot: `bot1`
- Controller profile:
  - live micro-cap: `epp_v2_4_bot1_bitget_live_microcap.yml`
  - live no-trade: `epp_v2_4_bot1_bitget_live_notrade.yml`
- Envelope intent:
  - micro-cap notional sizing (`total_amount_quote: 5`)
  - conservative edge/spread settings
  - strict turnover cap bias

## Implemented Artifacts
- Controller configs:
  - `data/bot1/conf/controllers/epp_v2_4_bot1_bitget_live_microcap.yml`
  - `data/bot1/conf/controllers/epp_v2_4_bot1_bitget_live_notrade.yml`
- Script configs:
  - `data/bot1/conf/scripts/v2_epp_v2_4_bot1_bitget_live_microcap.yml`
  - `data/bot1/conf/scripts/v2_epp_v2_4_bot1_bitget_live_notrade.yml`
- No-trade validator:
  - `scripts/release/validate_notrade_window.py`

## Incident Taxonomy (Bitget-Specific)
- `bitget_disconnect`
- `bitget_order_reject`
- `bitget_ack_timeout`
- `bitget_position_mode_mismatch`
- `bitget_funding_or_fee_drift`

## Validation Performed (This Phase)
- No-trade validator executed as tooling smoke check on a zero-order Bitget paper evidence window.
- Evidence:
  - `reports/notrade_validation/notrade_validation_20260222T012911Z.json`
  - `reports/notrade_validation/latest.json`

## Current Phase Outcome
- **Status: PARTIAL (pre-live package complete).**
- Ready to run live micro-cap window once operator confirms live Bitget session window and accepts runtime risk envelope.
- Live outcome evidence (required to close Day 15) is pending:
  - controlled live run artifact(s)
  - no-trade live proof (`fills_count_today` non-increasing and `orders_active=0` during no-trade scenario)
  - incident log entries if connector/runtime issues appear

## Next Operator Step
1. Run live micro-cap scenario in bounded window.
2. Run live no-trade scenario and validate with `validate_notrade_window.py`.
3. Append outcomes/incidents and upgrade status from PARTIAL to COMPLETED.
