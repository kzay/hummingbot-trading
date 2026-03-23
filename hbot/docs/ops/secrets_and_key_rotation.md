# Secrets and Key Rotation (Day 12/20, ROAD-8)

## Purpose
Define safe handling rules, key rotation procedure, and break-glass policy for trading credentials.

## Scope
- Environment variables in `infra/env/.env`.
- Exchange credentials used by bot connectors and external services.
- Operational artifacts (logs/reports/docs) where accidental leaks can appear.

## Non-Negotiable Rules
- Never commit `infra/env/.env` or plaintext credentials.
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

## Three API Key Policy (ROAD-8)

Use three distinct API keys for production:

| Key | Permissions | Env Vars | Purpose |
|-----|-------------|----------|---------|
| **Read-only data** | Read only (balances, order book, positions) | Optional; can share with bot key | Data feeds, exchange snapshot, reconciliation probes |
| **Trade-only bot** | Trade + read (no withdraw) | `BOT1_BITGET_API_KEY`, `BOT1_BITGET_API_SECRET`, `BOT1_BITGET_PASSPHRASE` | Bot execution; primary trading key |
| **Kill-switch emergency** | Trade + cancel only | `KILL_SWITCH_API_KEY`, `KILL_SWITCH_SECRET`, `KILL_SWITCH_PASSPHRASE` | Emergency cancel-all; survives bot process death |

**Why a separate kill-switch key?** The kill-switch service runs in its own container and must cancel orders even when the bot is frozen or crashed. Using the same key as the bot would require the bot to be healthy to trigger cancels. A dedicated key allows out-of-band HTTP trigger (`POST /kill`) and ccxt-based cancel-all without depending on bot state.

## IP Allowlist Requirement

- **All keys** must have IP allowlist configured on the exchange when supported.
- Restrict to deployment host(s) and any monitoring/ops IPs.
- Reduces blast radius if a key is leaked.

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
- **90-day rotation** recommended for all keys (ROAD-8).

## 90-Day Rotation Procedure

1. **Create new key** — Generate at exchange with same permissions; add to IP allowlist.
2. **Update `.env`** — Replace old key/secret/passphrase with new values on host.
3. **Restart services** — Recreate affected containers:
   - Bot key: `bot1`, `exchange-snapshot-service`
   - Kill-switch key: `kill-switch`
   - Example: `docker compose --env-file infra/env/.env -f infra/compose/docker-compose.yml up -d --force-recreate bot1 exchange-snapshot-service kill-switch`
4. **Revoke old key** — After validation, revoke at exchange.
5. **Verify** — Snapshot healthy; reconciliation within thresholds; kill-switch dry-run succeeds.

## Standard Rotation Procedure (Legacy / Ad-Hoc)
1. **Prepare**
   - Generate new exchange keys with least privilege.
   - Keep old keys active during cutover window.
2. **Stage**
   - Update `infra/env/.env` on host (never in repo history).
   - Verify key prefixes map correctly in `config/exchange_account_map.json`.
3. **Cutover**
   - Recreate only required services:
     - `exchange-snapshot-service`
     - affected bot container(s)
   - Example:
     - `docker compose --env-file infra/env/.env -f infra/compose/docker-compose.yml up -d --force-recreate exchange-snapshot-service bot1`
4. **Validate**
   - Confirm snapshot probe status is healthy in:
     - `reports/exchange_snapshots/latest.json`
   - Confirm no critical reconciliation drift:
     - `reports/reconciliation/latest.json`
5. **Finalize**
   - Revoke old keys.
   - Record rotation metadata (time/owner/scope) without secret values.

## Emergency Rotation Checklist (Compromised Key)

Use when a key is suspected compromised or unauthorized activity is detected:

1. [ ] **Pause trading** — Trigger `soft_pause` or kill switch immediately.
2. [ ] **Revoke compromised key** at exchange (do not wait).
3. [ ] **Create emergency key** with same permissions; add to IP allowlist.
4. [ ] **Update `.env`** with new key/secret/passphrase.
5. [ ] **Restart affected services** (bot, exchange-snapshot, kill-switch if that key).
6. [ ] **Validate** — Snapshot, reconciliation, kill-switch health.
7. [ ] **Incident note** — Timestamp, impacted bots, key scope revoked/rotated, validation evidence (no secret values).

## Kill-Switch Integration

The kill-switch service uses **its own API key** (`KILL_SWITCH_API_KEY`, `KILL_SWITCH_SECRET`, `KILL_SWITCH_PASSPHRASE`), not the bot key. This allows:

- **Out-of-band triggering** — HTTP `POST /kill` works even when the bot is frozen.
- **Independent lifecycle** — Kill-switch container can run and cancel orders without the bot process.
- **Blast radius containment** — If the bot key is compromised, the kill-switch key can still cancel; if the kill-switch key is compromised, it can only cancel (no new orders from the bot key).

Rotate the kill-switch key on the same 90-day schedule; use the emergency checklist if compromised.

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
- Last-updated: 2026-02-27 (ROAD-8)
