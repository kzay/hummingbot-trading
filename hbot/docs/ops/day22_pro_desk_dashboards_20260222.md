# Day 22 - Pro Desk Dashboards v1 (Control Plane)

## Scope
- Add first-class control-plane observability for promotion readiness.
- Surface gate state and report freshness in Grafana.
- Add fail-closed alerting for stale/missing control-plane outputs.

## Implemented Artifacts
- Metrics exporter:
  - `services/control_plane_metrics_exporter.py`
- Compose service:
  - `compose/docker-compose.yml` (`control-plane-metrics-exporter`)
- Prometheus scrape target:
  - `monitoring/prometheus/prometheus.yml` (`job_name: control-plane-metrics`)
- Alert rules:
  - `monitoring/prometheus/alert_rules.yml` (`group: control_plane`)
- Grafana dashboard:
  - `monitoring/grafana/dashboards/control_plane_overview.json`

## Exposed Metrics (Core)
- `hbot_control_plane_report_present{report=*}`
- `hbot_control_plane_report_age_seconds{report=*}`
- `hbot_control_plane_report_fresh{report=*}`
- `hbot_control_plane_gate_status{gate=*}`
- `hbot_control_plane_finding_count{report=*}`

## New Alerts
- `ControlPlaneReportMissing` (critical)
- `ControlPlaneReportStale` (critical)
- `PromotionGateFailed` (critical)
- `StrictCycleFailed` (warning)
- `Day2GateNotGo` (warning)

## Validation
- Compose config renders with new service and scrape target.
- Python syntax checks pass for exporter.
- Promotion gate flow remains intact after monitoring additions.

## Operational Note
- This dashboard is intended to answer, on one screen:
  - Is promotion currently safe?
  - Are all critical control-plane reports fresh?
