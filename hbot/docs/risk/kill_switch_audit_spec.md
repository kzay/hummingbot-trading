# Kill Switch Audit Spec v1

## Purpose
Provide immutable provenance for portfolio risk actions (`soft_pause`, `kill_switch`) triggered by Day 5 controls.

## Sources
- Service: `services/portfolio_risk_service/main.py`
- Streams (optional publish path):
  - `hb.execution_intent.v1`
  - `hb.audit.v1`
- File audit trail (always):
  - `reports/portfolio_risk/audit_<YYYYMMDD>.jsonl`

## Required Audit Fields
- `ts_utc`
- `status`
- `portfolio_action`
- `critical_count`
- `warning_count`
- `metrics`
  - `portfolio_daily_loss_pct`
  - `abs_net_exposure_quote`
  - `max_equity_share_pct`
  - `total_equity_quote`
- `findings[]`
  - `severity`
  - `check`
  - `message`
  - `details`
- `actions[]`
  - `bot`
  - `action`
  - `event_id`

## Integrity Rule
- Audit file is append-only JSONL and must never be edited in place.

## Operator Verification
1. Confirm `reports/portfolio_risk/latest.json` matches most recent audit line.
2. For each action, verify corresponding `event_id` exists in `actions[]`.
3. Confirm action scope only includes approved bots (`bot1`, `bot4` unless policy changed).
