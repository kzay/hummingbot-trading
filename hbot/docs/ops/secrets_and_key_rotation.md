# Secrets and Key Rotation (Day 12/20)

## Purpose
Define safe handling rules, key rotation procedure, and break-glass policy for trading credentials.

## Scope
- Environment variables in `env/.env`.
- Exchange credentials used by bot connectors and external services.
- Operational artifacts (logs/reports/docs) where accidental leaks can appear.

## Non-Negotiable Rules
- Never commit `env/.env` or plaintext credentials.
- Never paste secret values in:
  - `docs/`
  - `reports/`
  - incident notes
  - chat/collaboration channels
- Never log full credentials; only log masked metadata (last 4 chars max).
- Keep exchange keys least-privilege:
  - trade-only where possible
  - no withdraw permission
  - IP allowlist enabled when supported

## Secret Inventory (Current Runtime)
- `BOT*_BITGET_API_KEY`
- `BOT*_BITGET_API_SECRET`
- `BOT*_BITGET_PASSPHRASE`
- `REDIS_PASSWORD` (if enabled)
- `BOT*_PASSWORD` (connector/password gate where used)

## Rotation SLO
- Planned restart window only.
- Target service interruption: <= 5 minutes for external services.
- No strategy code changes required for key rotation.

## Standard Rotation Procedure
1. **Prepare**
   - Generate new exchange keys with least privilege.
   - Keep old keys active during cutover window.
2. **Stage**
   - Update `env/.env` on host (never in repo history).
   - Verify key prefixes map correctly in `config/exchange_account_map.json`.
3. **Cutover**
   - Recreate only required services:
     - `exchange-snapshot-service`
     - affected bot container(s)
   - Example:
     - `docker compose --env-file env/.env -f compose/docker-compose.yml up -d --force-recreate exchange-snapshot-service bot1`
4. **Validate**
   - Confirm snapshot probe status is healthy in:
     - `reports/exchange_snapshots/latest.json`
   - Confirm no critical reconciliation drift:
     - `reports/reconciliation/latest.json`
5. **Finalize**
   - Revoke old keys.
   - Record rotation metadata (time/owner/scope) without secret values.

## Break-Glass Policy
Use break-glass only if credential compromise is suspected or unauthorized activity is detected.

Immediate actions:
1. Trigger safe mode:
   - pause/kill affected bots (`soft_pause` then `kill_switch` if needed).
2. Revoke compromised keys at exchange.
3. Rotate to emergency keys.
4. Recreate affected services and revalidate reconciliation/parity/risk.
5. Append incident note with:
   - timestamp
   - impacted bots
   - key scope revoked/rotated
   - validation evidence paths

## Safe Logging Rules
- Allowed:
  - key ownership prefix (`BOT1`, `BOT4`)
  - status (`ok`, `disabled`, `paper_only`, `error`)
  - masked token suffix (`****ABCD`)
- Forbidden:
  - full key/secret/passphrase values
  - raw auth headers
  - signed payloads containing credentials

## Day 20 Operational Hardening Additions
- Automated hygiene scan entrypoint:
  - `python scripts/release/run_secrets_hygiene_check.py --include-logs`
- Scan contract:
  - scopes: `docs/`, `reports/`, and `data/*/logs` text artifacts
  - output: `reports/security/latest.json`
  - expected status before promotion: `pass`
- Exchange probe error safety:
  - `services/exchange_snapshot_service/main.py` now redacts active credential values from exception text before writing report payloads.

## Pre-Release Secrets Hygiene Checklist
- [ ] `python scripts/release/run_secrets_hygiene_check.py --include-logs` returns `status=pass`.
- [ ] `reports/security/latest.json` attached as release evidence.
- [ ] No raw key/secret/passphrase values appear in:
  - `reports/exchange_snapshots/latest.json`
  - incident notes
  - promotion gate artifacts
- [ ] Break-glass owner confirms key revoke + rotate path is current.

## Verification Checklist (Day 12)
- [ ] `reports/` contains no plaintext credential markers.
- [ ] `docs/` contains no plaintext credential markers.
- [ ] Rotation procedure tested in planned restart window.
- [ ] Break-glass owner/on-call path documented.

## Evidence (This Phase)
- Repo scan for common secret markers in `reports/`: no matches.
- Repo scan for common secret markers in `docs/`: only variable names/templates, no secret values.

## Owner
- Ops + Engineering
- Last-updated: 2026-02-22 (Day 20)
