# Soak Monitor Runbook

## Purpose
Track readiness during the Day 7 soak window using one aggregated snapshot that combines:
- Day 2 gate status
- Reconciliation status
- Parity status
- Portfolio risk status
- Strict promotion cycle status

## Service
- Script: `scripts/release/soak_monitor.py`
- Compose service: `soak-monitor` (profile `external`)

## Outputs
- `reports/soak/latest.json`
- `reports/soak/soak_snapshot_<timestamp>.json`

## Status Semantics
- `status=ready`: no blockers.
- `status=hold`: one or more blockers present.

## Common Blockers
- `day2_event_store_gate`
- `strict_cycle_not_pass`
- `parity_not_pass` (usually stale/failing parity report)
- `reconciliation_not_healthy`
- `portfolio_risk_not_healthy`
- `stale_reports`

## Commands
- One-shot snapshot:
  - `python scripts/release/soak_monitor.py --once`
- Continuous local watch:
  - `python scripts/release/soak_monitor.py --interval-sec 300 --freshness-max-min 30`
- Compose runtime:
  - `docker compose --env-file ../env/.env --profile external up -d soak-monitor`
- Daily report watcher (optional):
  - `python scripts/release/watch_daily_ops_report.py --interval-sec 900`
  - compose service: `daily-ops-reporter`
  - output: `docs/ops/daily_ops_report_<YYYYMMDD>.md`

## Operator Use
1. Check `reports/soak/latest.json`.
2. Review `blockers`.
3. Use per-component `path` fields in the snapshot to drill down quickly.
