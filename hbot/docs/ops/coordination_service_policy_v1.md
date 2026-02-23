# Coordination Service Policy v1 (Day 32)

## Purpose
Define when `coordination-service` is allowed to emit execution intents and enforce safe bounds for ML-driven inventory targeting.

## Scope
- Service: `services/coordination_service/main.py`
- Policy source: `config/coordination_policy_v1.json`
- Promotion checker: `scripts/release/check_coordination_policy.py`

## Allowed Runtime Modes
- Default mode is disabled:
  - `COORD_ENABLED=false` unless explicitly enabled by operator.
- ML-gated mode:
  - if `COORD_REQUIRE_ML_ENABLED=true`, service remains suspended unless `ML_ENABLED=true`.
- Instance scope:
  - only instances listed in `coordination_policy_v1.json:allowed_instances` are permitted.
  - current v1 scope: `bot1`.

## Intent Safety Contract
- Approved decision + model metadata:
  - action: `set_target_base_pct`
  - target is clamped to policy bounds (`min`..`max`).
- Approved decision without model metadata:
  - action: `resume`
- Rejected decision:
  - action: `soft_pause`
- Intent TTL is policy-driven (`conflict_contract.intent_ttl_ms`).

## Conflict/Precedence Rules
- `OpsGuard` and `portfolio-risk-service` controls have precedence over coordination intents.
- Coordination only suggests target-base/resume/soft-pause; it does not override kill-switch outcomes.

## Health and Observability
- Health output: `reports/coordination/latest.json`
- Compose healthcheck validates freshness of coordination health artifact.

## Promotion Gate Requirement
- `run_promotion_gates.py` includes critical check `coordination_policy_scope`.
- Gate fails if:
  - coordination policy file is malformed,
  - allowed instances violate multi-bot policy,
  - compose coordination env contract is missing required safety toggles.
