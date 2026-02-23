# Day 36 - Full Accounting Layer v2 (2026-02-22)

## Objective
- Deliver Day 36 accounting persistence and integrity checks as production artifacts.
- Keep promotion fail-closed by adding accounting health as a critical gate.

## Implemented
- New integrity checker:
  - `scripts/release/check_accounting_integrity_v2.py`
- Promotion gate integration:
  - `scripts/release/run_promotion_gates.py`
  - new critical gate: `accounting_integrity_v2`
- Ops DB schema extension:
  - `services/ops_db_writer/schema_v1.sql`
  - new table: `accounting_snapshot`
- Ops DB writer ingestion:
  - `services/ops_db_writer/main.py`
  - new ingestion path from `reports/reconciliation/latest.json` `accounting_snapshots[]` into `accounting_snapshot`
- Contract update:
  - `docs/validation/accounting_contract_v2.md`

## Validation Commands
- Accounting integrity checker:
  - `python scripts/release/check_accounting_integrity_v2.py --max-age-min 20`
- Promotion gates (CI profile):
  - `python scripts/release/run_promotion_gates.py --ci`
- Ops DB writer one-shot:
  - `python services/ops_db_writer/main.py --once`

## Expected Evidence
- `reports/accounting/latest.json`
- `reports/promotion_gates/latest.json` (contains `accounting_integrity_v2`)
- `reports/ops_db_writer/latest.json` (includes `accounting_snapshot` row count)

## Outcome
- Day 36 accounting layer v2 baseline is delivered:
  - persistence path is in place,
  - integrity checks are artifacted,
  - promotion gate now blocks on critical accounting regressions.
