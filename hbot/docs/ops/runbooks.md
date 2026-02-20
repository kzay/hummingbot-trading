# Runbooks

## Purpose
Operational SOPs for startup, shutdown, recovery, and controlled changes.

## Startup (external orchestration)
1. Validate `env/.env`.
2. Start:
   - `docker compose --env-file ../env/.env --profile multi --profile external up -d`
3. Confirm service health (`ps`, logs, Redis ping).
4. Start/verify strategy in bot terminal.

## Shutdown
- Graceful:
  - `docker compose --env-file ../env/.env --profile multi --profile external down`

## Degraded Mode
- Redis down:
  - restart without `--profile external`
  - keep local HB safeguards active

## Rollback
- Revert to previous image/config snapshot.
- Run post-rollback health checks and log verification.

## Paper Trade Startup

1. For EPP v2.4 controllers, keep `connector_name: bitget_paper_trade` and
   `internal_paper_enabled: true`.
2. In `conf_client.yml`, ensure:
   - `paper_trade_exchanges: [bitget]`
   - `paper_trade_account_balance` includes realistic BTC/USDT balances.
3. For standalone scripts (bot3): use `bitget_paper_trade` in the `markets` dict
   and enable `paper_trade_exchanges: [bitget]` in `conf_client.yml`.
4. Start the bot and verify `status` includes paper diagnostics (`paper fills`,
   `rejects`, `avg_qdelay_ms`) plus controller regime/spread data.
5. If you need emergency rollback, set `internal_paper_enabled: false` and
   recreate the bot container.

## EPP Paper Validation Checklist (24h minimum)

Track these KPIs from `minute.csv` / `fills.csv` before changing capital:

- Stability
  - `% running` >= 65%
  - No repetitive minute-by-minute flapping between `running` and `soft_pause`
- Risk
  - `turnover_today_x` <= 3.0
  - `daily_loss_pct` < 1.5% and `drawdown_pct` < 2.5%
  - No `hard_stop` events from risk limits
- Execution quality
  - `cancel_per_min` below configured budget for >95% of samples
  - Fee source remains resolved (`api:*`, `connector:*`, or `project:*`)
  - `paper_reject_count` remains near zero after startup warmup
- Inventory
  - `base_pct` remains inside configured hard band (`min_base_pct`..`max_base_pct`)
  - `base_pct` tracking error vs target shrinks after large deviations

## Stale `.pyc` Cache Fix

When modifying mounted controller files (`epp_v2_4.py` etc.), the container's
Python bytecache may serve the old version. `docker restart` does NOT clear it.

Fix:
```bash
docker exec hbot-bot1 rm -rf /home/hummingbot/controllers/__pycache__ \
    /home/hummingbot/controllers/market_making/__pycache__
docker compose --env-file ../env/.env -f docker-compose.yml up -d --force-recreate bot1
```

## Checklist
- Connector ready
- No growing errors.log
- Audit stream populated
- Dead-letter volume acceptable

## Owner
- Operations
- Last-updated: 2026-02-20


## Dashboard Operations

### Startup

1. Start monitoring services:
   - `docker compose --env-file ../env/.env up -d prometheus grafana node-exporter cadvisor bot-metrics-exporter loki promtail`
2. Verify Prometheus target health (`/targets`) and datasource health in Grafana.
3. Open dashboards:
   - `Hummingbot Trading Desk Overview`
   - `Hummingbot Bot Deep Dive`

### Validation Checklist

- `bot-metrics` target is `UP`.
- Loki datasource responds and log panels return records.
- Per-bot KPI panels refresh in <30s.
- Alert rules loaded without errors in Prometheus (`/rules`).
- At least one controlled alert test performed (e.g., stop a bot container to trigger alert).

### Incident Triage (Trading)

1. Check bot state and net edge panels (running/soft_pause/hard_stop).
2. Inspect fee source panel (API vs fallback) before adjusting strategy thresholds.
3. Use Loki logs panel filtered by `bot` + `ERROR` for fast root-cause isolation.
4. Cross-check container restarts and host resource saturation in infrastructure dashboard.
