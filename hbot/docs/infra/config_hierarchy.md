# Config Hierarchy (DEBT-4)

## Overview

The hbot trading system uses four config sources with defined precedence. This doc clarifies how they interact and which vars are required per deployment mode.

## Four Config Sources

| Source | Location | Loaded By | When |
|--------|----------|-----------|------|
| **Env vars** | `env/.env` | Docker Compose / shell | Before container start |
| **Docker Compose env blocks** | `compose/docker-compose.yml` | Compose | Service definition (defaults, overrides) |
| **JSON policy configs** | `config/*.json` | Services / controllers | At startup or per-cycle |
| **YAML controller config** | `data/bot1/conf/controllers/*.yml` | Hummingbot strategy | When strategy loads |

## Precedence Order

1. **Env var** (highest) — values from `env/.env` passed via `--env-file`
2. **Docker Compose** — service `environment:` blocks with `${VAR:-default}` syntax
3. **Service default** — hardcoded fallback in code

For JSON and YAML:
- **JSON** — loaded at service startup (e.g. `multi_bot_policy_v1.json`, `fee_profiles.json`, `reconciliation_thresholds.json`)
- **YAML** — loaded by Hummingbot when the strategy starts; referenced via `SCRIPT_CONFIG` env (e.g. `v2_epp_v2_4_bot_a.yml`)

## Required Vars by Deployment Mode

| Mode | Required Env Vars |
|------|-------------------|
| **Paper** | `BOT1_PASSWORD`, `BOT1_MODE=paper` (or `BOT_MODE=paper` via Compose). API keys optional for pure paper. |
| **Live (bot only)** | `BOT1_BITGET_API_KEY`, `BOT1_BITGET_API_SECRET`, `BOT1_BITGET_PASSPHRASE`, `BOT1_PASSWORD`, `BOT1_MODE=live` |
| **Full stack** | Above + `REDIS_HOST`, `REDIS_PORT`; for kill switch: `KILL_SWITCH_API_KEY`, `KILL_SWITCH_SECRET`, `KILL_SWITCH_PASSPHRASE`; for exchange snapshot: same as bot keys or `EXCHANGE_ACCOUNT_MAP_PATH` |

## `fee_mode: auto` Resolution

When YAML has `fee_mode: auto` (and `fee_profile`, e.g. `vip0`), the controller resolves fees in this order:

1. **API** — `FeeResolver.from_exchange_api()` (Bitget `/api/user/v1/fee/query`)
2. **Project JSON** — `config/fee_profiles.json` via `FeeResolver.from_project_profile(connector_name, fee_profile)`
3. **Manual YAML** — `spot_fee_pct` as fallback (only if `require_fee_resolution: false`)

Evidence: `processed_data.fee_source` shows `api:bitget:user_fee_query`, `project:.../fee_profiles.json`, or `manual_fallback:spot_fee_pct`.

## Critical Env Vars by Service

| Env Var | Service(s) | Purpose |
|---------|------------|---------|
| `BOT1_BITGET_API_KEY/SECRET/PASSPHRASE` | bot1, exchange-snapshot-service | Exchange auth |
| `BOT1_PASSWORD` | bot1 | Hummingbot config gate |
| `BOT1_MODE` | bot1 (via `BOT_MODE`) | `paper` or `live` |
| `KILL_SWITCH_API_KEY/SECRET/PASSPHRASE` | kill-switch | Emergency cancel-all (separate key) |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` | bot1, signal-service, risk-service, kill-switch, coordination, event-store, etc. | Redis bus |
| `EXT_SIGNAL_RISK_ENABLED` | bot1, signal-service, risk-service | Enable external signal stack |
| `ML_ENABLED`, `ML_MODEL_URI` | signal-service | ML inference |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | alertmanager, bot-watchdog, telegram-bot | Alerts |
| `GF_ADMIN_USER`, `GF_ADMIN_PASSWORD` | grafana | Grafana auth |
| `HB_FEE_PROFILE_PATH` | FeeResolver (optional) | Override path to `fee_profiles.json` |
| `FETCH_PERP_POSITIONS` | exchange-snapshot-service | Enable perp position fetch (`true` default) |

## Related Files

- `env/.env.template` — full env var list
- `compose/docker-compose.yml` — service env blocks
- `config/fee_profiles.json` — fee profiles for `fee_mode: project` / fallback
- `config/multi_bot_policy_v1.json` — bot roles and modes
- `data/bot1/conf/controllers/epp_v2_4_bot_a.yml` — controller YAML
