# Documentation Change Log

## Purpose
Track meaningful documentation updates and ownership changes.

## Entries

### 2026-02-19 (paper trade standardization)
- Diagnosed and resolved `bitget is not ready` issue (empty spot account blocked `account_balance` readiness).
- Discovered `paper_trade_exchanges` config only registers `bitget_paper_trade` as available -- scripts must use the suffix explicitly.
- Discovered V2 controller framework's `MarketDataProvider` cannot resolve `bitget_paper_trade` module; V2 controllers must use `connector_name: bitget` with `paper_mode: true`.
- Added `id` field to all controller YAMLs (was defaulting to `None`, causing `nan` in status).
- Created bot3 as dedicated paper trade smoke-test instance (`--profile test`).
- Updated README sections 14.2, 14.3, 14.4, 14.6, project structure tree, and Common Issues.
- Updated strategy spec, deployment profiles, runbooks, and validation plan.

### 2026-02-19
- Created comprehensive docs hub and topic-folder structure.
- Added infra, techspec, architecture, financial, strategy, risk, ops, validation, and governance baseline docs.
- Added root docs index and linked navigation.

## Update Rule
- Add one entry per merged documentation change set.
- Reference PR/commit ID when available.

## Owner
- Engineering Documentation Owner

