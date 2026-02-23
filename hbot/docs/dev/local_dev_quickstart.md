# Local Dev Quickstart (Day 11)

## Purpose
Provide one-command local workflows for test/external bring-up and fast developer checks.

## Preconditions
- Docker Desktop running.
- `.env` present at `hbot/env/.env`.
- Run all commands from `hbot/`.

## One-Command Profile Bring-Up
- Start test profile:
  - `python scripts/release/dev_workflow.py up-test`
- Stop test profile:
  - `python scripts/release/dev_workflow.py down-test`
- Start external profile:
  - `python scripts/release/dev_workflow.py up-external`
- Stop external profile:
  - `python scripts/release/dev_workflow.py down-external`

## Fast Developer Checks (lint + unit + minimal smoke)
- Command:
  - `python scripts/release/dev_workflow.py fast-checks`
- What it checks:
  - syntax/lint proxy: `python -m compileall controllers services scripts tests`
  - lightweight unit checks:
    - `tests.services.test_event_schemas`
    - `tests.controllers.test_paper_engine`
  - minimal smoke evidence:
    - bot4 minute artifact exists
    - bot3 exchange snapshot is `paper_only`
- Output artifacts:
  - `reports/dev_checks/latest.json`
  - `reports/dev_checks/dev_fast_checks_<timestamp>.json`

## Canonical Smoke Workflow (bot3 + bot4)
1. Start test profile:
   - `python scripts/release/dev_workflow.py up-test`
2. In bot3 terminal, run paper smoke:
   - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot3_paper_smoke.yml`
3. In bot4 terminal, run Binance testnet smoke:
   - `start --script v2_with_controllers.py --conf v2_epp_v2_4_bot4_binance_smoke.yml`
4. Run fast checks:
   - `python scripts/release/dev_workflow.py fast-checks`

## Stale Cache Footgun (Automated)
- If controller code changes are not reflected:
  - `python scripts/release/dev_workflow.py clear-pyc --bot bot1`
  - then recreate the bot container:
    - `docker compose --env-file env/.env -f compose/docker-compose.yml up -d --force-recreate bot1`

## Expected Runtime
- Fast checks should complete in a short and predictable window (typically under 1 minute on a warm workspace).
