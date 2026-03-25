# Ops Observability Spec

## Context

The March 2026 ops loop INITIAL_AUDIT identified gaps in alert coverage, report hygiene, and incident runbook completeness. While 44 alert rules exist and cover the trading runtime well, infrastructure-level monitoring (Prometheus scrape health, Postgres availability, metrics exporter failures) has no dedicated alerting. Report directories accumulate thousands of files unbounded. Two critical failure scenarios lack incident playbooks.

## ADDED Requirements

### Requirement: Infrastructure health alerts exist for critical dependencies

The `alert_rules.yml` SHALL include:
- `PrometheusTargetDown`: fires when `up == 0` for any scrape target, severity warning, `for: 5m`
- `PostgresDown`: fires on absence of postgres container metrics from cAdvisor, severity critical, `for: 2m`
- `MetricsExporterScrapeFailed`: fires when scrape of bot_metrics_exporter or control_plane_metrics_exporter produces zero `scrape_duration_seconds`, severity warning, `for: 5m`

**Verification**: All three alerts appear in Prometheus `/alerts` UI after config reload.

### Requirement: Report directories have bounded retention

Report directories SHALL be pruned on a schedule (via ops_scheduler or standalone script):
- `reports/parity/`: retain last 7 days
- `reports/reconciliation/`: retain last 14 days
- `reports/verification/`: delete `*.tmp` files, retain last 14 days

**Verification**: After first run, `reports/parity/` contains < 2000 files. No `.tmp` files in `reports/verification/`.

### Requirement: Incident playbooks cover Postgres and metrics exporter failures

`hbot/docs/ops/incident_playbooks/` SHALL include:
- `11_postgres_outage.md` with symptoms, diagnosis commands, recovery steps, and verification criteria
- `12_metrics_exporter_failure.md` with the same structure

**Verification**: Files exist and follow the format of existing playbooks 01–10.

## MODIFIED Requirements

### Requirement: BotDailyPnlDrawdown alert uses normalized threshold

The `BotDailyPnlDrawdown` and `RealizedPnlNegative` alert rules SHALL use a threshold expressed as a percentage of account equity (via recording rule or label) rather than hardcoded absolute quote values (-50, -20).

**Verification**: Alert expr references a recording rule or metric that normalizes against equity. Old hardcoded values are removed.

### Requirement: promotion_gates latest report stays fresh

The `reports/promotion_gates/latest.json` file SHALL be refreshed by a scheduled strict-cycle run at least weekly. The ops_scheduler or equivalent automation SHALL trigger this.

**Verification**: File timestamp is less than 7 days old at any weekly review.

## Metrics to Track Next Cycle

| Metric | Baseline | Target |
|--------|----------|--------|
| Report files in `reports/parity/` | 11,618 | < 2,000 |
| Report files in `reports/reconciliation/` | thousands | < 1,000 |
| `.tmp` files in `reports/verification/` | present | 0 |
| Infrastructure alert rules count | 0 | 3 |
| Incident playbooks count | 10 | 12 |
| `promotion_gates/latest.json` staleness | 17 days | < 7 days |
