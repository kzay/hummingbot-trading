# Migration Spike - 2026-02-22

## Scope (Timeboxed)
Measure migration effort away from current execution engine using a paper-only execution-adapter spike.

## Required Feature Set Evaluated
- Connector integration surface (paper/stub for venue abstraction)
- Order lifecycle (`created` -> `filled`)
- Risk veto before placement
- Audit trail per decision/action

## Prototype Implemented
- Script: `scripts/spikes/migration_execution_adapter_spike.py`
- Artifact outputs:
  - `reports/migration_spike/latest.json`
  - `reports/migration_spike/latest_audit.jsonl`
  - timestamped JSON/JSONL artifacts

## Measured Results
- Spike status: `pass`
- Evidence:
  - `reports/migration_spike/execution_adapter_spike_20260222T012304Z.json`
- Observed behavior:
  - allowed intents completed order lifecycle
  - oversized intent blocked by risk veto
  - all actions emitted audit events

## Cost Estimate (Measured + Bounded)
- **Adapter MVP (paper only):** 1-2 days (achieved in spike).
- **Parity with current Option 4 controls in live path:** 2-4 weeks.
  - reasons:
    - re-implement connector-specific lifecycle and edge cases
    - re-wire promotion gates and evidence contracts
    - re-validate reconciliation/parity/portfolio-risk integration
- **Production confidence hardening:** +2-4 weeks.
  - game days, incident taxonomy, rollback drills, operator training

## Risks
- Reliability reset risk: existing validated controls would need re-qualification in new stack.
- Connector behavior gap risk for Bitget edge cases.
- Migration can delay Day 15+ operational hardening and live micro-cap evidence gathering.

## Recommendation
- **Decision: NO-GO for deeper migration investment now.**
- Continue Option 4 execution hardening through current roadmap.
- Re-open migration track only if one of these triggers occurs:
  1. repeated connector/runtime instability that cannot be mitigated within Option 4 controls,
  2. inability to meet live Bitget operational objectives in Day 15-20,
  3. sustained operator overhead from Hummingbot-specific constraints.

## Next Decision Checkpoint
- Reassess migration only after:
  - Day 15 live micro-cap evidence,
  - Day 16 accounting integrity checks,
  - Day 17/18 gate and bus resilience milestones.
