# Day 39 - ML Signal Governance (2026-02-22)

## Objective
- Add an enforceable ML governance policy with baseline comparison, drift detection, and retirement criteria.
- Make governance a critical promotion gate.

## Implemented
- New policy:
  - `config/ml_governance_policy_v1.json`
- New checker:
  - `scripts/release/check_ml_signal_governance.py`
- Gate integration:
  - `scripts/release/run_promotion_gates.py`
  - new critical gate: `ml_signal_governance`
- Policy/runbook documentation:
  - `docs/ops/ml_signal_governance_policy_v1.md`

## Contract
- `ML_ENABLED=false`:
  - pass with policy validation + safe baseline-only mode.
- `ML_ENABLED=true`:
  - requires fresh `reports/ml/latest.json`
  - enforces:
    - baseline outperformance thresholds
    - drift limits
    - retirement thresholds

## Evidence
- `reports/policy/ml_governance_latest.json`
- `reports/promotion_gates/latest.json` includes `ml_signal_governance`

## Outcome
- Day 39 governance controls are fail-closed and promotion-enforced, while remaining operationally safe when ML is intentionally disabled.
