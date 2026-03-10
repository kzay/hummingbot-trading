# Shared Market History Runbook

## Purpose
Operate the shared market-history rollout safely across backfill, runtime seeding, UI read-path migration, and retention/capacity monitoring.

## Scope
- Canonical store: `market_bar_v2`
- Writer: `services/ops_db_writer/main.py`
- Runtime reader/seeding: `controllers/epp_v2_4.py`
- Read-model consumer: `services/realtime_ui_api/main.py`
- Telemetry remains separate: `minute.csv`

## Main Controls
- `HB_HISTORY_PROVIDER_ENABLED`: enables provider-backed read paths.
- `HB_HISTORY_SEED_ENABLED`: enables startup `MidPriceBuffer` seeding.
- `HB_HISTORY_SOURCE_PRIORITY`: runtime seed source order, usually `quote_mid,exchange_ohlcv`.
- `HB_HISTORY_ALLOW_FALLBACK`: when `true`, runtime may try later sources in `HB_HISTORY_SOURCE_PRIORITY`.
- `HB_HISTORY_RUNTIME_MIN_STATUS`: minimum accepted seed status, `fresh` or `degraded`.
- `HB_HISTORY_RUNTIME_MIN_BARS`: minimum bar count required for accepting a seed result.
- `HB_HISTORY_MAX_ACCEPTABLE_GAP_S`: max accepted gap during startup seeding.
- `HB_HISTORY_UI_READ_MODE`: `legacy`, `shadow`, or `shared`.
- `OPS_DB_MARKET_BAR_V2_RETENTION_MAX_BARS`: rolling per-key cap.
- `OPS_DB_MARKET_BAR_V2_MAX_DISTINCT_KEYS`: distinct-key budget for capacity monitoring.
- `OPS_DB_MARKET_BAR_V2_STORAGE_BUDGET_MB`: storage budget used by the capacity report.

## Evidence Files
- Backfill parity: `reports/ops/market_bar_v2_backfill_latest.json`
- Capacity/retention: `reports/ops/market_bar_v2_capacity_latest.json`
- Promotion gates: `reports/promotion_gates/latest.json`
- Runtime seed telemetry: latest `data/<bot>/logs/epp_v24/<variant>/minute.csv`

## Standard Sequence
1. Backfill legacy bars into `market_bar_v2`:
   - `python scripts/ops/backfill_market_bar_v2.py --dry-run`
   - `python scripts/ops/backfill_market_bar_v2.py`
2. Generate retention/capacity evidence:
   - `python scripts/ops/report_market_bar_v2_capacity.py`
3. Enable UI shadow mode first:
   - `HB_HISTORY_PROVIDER_ENABLED=true`
   - `HB_HISTORY_UI_READ_MODE=shadow`
4. After shadow parity is clean, enable runtime seeding on the canary bot:
   - `HB_HISTORY_SEED_ENABLED=true`
5. Run promotion gates:
   - `python scripts/release/run_promotion_gates.py --ci`

## Canary Order
1. `bot1` with seed enabled, UI still `shadow`
2. `bot7` after `bot1` seed results stay healthy
3. Remaining paper bots
4. UI `shared` mode only after shadow parity remains healthy

## Backfill Acceptance
- `status=pass`
- `missing_count_after=0`
- `sample_mismatch_count=0`
- Report freshness within the promotion gate max-age budget

## Capacity Acceptance
- No `over_cap_keys`
- `distinct_keys <= OPS_DB_MARKET_BAR_V2_MAX_DISTINCT_KEYS`
- `status=pass` or consciously accepted `warn`
- Review `projected_capacity_total_mb` before increasing key count or retention

## Runtime Seed Acceptance
- Latest `minute.csv` rows show:
  - `history_seed_status` in `fresh`, `degraded`, or `stale` only when policy allows it
  - `history_seed_bars >= HB_HISTORY_RUNTIME_MIN_BARS`
  - `history_seed_source` matches expected source priority behavior
- Promotion gate fails when:
  - shared-history reads are enabled but backfill evidence is stale/failing
  - runtime seeding is enabled and latest seed evidence is `disabled`, `gapped`, or `empty`

## Common Failure Meanings
- `history_seed_status=disabled`:
  - seeding is off or provider unavailable
- `history_seed_status=gapped` or `empty`:
  - do not trust seeded indicators; keep rollout blocked
- backfill gate fail:
  - rerun backfill dry-run first, confirm schema/writer parity, then rerun full backfill
- capacity report `warn`:
  - near cap or over storage budget; review retention before expanding rollout

## Rollback
1. Disable runtime seeding:
   - `HB_HISTORY_SEED_ENABLED=false`
2. Return UI to legacy:
   - `HB_HISTORY_UI_READ_MODE=legacy`
   - optionally `HB_HISTORY_PROVIDER_ENABLED=false`
3. Re-run promotion gates to confirm the rollback state is healthy.
4. Leave `market_bar_v2` in place; rollback is configuration-only.

## Notes
- `minute.csv` is still operator evidence, not canonical market history.
- Runtime seed fallback is policy-driven, not hard-coded; check env values before diagnosing source choice.
- `market_bar_v2` is additive. Do not delete legacy tables during rollout.
