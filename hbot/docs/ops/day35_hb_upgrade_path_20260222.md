# Day 35 - HB Version Upgrade Path (2026-02-22)

## Objective
- Complete the remaining Day 35 scope by defining a safe Hummingbot image upgrade path.
- Provide preflight evidence before any runtime upgrade attempt.

## Implemented
- New dry-run checker:
  - `scripts/release/check_hb_upgrade_readiness.py`
- What it validates:
  - target image differs from current default in compose anchor
  - compose config renders successfully with `HUMMINGBOT_IMAGE=<target>` override
- Output artifacts:
  - `reports/upgrade/latest.json`
  - `reports/upgrade/hb_upgrade_readiness_<timestamp>.json`

## Validation
- Command executed:
  - `python scripts/release/check_hb_upgrade_readiness.py --target-image hummingbot/hummingbot:version-2.12.1`
- Evidence:
  - `reports/upgrade/latest.json`

## Rollout Contract
- Phase A (test profile):
  - Recreate `bot3` + `bot4` with target image.
- Phase B (gates):
  - Run promotion gates in CI mode and verify no new critical failures.
- Phase C (live safety):
  - Recreate `bot1` in no-trade-safe mode first, then observe reconciliation/parity/risk.
- Rollback:
  - Restore previous image tag and recreate affected bots.

## Outcome
- Day 35 scope is now fully covered:
  - market-data freshness gate delivered,
  - HB image upgrade path and preflight evidence delivered.
