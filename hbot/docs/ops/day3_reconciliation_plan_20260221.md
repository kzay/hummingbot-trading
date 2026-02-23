# Day 3 Reconciliation Plan - 2026-02-21

## Objective
Kick off Day 3 with a practical reconciliation MVP that can run unattended and produce drift evidence for operations.

## Phase Scope
- Build `services/reconciliation_service/` scaffold.
- Implement periodic reconciliation jobs for:
  - balances
  - positions/inventory
  - fill/order parity
- Classify drift severities (`warning`, `critical`).
- Add synthetic drift test path to validate alert/report behavior.

## Execution Steps
1. Implement reconciliation service core loop and report writers.
2. Wire service into compose under `external` profile.
3. Run one normal cycle and capture report.
4. Run one synthetic-drift cycle and verify critical signal.
5. Update checklist/progress docs with evidence and status.

## Acceptance Criteria (Kickoff)
- Reconciliation service executes and writes report artifact.
- Drift severity classification exists in output.
- Synthetic drift creates at least one `critical` severity item.

## Risks
- No direct exchange-account reconciliation yet (MVP uses local artifacts and event-store feed).
- Fill parity may be partial until `order_filled` events are fully produced by upstream adapters.

## Rollback
- Stop/remove `reconciliation-service` from compose runtime.
- Keep existing bots/monitoring untouched.
- Preserve generated reports for post-mortem.
