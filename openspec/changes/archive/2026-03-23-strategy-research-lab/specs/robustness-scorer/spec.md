## ADDED Requirements

### Requirement: Composite robustness score

The system SHALL compute a composite robustness score in [0, 1] from a `WalkForwardResult` (or partial data) using a weighted sum of normalised components:

| Component | Default weight | Normalisation |
|-----------|---------------|---------------|
| OOS Sharpe | 0.25 | `clamp(mean_oos_sharpe / 3.0, 0, 1)` |
| OOS degradation ratio | 0.20 | `1.0` if `ratio >= threshold` else `ratio / threshold` |
| Parameter stability | 0.15 | `clamp(1.0 - mean_param_cv, 0, 1)` |
| Fee stress margin | 0.15 | `clamp(min_stressed_sharpe / base_sharpe, 0, 1)` |
| Regime stability | 0.15 | `clamp(min_regime_sharpe / overall_sharpe, 0, 1)` |
| DSR pass | 0.10 | `1` if `deflated_sharpe > 0` else `0` |

#### Scenario: Perfect candidate
- **WHEN** all components are at their maximum
- **THEN** the score is 1.0

#### Scenario: Zero OOS Sharpe
- **WHEN** mean OOS Sharpe is 0 or negative
- **THEN** the OOS Sharpe component contributes 0, reducing the overall score

#### Scenario: Missing fee stress data
- **WHEN** fee stress was not run (no `WalkForwardResult` or fee data is None)
- **THEN** the fee stress component defaults to 0 and its weight is redistributed proportionally to other components

### Requirement: Configurable weights

The system SHALL accept custom weights via a dict. If custom weights do not sum to 1.0, the system SHALL normalise them.

#### Scenario: Custom weights
- **WHEN** `RobustnessScorer(weights={"oos_sharpe": 0.5, "dsr_pass": 0.5})` is constructed
- **THEN** only those two components are used, each weighted 0.5

### Requirement: Score breakdown

The system SHALL return a `ScoreBreakdown` dataclass with: `total_score` (float), `components` (dict mapping component name to `ComponentScore(raw_value, normalised, weight, weighted_contribution)`), and `recommendation` (str: one of "reject", "revise", "pass").

#### Scenario: Breakdown inspection
- **WHEN** a score is computed
- **THEN** `breakdown.components["oos_sharpe"].weighted_contribution` equals `normalised * weight`

#### Scenario: Recommendation thresholds
- **WHEN** total_score < 0.35
- **THEN** recommendation is "reject"
- **WHEN** total_score >= 0.35 and < 0.55
- **THEN** recommendation is "revise"
- **WHEN** total_score >= 0.55
- **THEN** recommendation is "pass"
