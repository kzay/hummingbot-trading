# Day 33 - Control-Plane Coordination Metrics + Wiring (2026-02-22)

## Objective
- Verify control-plane exporter wiring against the latest policy/gate set.
- Add missing coordination freshness and policy visibility metrics.
- Surface coordination health and policy-gate state in Prometheus/Grafana.

## Implemented
- Exporter extended in `services/control_plane_metrics_exporter.py`:
  - Added report targets:
    - `reports/coordination/latest.json` as `report=coordination`
    - `reports/policy/coordination_policy_latest.json` as `report=coordination_policy`
  - Added gate projection from promotion summary `checks[]`:
    - emits `hbot_control_plane_gate_status{gate=<check_name>,severity=<...>,source="promotion_latest"}`
  - Added coordination runtime signals:
    - `hbot_control_plane_gate_status{gate="coordination_runtime_ok"}`
    - `hbot_control_plane_gate_status{gate="coordination_runtime_active"}`
    - `hbot_coordination_runtime_state{state=...}`
    - `hbot_coordination_decisions_seen`
    - `hbot_coordination_intents_emitted`
    - `hbot_coordination_allowed_instance_info{instance=...}`
  - Added coordination policy signal:
    - `hbot_control_plane_gate_status{gate="coordination_policy_ok"}`

- Prometheus alerts updated in `monitoring/prometheus/alert_rules.yml`:
  - Included `coordination` and `coordination_policy` in report missing/stale alerts.
  - Added `CoordinationPolicyGateFailed` (critical) on:
    - `hbot_control_plane_gate_status{gate="coordination_policy_scope",source="promotion_latest"} == 0`
  - Added `CoordinationRuntimeNotHealthy` (warning) on:
    - `hbot_control_plane_gate_status{gate="coordination_runtime_ok"} == 0`

- Grafana dashboard updated in `monitoring/grafana/dashboards/control_plane_overview.json`:
  - New panel: `Coord Policy Gate`
  - New panel: `Coord Runtime Health`

- Runbook updated in `docs/ops/runbooks.md`:
  - Added validation steps and key metrics under Day 33 section.

## Validation
- Static verification completed:
  - Exporter includes coordination artifacts and gate projection logic.
  - Alert rules include coordination missing/stale + dedicated coordination alerts.
  - Dashboard includes explicit coordination policy and runtime panels.
- Runtime validation command:
  - `curl -s http://localhost:9401/metrics | grep coordination`

## Outcome
- Coordination freshness and policy-gate visibility are now first-class control-plane signals.
- Promotion evidence (`checks[]`) is now directly queryable per gate in Prometheus.
- Existing operational blocker remains unchanged:
  - `event_store_integrity_freshness` can still keep promotion status at FAIL until fresh integrity artifacts are restored.
