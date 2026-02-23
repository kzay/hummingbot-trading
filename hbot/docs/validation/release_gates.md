# Release Gates

## Purpose
Specify mandatory pass/fail criteria before promotion.

## Gate 1: Build and Static
- Python modules compile.
- Compose config validates.
- Lint checks clear for changed files.

## Gate 2: Functional
- Contract tests pass.
- Risk gating tests pass.
- Intent idempotency/expiry handling verified.
- Controller preflight passes for all target connectors.

## Gate 3: Operational
- External services restart independently.
- HB local authority remains effective under degraded bus.
- No uncontrolled order placement in no-trade variants.

## Gate 4: Financial Safety
- KPI thresholds remain within configured limits.
- No unresolved critical incidents in validation window.

## Gate 5: Environment Matrix
- Binance demo futures smoke (`v2_epp_v2_4_binance_demo_smoke.yml`) passes:
  - Preflight pass
  - Connector transitions to ready
  - Controller ticks continuously for soak window
- Bitget paper smoke (`v2_epp_v2_4_bitget_paper_smoke.yml`) passes:
  - Preflight pass
  - Paper connector cycles orders/fills
  - No unresolved fee profile or connector mapping errors

## Hardening Checklist
- No runtime monkey-patching of Hummingbot internals.
- Exchange profiles resolved from `config/exchange_profiles.json`.
- Fee profiles cover all active connectors in `config/fee_profiles.json`.
- Compose config has no ad-hoc connector source file overrides.
- Runbook includes environment switch, preflight diagnostics, and smoke matrix commands.

## Acceptance Sign-off
- Strategy owner: [ ]
- Risk owner: [ ]
- Ops owner: [ ]
- Release manager: [ ]

## Promotion Decision
- Requires sign-off from Strategy + Risk + Ops owners.

## Owner
- Release Management
- Last-updated: 2026-02-19

