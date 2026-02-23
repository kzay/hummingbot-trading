# Secrets and Environment

## Purpose
Document environment variables, credential handling, and secret hygiene.

Related runbook:
- `docs/ops/secrets_and_key_rotation.md`

## Scope
All runtime services using `env/.env` and encrypted connector configs.

## Secret Handling
- Never commit `env/.env`.
- Keep `env/.env.template` as non-secret defaults.
- Store exchange keys through Hummingbot encrypted connector files when possible.
- Restrict file access (`chmod 600` equivalent on host where possible).

## Sensitive Variables
- `BOT*_BITGET_API_KEY`, `BOT*_BITGET_API_SECRET`, `BOT*_BITGET_PASSPHRASE`
- `BOT*_PASSWORD`
- `REDIS_PASSWORD` (if used)

## External ML/Signal Vars
- `EXT_SIGNAL_RISK_ENABLED`
- `ML_*`
- `RISK_*`
- `REDIS_*`

## Failure Modes
- Missing password verification files -> non-interactive startup failures.
- Invalid rate oracle source -> client config errors.

## Source of Truth
- `hbot/env/.env.template`
- `hbot/data/bot*/conf/conf_client.yml`

## Owner
- Engineering/SRE
- Last-updated: 2026-02-19

