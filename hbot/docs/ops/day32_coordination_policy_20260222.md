# Day 32 - Coordination Service Audit + Policy

## Scope
- Audit `coordination-service` intent behavior.
- Enforce runtime scope/mode safety and target-base clamps via explicit policy.
- Add promotion-time policy validation.

## Implemented
- New policy config:
  - `config/coordination_policy_v1.json`
- Coordination service hardening:
  - `services/coordination_service/main.py`
  - adds:
    - explicit runtime gating (`COORD_ENABLED`, `COORD_REQUIRE_ML_ENABLED`, `ML_ENABLED`)
    - allowed instance scope enforcement
    - policy-driven target-base clamp (`min`, `max`, `neutral`, `confidence_step`)
    - policy-driven TTL (`intent_ttl_ms`)
    - health artifact writer (`reports/coordination/latest.json`)
- Compose/runtime wiring:
  - `compose/docker-compose.yml` (`coordination-service` env + healthcheck)
- Promotion checker:
  - `scripts/release/check_coordination_policy.py`
  - evidence pointer: `reports/policy/coordination_policy_latest.json`
- Promotion gate integration:
  - `scripts/release/run_promotion_gates.py` adds critical `coordination_policy_scope`
- Docs:
  - `docs/ops/coordination_service_policy_v1.md`
  - `docs/ops/runbooks.md`
  - `docs/validation/promotion_gate_contract.md`

## Outcome
- Coordination service is no longer a silent always-on behavior path.
- Scope/mode guardrails are explicit, testable, and enforced pre-promotion.

## Validation Evidence
- Coordination policy checker:
  - `reports/policy/coordination_policy_check_20260222T130722Z.json` (`status=pass`)
- Promotion gates with integrated coordination check:
  - `reports/promotion_gates/promotion_gates_20260222T130728Z.json`
  - `coordination_policy_scope=PASS`
  - overall status remains `FAIL` due to `event_store_integrity_freshness` (independent blocker)
