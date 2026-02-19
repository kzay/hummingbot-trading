# Kill Switches

## Purpose
Catalog kill-switch triggers and expected behavior.

## Types
- **Local soft pause**:
  - net-edge gate failure
  - no-trade variant
  - external bus outage policy trigger
- **Local hard stop**:
  - explicit kill-switch intent
  - severe repeated failures
- **External policy stop**:
  - risk decision produces `soft_pause`/`kill` intent

## Trigger Sources
- Controller ops guard state machine.
- Risk service decisioning.
- Operator/manual commands.

## Response Matrix
- Soft pause: no new entries; manage existing state safely.
- Hard stop: stop controller execution path and escalate incident.

## Auditing
- Every reject/apply path should emit audit metadata with reason and correlation ID.

## Owner
- Risk/Ops
- Last-updated: 2026-02-19

