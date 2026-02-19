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

## Gate 3: Operational
- External services restart independently.
- HB local authority remains effective under degraded bus.
- No uncontrolled order placement in no-trade variants.

## Gate 4: Financial Safety
- KPI thresholds remain within configured limits.
- No unresolved critical incidents in validation window.

## Promotion Decision
- Requires sign-off from Strategy + Risk + Ops owners.

## Owner
- Release Management
- Last-updated: 2026-02-19

