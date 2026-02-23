# Day 30 - Compose Mount Simplification + Drift Prevention

## Scope
- Simplify bot compose mounts from per-file controller binds to shared controller directory mounts.
- Add promotion-time drift prevention for strategy catalog and config wiring consistency.

## Implemented
- Compose mount simplification:
  - `compose/docker-compose.yml`
  - bots `bot1`..`bot4` now mount:
    - `../controllers:/home/hummingbot/controllers:ro`
    - `../controllers:/home/hummingbot/controllers/market_making:ro`
  - removed individual controller file mounts.
- Drift prevention checker:
  - `scripts/release/check_strategy_catalog_consistency.py`
  - validates approved bundles in `config/strategy_catalog/catalog_v1.json`:
    - config files exist
    - script config references expected controller file
    - `controller_name` resolves to shared `controllers/<controller_name>.py`
  - writes evidence to:
    - `reports/strategy_catalog/latest.json`
- Promotion gate integration:
  - `scripts/release/run_promotion_gates.py`
  - new critical check: `strategy_catalog_consistency`
  - preflight now requires checker script presence.

## Docs Updated
- `docs/validation/promotion_gate_contract.md`
- `docs/ops/runbooks.md`

## Outcome
- Controller rollout is now compose-scalable and shared-module based.
- Catalog/config drift is checked automatically before promotion.

## Validation Evidence
- Strategy catalog checker:
  - `reports/strategy_catalog/strategy_catalog_check_20260222T125608Z.json` (`status=pass`)
- Promotion gates (includes `strategy_catalog_consistency`):
  - `reports/promotion_gates/promotion_gates_20260222T125611Z.json`
  - current overall status remains `FAIL` due to `event_store_integrity_freshness` (separate freshness blocker)
