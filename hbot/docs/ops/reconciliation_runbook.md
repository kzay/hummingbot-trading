# Reconciliation Runbook (Day 3 MVP)

## Purpose
Operate and validate the reconciliation service introduced in Option 4 Day 3.

## Service
- Runtime service: `reconciliation-service`
- Implementation: `hbot/services/reconciliation_service/main.py`
- Output directory: `hbot/reports/reconciliation/`

## Checks in MVP
- **Balance check**
  - Flags critical when `equity_quote <= 0` or `base_pct` not in `[0,1]`.
- **Position/inventory check**
  - Computes `abs(base_pct - target_base_pct)`.
  - Warning and critical thresholds are env-configurable.
- **Fill/order parity check**
  - Compares `fills.csv` row count vs `order_filled` event count in event store.
- **Exchange-source check (optional)**
  - When enabled, compares local `base_pct` vs external snapshot `base_pct`.
  - Snapshot path defaults to `reports/exchange_snapshots/latest.json`.
- **Accounting integrity check (Day 16)**
  - Emits per-bot `accounting_snapshots` in reconciliation output.
  - Validates fee counter monotonicity and turnover/fee consistency.
  - Flags:
    - `fees_paid_negative` (critical)
    - `fees_counter_decreased_warning|critical`
    - `turnover_without_fee_accrual` (warning)

## Severity Policy
- `critical`: hard anomalies needing immediate operator action.
- `warning`: mismatch or drift requiring follow-up.
- `ok`: no findings.

## Threshold Configuration
- File: `config/reconciliation_thresholds.json`
- Supports defaults and per-bot overrides for:
  - `enabled`
  - `inventory_check_enabled`
  - `exchange_check_enabled`
  - `fill_parity_check_enabled`
  - `accounting_check_enabled`
  - `inventory_warn`
  - `inventory_critical`
  - `exchange_drift_warn`
  - `exchange_drift_critical`
  - `fee_drop_warn`
  - `fee_drop_critical`
  - `turnover_fee_gap_warn`
- Runtime env:
  - `RECON_THRESHOLDS_PATH` (default `/workspace/hbot/config/reconciliation_thresholds.json`)

## Exchange Snapshot Account Mapping
- Mapping file: `config/exchange_account_map.json`
- Snapshot service mode:
  - `EXCHANGE_SNAPSHOT_MODE=bitget_ccxt_private`
- Credential prefix resolution:
  - `<PREFIX>_BITGET_API_KEY`
  - `<PREFIX>_BITGET_SECRET`
  - `<PREFIX>_BITGET_PASSPHRASE`
- Example mapping:
  - `bot2 -> BOT2`
  - `bot3 -> BOT3`
- Validation target:
  - `reports/exchange_snapshots/latest.json` should show expected per-bot mode status:
    - `bot1`: `account_probe_status=ok`
    - `bot2`: `account_probe_status=disabled`
    - `bot3`: `account_probe_status=paper_only`

## Alert Routing
- Reconciliation reports can trigger webhook alerts when severity threshold is met.
- Environment controls:
  - `RECON_ALERT_WEBHOOK_URL`
  - `RECON_ALERT_MIN_SEVERITY` (`warning` or `critical`)
- Evidence marker:
  - `reports/reconciliation/last_webhook_sent.json`

## Commands
- Start with external profile:
  - `docker compose --env-file ../env/.env --profile external up -d reconciliation-service`
- One-off local cycle:
  - `PYTHONPATH=. python services/reconciliation_service/main.py --once`
- Synthetic drift test:
  - `PYTHONPATH=. python services/reconciliation_service/main.py --once --synthetic-drift`

## Expected Artifacts
- `reports/reconciliation/reconciliation_<timestamp>.json`
- `reports/reconciliation/latest.json`

## Day 3 Acceptance (MVP)
- Reconciliation cycle runs and writes report artifacts.
- Reports contain severity classification.
- Synthetic drift test yields at least one `critical` finding.
- Webhook alert routing emits a payload when threshold is met.
- Threshold tuning is visible in report details (`warn_threshold`, `critical_threshold`).

## Incident Response
- If `status=critical` in latest report:
  - pause promotion activities
  - open incident entry in `docs/ops/incidents.md`
  - assign owner and remediation ETA
