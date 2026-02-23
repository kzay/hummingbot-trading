# Reconciliation Evidence - 2026-02-21

## Phase
Day 3 - Reconciliation Service (MVP + hardening pass)

## Plan Executed
1. Reconciliation service scaffold implemented.
2. Compose wiring added for `reconciliation-service` (external profile).
3. One-off synthetic drift test executed and verified.
4. Service started in container runtime.
5. Added webhook alert routing from reconciliation outputs.
6. Added exchange-source snapshot comparison hook.

## Evidence Artifacts
- Service implementation:
  - `hbot/services/reconciliation_service/main.py`
- Runtime runbook:
  - `hbot/docs/ops/reconciliation_runbook.md`
- Runtime reports:
  - `hbot/reports/reconciliation/reconciliation_20260221T172336Z.json`
  - `hbot/reports/reconciliation/latest.json`
  - `hbot/reports/reconciliation/last_webhook_sent.json`
- Exchange snapshot source:
  - `hbot/services/exchange_snapshot_service/main.py`
  - `hbot/reports/exchange_snapshots/latest.json`

## Synthetic Drift Validation
- Test command used:
  - `python services/reconciliation_service/main.py --once --synthetic-drift`
- Result:
  - `status=critical`
  - `critical_count=1`
  - `check=synthetic_drift_test`
- Acceptance:
  - Drift severity and critical path verified.

## Hardening Validation
- Webhook routing:
  - Reconciliation report emits webhook payload when severity threshold is met.
  - Evidence marker written to `reports/reconciliation/last_webhook_sent.json`.
- Exchange-source hook:
  - Exchange snapshot producer service is running and writing `reports/exchange_snapshots/latest.json`.
  - Latest reconciliation report now consumes snapshot path without `exchange_snapshot_missing` warnings.
  - Warning count reduced from snapshot-missing + inventory warnings to inventory-only warnings.
- Authoritative probe mode:
  - `exchange_snapshot_service` now supports `mode=bitget_ccxt_private`.
  - Latest snapshot confirms `account_probe.status=ok` with Bitget account balances payload.
  - Evidence: `reports/exchange_snapshots/latest.json`.
- Per-bot account mapping:
  - Mapping file added: `config/exchange_account_map.json`.
  - Snapshot now includes per-bot `account_scope`, `account_credential_prefix`, and `account_probe_status`.
  - Current credential validation outcomes from latest snapshot:
    - `bot2`: `fetch_failed` (`Apikey does not exist`) for `BOT2` prefix.
    - `bot3`: `missing_credentials` for `BOT3` prefix.
  - Action required: correct/fill `BOT2_*` and `BOT3_*` Bitget credentials for full authoritative parity.
- Per-bot thresholds:
  - Config file added: `config/reconciliation_thresholds.json`
  - Reconciliation report now includes threshold values per finding:
    - `warn_threshold`
    - `critical_threshold`
  - Runtime confirms thresholds loaded via `thresholds_path` in `reports/reconciliation/latest.json`.

## Runtime Activation
- Service started:
  - `docker compose --env-file ../env/.env --profile external up -d reconciliation-service`
- Status check:
  - `reconciliation-service` up/running

## Notes
- Current reconciliation includes local artifacts, event-store parity, webhook alert routing, and exchange snapshot hook.
- Next hardening step is to feed authoritative exchange snapshots into `reports/exchange_snapshots/latest.json`.
