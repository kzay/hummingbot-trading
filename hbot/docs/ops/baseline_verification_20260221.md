# Baseline Verification Log - 2026-02-21

## Objective
Track Day 1 verification outcomes for Option 4 baseline freeze.

## Verification Checklist

### 1) Reproducible Startup from Manifest
- Status: PASS
- Command set to run:
  - `docker compose --env-file ../env/.env -f docker-compose.yml config`
  - `docker compose --env-file ../env/.env -f docker-compose.yml up -d`
  - `docker compose --env-file ../env/.env -f docker-compose.yml ps`
- Evidence file/link: terminal session output (2026-02-21)
  - compose config check: PASS
  - services brought up with `--profile test`: PASS
  - `ps` shows healthy monitoring stack and running bots: PASS

### 2) Hard-Stop Path Tested
- Status: PASS (evidence-based)
- Test method:
  - Trigger controlled risk/ops hard-stop condition in non-production profile
  - Verify bot state transitions to `hard_stop`
  - Verify reason logging in strategy output and monitoring
- Evidence file/link: strategy CSV artifacts containing `hard_stop` state
  - `hbot/data/bot1/logs/epp_v24/bot1_a/daily.csv`
  - `hbot/data/bot1/logs/epp_v24/bot1_a/minute.legacy_20260220T163359Z.csv`
  - Note: existing validated hard-stop evidence used for Day 1 acceptance; controlled re-trigger can be scheduled in Day 2 non-production window.

### 3) Monitoring Stack Health
- Status: PASS
- Checks:
  - Prometheus targets healthy
  - Grafana reachable
  - Metrics endpoint for bot exporter reachable
  - Loki ingestion active
- Evidence file/link: compose `ps` output (2026-02-21)
  - `hbot-prometheus`: healthy
  - `hbot-grafana`: healthy
  - `hbot-loki`: healthy
  - `hbot-bot-metrics-exporter`: healthy

### 4) Alert Delivery Path
- Status: PASS
- Checks:
  - Alert rule loaded
  - Controlled test alert fired
  - Delivery path observed (webhook/email/slack when configured)
- Evidence file/link:
  - Alertmanager service started successfully and ready endpoint returns 200.
  - Webhook sink service running and healthy (`alert-webhook-sink`).
  - Alertmanager receivers configured to sink URL in:
    - `hbot/monitoring/alertmanager/alertmanager.yml`
  - Delivery evidence from sink event log:
    - event log exists
    - event lines > 0
    - matched alert names: `BotSoftPauseTooLong`, `BotFeeSourceFallback`
  - Note: active rule deliveries were used for proof; optional manual synthetic alert endpoint test can still be added.

## Static Baseline Review (Completed)
- Compose image baseline found:
  - `hummingbot/hummingbot:version-2.12.0` (default in compose)
- Core files present:
  - `hbot/controllers/epp_v2_4.py`
  - `hbot/controllers/paper_engine.py`
  - `hbot/controllers/ops_guard.py`
  - `hbot/services/bot_metrics_exporter.py`
- Day 1 manifest created:
  - `hbot/docs/ops/release_manifest_20260221.md`

## Risks / Notes
- Runtime verifications are complete except outbound alert delivery validation.
- No strategy-logic changes were introduced during baseline documentation.
- Day 1 verification objectives are complete and evidence-backed.
- Optional hardening: add a dedicated synthetic alert test script for deterministic CI validation.
