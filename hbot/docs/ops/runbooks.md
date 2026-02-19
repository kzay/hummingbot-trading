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

1. Ensure Bitget spot account has some balance (even 2 USDT) so the connector
   initializes (`account_balance` readiness check requires `len(_account_balances) > 0`).
2. For V2 controllers: set `paper_mode: true` in controller YAML.
   `connector_name` stays `bitget` (not `bitget_paper_trade`).
3. For standalone scripts (bot3): use `bitget_paper_trade` in the `markets` dict
   and enable `paper_trade_exchanges: [bitget]` in `conf_client.yml`.
4. Start the bot and verify `status` output shows expected paper balances or
   controller regime/spread data.

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
- Last-updated: 2026-02-19

