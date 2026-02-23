# Accounting Contract v1 (Day 16)

## Purpose
Define desk-grade accounting fields and integrity rules so operators can explain daily PnL drivers from artifacts.

## Contract Scope
- Fees paid (by venue/asset context from bot snapshots).
- Funding/borrow placeholders (for perps/margin capable connectors).
- Realized/unrealized PnL context via `equity_quote`, `daily_loss_pct`, `drawdown_pct`.
- Position inventory snapshots (`base_balance`, `quote_balance`, `base_pct`, `target_base_pct`).

## Canonical Artifact
- Reconciliation report:
  - `reports/reconciliation/latest.json`
  - `reports/reconciliation/reconciliation_<timestamp>.json`

## Required Fields in Reconciliation Output
- `accounting_snapshots[]` per checked bot:
  - `bot`
  - `exchange`
  - `trading_pair`
  - `mid`
  - `equity_quote`
  - `base_balance`
  - `quote_balance`
  - `fees_paid_today_quote`
  - `funding_paid_today_quote` (0 when unavailable)
  - `daily_loss_pct`
  - `drawdown_pct`
  - `fee_source`

## Accounting Integrity Checks (v1)
Configured in `config/reconciliation_thresholds.json`:
- `accounting_check_enabled`
- `fee_drop_warn`
- `fee_drop_critical`
- `turnover_fee_gap_warn`

Checks emitted in `findings[]` with `check=accounting`:
1. `fees_paid_negative` (critical)
   - `fees_paid_today_quote < 0` is invalid.
2. `fees_counter_decreased_warning|critical`
   - fee counter drops between consecutive minute snapshots beyond threshold.
3. `turnover_without_fee_accrual` (warning)
   - turnover increases in a fee-paying profile while fee counter does not increase.

## Operator Questions Answered
- “What drove daily PnL today?”
  - read `equity_quote`, `daily_loss_pct`, `drawdown_pct`, and fee/funding snapshots in reconciliation artifact.
- “Did accounting counters remain consistent?”
  - inspect `findings[]` for `check=accounting`.

## Notes
- Funding/borrow is included as a contract field and defaults to `0` where source data is unavailable.
- v2 can split realized/unrealized explicitly using fill-level attribution and funding event ingestion.
