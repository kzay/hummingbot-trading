## ADDED Requirements

### Requirement: Single training entry point for all model types
`research.train_and_evaluate()` SHALL be the canonical entry point for training all model types: `regime`, `direction`, `sizing`, and `adverse`.

#### Scenario: Training regime model
- **WHEN** `train_and_evaluate(model_type='regime', ...)` is called
- **THEN** a regime classifier is trained using the same pipeline as direction/sizing, with regime-specific labels and metrics

#### Scenario: Training adverse model
- **WHEN** `train_and_evaluate(model_type='adverse', ...)` is called
- **THEN** an adverse-fill classifier is trained using fills+minute data, with adverse-specific features and precision@recall metrics

### Requirement: Registry-compatible output for all models
All trained models SHALL be saved via `model_registry.save_model()` producing the standard `{exchange}/{pair}/{model_type}_v1.joblib` + metadata layout.

#### Scenario: Adverse model saved to registry
- **WHEN** an adverse-fill model completes training
- **THEN** it is saved at `{base_dir}/{exchange}/{pair}/adverse_v1.joblib` with `adverse_v1_metadata.json`

#### Scenario: Standalone scripts delegate to research
- **WHEN** `scripts/ml/train_regime_classifier.py` is executed
- **THEN** it calls `research.train_and_evaluate(model_type='regime', ...)` and produces registry-compatible output

### Requirement: Consistent label mapping
All model types SHALL use label names that match the runtime consumer expectations.

#### Scenario: Regime labels match bridge mapping
- **WHEN** a regime model is trained
- **THEN** its class labels match the keys in `REGIME_VOL_BUCKET_MAP` used by `signal_consumer.py` (integer classes 0-3 mapping to neutral_low_vol, neutral_high_vol, high_vol_shock)

#### Scenario: Label mapping documented in metadata
- **WHEN** any model is saved
- **THEN** metadata includes `label_mapping` dict showing class index → human-readable name

### Requirement: Pluggable feature extractors per model type
Each model type SHALL specify its feature extraction function, allowing adverse-fill to use `get_custom_info()`-derived features while other types use `compute_features()`.

#### Scenario: Regime/direction/sizing use compute_features
- **WHEN** `train_and_evaluate(model_type='regime')` assembles data
- **THEN** `compute_features()` from `feature_pipeline.py` is used

#### Scenario: Adverse uses custom feature extractor
- **WHEN** `train_and_evaluate(model_type='adverse')` assembles data
- **THEN** the adverse-specific feature extractor (spread, edge, drift, regime one-hots) is used

### Requirement: Deployment gates applied uniformly
All model types SHALL pass through `check_deployment_gates()` with type-specific thresholds before being marked `deployment_ready`.

#### Scenario: Regime model gate check
- **WHEN** a regime model completes CV
- **THEN** it must meet: mean accuracy ≥ 0.55, beat majority baseline by ≥ 0.05, feature stability ≥ 60%

#### Scenario: Adverse model gate check
- **WHEN** an adverse model completes CV
- **THEN** it must meet: precision @ recall ≥ 0.70 is ≥ 0.60, mean precision ≥ 0.55

#### Scenario: Failed gate marks model not ready
- **WHEN** any model fails its deployment gate
- **THEN** metadata `deployment_ready` is set to `false` and `gate_failures` lists the specific failures
