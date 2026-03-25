## ADDED Requirements

### Requirement: Shadow model loading
The `ml_feature_service` SHALL support loading candidate (shadow) models alongside active models for comparison.

#### Scenario: Shadow model configured via metadata
- **WHEN** a model's metadata has `deployment_ready: true` and `shadow: true`
- **THEN** the service loads it into `_shadow_models` dict, separate from active `_models`

#### Scenario: No shadow models configured
- **WHEN** no model metadata contains `shadow: true`
- **THEN** `_shadow_models` is empty and no shadow inference occurs

### Requirement: Shadow inference runs alongside active inference
When shadow models are loaded, the service SHALL run inference on both active and shadow models using the same feature vector.

#### Scenario: Dual prediction on each tick
- **WHEN** active and shadow models exist for the same model type (e.g., `regime`)
- **THEN** both models produce predictions from the same feature vector on each computation cycle

#### Scenario: Shadow prediction does not affect execution
- **WHEN** a shadow model produces a prediction
- **THEN** the prediction is NOT included in the `predictions` field of the published `MlFeatureEvent`; it is only logged

### Requirement: Divergence logging
Shadow vs. active prediction divergence SHALL be logged for promotion analysis.

#### Scenario: Prediction agreement logged
- **WHEN** both active and shadow models produce predictions
- **THEN** a log entry or Redis stream event records: timestamp, model_type, active_prediction, shadow_prediction, agreement (boolean), active_confidence, shadow_confidence

#### Scenario: Divergence metrics accumulated
- **WHEN** shadow inference has run for at least `shadow_soak_window` minutes (default 1440 = 24h)
- **THEN** accumulated logging metrics are available: agreement_rate, mean_confidence_delta, prediction_correlation

### Requirement: Offline shadow evaluation for promotion decisions
Promotion-ready shadow metrics SHALL be computed by an offline evaluation/report step using logged shadow events joined with realized outcomes.

#### Scenario: Offline evaluator consumes logged shadow events
- **WHEN** shadow comparison logs and realized outcomes are available for the soak window
- **THEN** an evaluator/report job computes performance metrics for active vs. shadow models over the same period

#### Scenario: Promotion recommendation emitted
- **WHEN** the offline evaluator completes a soak-window comparison
- **THEN** it emits a recommendation payload or report containing promote/reject status and supporting metrics

### Requirement: Shadow mode toggle
Shadow inference SHALL be toggleable at runtime without service restart.

#### Scenario: Enable shadow via config
- **WHEN** `ML_SHADOW_MODE=true` environment variable is set
- **THEN** shadow models are loaded and dual inference begins

#### Scenario: Disable shadow at runtime
- **WHEN** `ML_SHADOW_MODE` is changed to `false` (or the config file is updated)
- **THEN** shadow inference stops on the next computation cycle; accumulated metrics are preserved
