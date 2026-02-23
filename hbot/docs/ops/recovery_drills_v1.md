# Recovery Drills v1 (Day 28)

## Purpose
Define repeatable recovery drills for control-plane services and event/report freshness safety signals.

## Drill 1 - Event Store Staleness Fail-Closed
- Scenario:
  - stop `event-store-service` and wait beyond freshness threshold.
- Steps:
  1. `docker compose --env-file env/.env --profile external -f compose/docker-compose.yml stop event-store-service`
  2. wait until `event_store_integrity_freshness` should become stale
  3. run `python scripts/release/run_promotion_gates.py --ci`
- Expected:
  - gate status `FAIL`
  - `critical_failures` includes `event_store_integrity_freshness`
- Recovery:
  1. start `event-store-service`
  2. wait for monitor refresh artifact
  3. rerun promotion gates

## Drill 2 - Portfolio Risk Report Staleness
- Scenario:
  - stop `portfolio-risk-service` and verify freshness block.
- Steps:
  1. `docker compose --env-file env/.env --profile external -f compose/docker-compose.yml stop portfolio-risk-service`
  2. wait beyond `PORTFOLIO_RISK_HEALTH_MAX_SEC`
  3. run `python scripts/release/run_promotion_gates.py --ci`
- Expected:
  - gate status `FAIL`
  - `critical_failures` includes `portfolio_risk_status`
- Recovery:
  1. start `portfolio-risk-service`
  2. verify `reports/portfolio_risk/latest.json` freshness
  3. rerun gates

## Drill 3 - Ops DB Writer Restart Idempotency
- Scenario:
  - restart writer and ensure no duplicate amplification.
- Steps:
  1. run `docker compose --env-file env/.env --profile ops -f compose/docker-compose.yml run --rm ops-db-writer python /workspace/hbot/services/ops_db_writer/main.py --once`
  2. capture row counts
  3. run same command again
  4. compare row counts and key uniqueness constraints
- Expected:
  - no duplicate key amplification
  - writer report `status=pass`

## Operator Notes
- Do not promote while any freshness-critical report is stale.
- Always collect evidence paths from gate output (`reports/promotion_gates/latest.json`) after each drill.
