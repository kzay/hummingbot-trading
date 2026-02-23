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

- 2026-02-22T00:20:11.428657+00:00 - strict gate status transition to FAIL; critical_failures=['regression_backtest_harness', 'day2_event_store_gate']; evidence=F:\Environement\git-repo\hummingbot_custo\hbot\reports\promotion_gates\strict_cycle_latest.json
- 2026-02-22T00:46:55.371238+00:00 - strict promotion cycle failed; critical_failures=['day2_event_store_gate']; evidence=F:\Environement\git-repo\hummingbot_custo\hbot\reports\promotion_gates\latest.json
- 2026-02-22T00:47:26.869905+00:00 - strict promotion cycle failed; critical_failures=['day2_event_store_gate']; evidence=F:\Environement\git-repo\hummingbot_custo\hbot\reports\promotion_gates\latest.json
- 2026-02-22T00:49:14.661789+00:00 - strict promotion cycle failed; critical_failures=['day2_event_store_gate']; evidence=F:\Environement\git-repo\hummingbot_custo\hbot\reports\promotion_gates\latest.json
- 2026-02-22T02:08:17.691804+00:00 - bus recovery drill failed delta tolerance check (`delta_since_baseline_within_tolerance=false`, max_delta_observed=22478) before and after Redis restart; evidence=F:\Environement\git-repo\hummingbot_custo\hbot\reports\bus_recovery\bus_recovery_post_restart_20260222T020817Z.json
