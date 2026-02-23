# Accounting Contract v2 (Day 36)

## Purpose
Extend desk accounting evidence from report-only fields to a persisted, queryable layer with promotion-gate integrity checks.

## Scope Extension from v1
- Keep all `accounting_snapshots[]` fields from v1 reconciliation output.
- Persist snapshot rows to PostgreSQL (`accounting_snapshot` table) through `ops-db-writer`.
- Add a first-class integrity checker that validates freshness, required fields, and critical accounting findings.

## Canonical Inputs
- `reports/reconciliation/latest.json`
- `reports/reconciliation/reconciliation_<timestamp>.json`

## Canonical Outputs
- Postgres table:
  - `accounting_snapshot`
- Integrity artifact:
  - `reports/accounting/latest.json`
  - `reports/accounting/accounting_integrity_<timestamp>.json`

## Promotion Contract (v2)
- Gate name: `accounting_integrity_v2`
- Severity: `critical`
- Pass conditions:
  - reconciliation report is fresh (`ts_utc` within gate freshness budget),
  - `accounting_snapshots[]` is present and non-empty,
  - all required fields are present for each snapshot row,
  - no `findings[]` item with `check=accounting` and `severity=critical`,
  - `fees_paid_today_quote` and `funding_paid_today_quote` are non-negative.

## Required Fields per Snapshot
- `bot`
- `exchange`
- `trading_pair`
- `mid`
- `equity_quote`
- `base_balance`
- `quote_balance`
- `fees_paid_today_quote`
- `funding_paid_today_quote`
- `daily_loss_pct`
- `drawdown_pct`
- `fee_source`

## Operational Queries
- Latest per-bot accounting snapshot:
  - `SELECT * FROM accounting_snapshot ORDER BY ts_utc DESC, bot;`
- Fee/funding trail (recent horizon):
  - `SELECT bot, ts_utc, fees_paid_today_quote, funding_paid_today_quote FROM accounting_snapshot WHERE ts_utc > now() - interval '24 hours' ORDER BY ts_utc DESC, bot;`

## Notes
- v2 does not yet split realized vs unrealized PnL attribution at fill-level lineage; it establishes the persistence and integrity backbone for that next increment.
