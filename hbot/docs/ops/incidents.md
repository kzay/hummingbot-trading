# Incident Playbook

## Purpose
Provide triage and response procedures for common failure scenarios.

## Severity Levels
- Sev-1: trading safety at risk.
- Sev-2: execution degraded but controlled.
- Sev-3: observability/docs/tooling issue.

## Common Incidents
- Connector not ready loops.
- Intent rejection spikes.
- Redis outage or stream lag.
- Model loader/inference failures.

## Triage Flow
1. Confirm scope (single bot vs system-wide).
2. Check `errors.log`, service logs, dead-letter reasons.
3. Determine safe mode:
   - soft pause
   - hard stop if unsafe
4. Mitigate and verify stability.

## Postmortem Template
- timeline
- root cause
- impact
- corrective action
- prevention tasks

## Owner
- Operations + Engineering
- Last-updated: 2026-02-19

