# ML Signal Governance Policy v1 (Day 39)

## Purpose
Define explicit promotion-time controls for ML signals, so model use is justified against a deterministic baseline and automatically retired when degraded.

## Policy Source
- `config/ml_governance_policy_v1.json`

## Governance Controls
- Baseline comparison:
  - candidate must clear minimum delta thresholds vs deterministic baseline.
- Drift controls:
  - feature PSI and confidence-drop limits must remain below configured bounds.
- Retirement controls:
  - consecutive underperformance and critical incident limits are capped.
  - breach action is `disable_ml`.

## Runtime Expectations
- If `ML_ENABLED=false`:
  - governance checker still validates policy shape and records safe baseline-only mode.
- If `ML_ENABLED=true`:
  - `reports/ml/latest.json` must exist and satisfy:
    - freshness budget (`report_max_age_min`)
    - baseline outperformance thresholds
    - drift limits
    - retirement thresholds

## Checker + Artifacts
- Checker:
  - `scripts/release/check_ml_signal_governance.py`
- Artifacts:
  - `reports/policy/ml_governance_latest.json`
  - `reports/policy/ml_governance_check_<timestamp>.json`
