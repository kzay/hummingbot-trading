# Release Manifest - 2026-02-21

## Purpose
Freeze a reproducible Day 1 baseline for Option 4 execution.

## Runtime Baseline
- Compose file: `hbot/compose/docker-compose.yml`
- Hummingbot base image (default): `hummingbot/hummingbot:version-2.12.0`
- Restart policy: `unless-stopped`
- Strategy runtime mode: Hummingbot v2 controller-based execution

## Strategy/Controller Baseline
- Primary controller: `hbot/controllers/epp_v2_4.py`
- Paper/sim adapter: `hbot/controllers/paper_engine.py`
- Guardrail state machine: `hbot/controllers/ops_guard.py`
- Runtime adapter: `hbot/controllers/connector_runtime_adapter.py`

## Active Config Set (Declared Baseline)
- Bot1 Bitget paper smoke controller:
  - `hbot/data/bot1/conf/controllers/epp_v2_4_bitget_paper_smoke.yml`
- Bot3 paper smoke controller:
  - `hbot/data/bot3/conf/controllers/epp_v2_4_bot3_paper_smoke.yml`
- Bot4 Binance testnet smoke controller:
  - `hbot/data/bot4/conf/controllers/epp_v2_4_bot4_binance_smoke.yml`

## Risk and Safety Baseline
- Core limits declared in controller config/model:
  - `min_base_pct`, `max_base_pct`
  - `max_order_notional_quote`, `max_total_notional_quote`
  - `max_daily_turnover_x_hard`
  - `max_daily_loss_pct_hard`
  - `max_drawdown_pct_hard`
- OpsGuard states:
  - `running`, `soft_pause`, `hard_stop`

## Monitoring and Logging Baseline
- Metrics exporter:
  - `hbot/services/bot_metrics_exporter.py`
- Monitoring stack services (compose):
  - Prometheus, Grafana, Loki, Promtail, node-exporter, cAdvisor
- Trading logs:
  - per-bot logs under `hbot/data/bot*/logs/`
  - controller CSV artifacts under `epp_v24/*/minute.csv`, `daily.csv`, `fills.csv`

## External Control-Plane Runtime (Day 8 Update)
- Reproducible external image (default tag):
  - `hbot-control-plane:20260222`
- Compose variable:
  - `HBOT_CONTROL_PLANE_IMAGE`
- Build provenance:
  - Dockerfile: `hbot/compose/images/control_plane/Dockerfile`
  - pinned dependencies: `hbot/compose/images/control_plane/requirements-control-plane.txt`
- External services using this image:
  - `signal-service`, `risk-service`, `coordination-service`
  - `event-store-service`, `event-store-monitor`, `day2-gate-monitor`
  - `reconciliation-service`, `exchange-snapshot-service`
  - `shadow-parity-service`, `portfolio-risk-service`
  - `soak-monitor`, `daily-ops-reporter`

## Option 4 Day 1 Status
- Manifest creation: DONE
- Reproducible startup verification: PENDING
- Hard-stop scenario evidence: PENDING
- Monitoring stack health verification: PENDING
- Alert delivery path test: PENDING

## Change Control
- Strategy logic changes are out of scope for Day 1 baseline freeze.
- Any runtime modifications must be documented in:
  - `hbot/docs/ops/baseline_verification_20260221.md`
  - `hbot/docs/ops/option4_execution_progress.md`
