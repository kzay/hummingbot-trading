## ADDED Requirements

### Requirement: Data assembly for training
The research pipeline SHALL assemble training datasets by loading all available data for a given `(exchange, pair)` from the DataCatalog, running the feature pipeline and label generator, and joining features + labels on `timestamp_ms` into a single Parquet file.

#### Scenario: Assemble BTC-USDT dataset
- **WHEN** `assemble_dataset(exchange="bitget", pair="BTC-USDT")` is called
- **THEN** all available data types are loaded from the catalog, features and labels are computed, and a single `{pair}_features_labels.parquet` file is saved to the output directory

#### Scenario: Missing optional data types
- **WHEN** LS ratio data is not in the catalog for the requested pair
- **THEN** the dataset is assembled with NaN for LS-derived features; no error is raised

### Requirement: Walk-forward cross-validation for ML models
The research pipeline SHALL implement temporal walk-forward CV:
- Split data into N windows (default 5) using expanding or rolling splits
- For each window: train on the train slice, evaluate on the test slice
- No random shuffling — temporal order is preserved
- Report per-window OOS metrics: accuracy (classification) or R-squared (regression), plus feature importance top-20

#### Scenario: 5-window walk-forward CV
- **WHEN** walk-forward CV is run with 5 windows on a 12-month dataset
- **THEN** 5 train/test splits are created with no temporal overlap, and per-window OOS metrics are reported

#### Scenario: No data leakage
- **WHEN** walk-forward CV creates train/test splits
- **THEN** every test row has a `timestamp_ms` strictly greater than every train row in the same window

### Requirement: Baseline comparison
The research pipeline SHALL compute the rule-based `RegimeDetector` baseline performance on the same labels used for ML training. The baseline uses the same forward-outcome labels and the same evaluation windows. The ML model MUST demonstrate improvement over this baseline to pass the deployment gate.

#### Scenario: Baseline vs ML comparison
- **WHEN** a regime classifier is trained and evaluated
- **THEN** the report includes both ML OOS accuracy and rule-based baseline accuracy on the same test windows

#### Scenario: ML does not beat baseline
- **WHEN** the ML model's mean OOS accuracy is lower than the baseline
- **THEN** the model metadata is flagged as `deployment_ready: false` with a warning

### Requirement: Per-pair model training
Models SHALL be trained separately for each `(exchange, pair)` combination. The training script SHALL accept `--exchange` and `--pair` arguments and produce model artifacts under `data/ml/models/{exchange}/{pair}/`.

#### Scenario: Train BTC-USDT regime model
- **WHEN** `python -m controllers.ml.research --exchange bitget --pair BTC-USDT --model-type regime` is run
- **THEN** a trained model is saved to `data/ml/models/bitget/BTC-USDT/regime_v1.joblib` with metadata

#### Scenario: Train ETH-USDT independently
- **WHEN** training is run for ETH-USDT
- **THEN** the output model is independent of BTC-USDT and stored under `data/ml/models/bitget/ETH-USDT/`

### Requirement: Model registry with metadata
Each trained model artifact SHALL be accompanied by a JSON metadata file containing:
- `exchange`, `pair` — which market
- `model_type` — regime, direction, sizing
- `feature_columns` — ordered list of feature names used during training
- `label_column` — the prediction target
- `walk_forward_results` — per-window OOS metrics
- `mean_oos_metric` — mean OOS accuracy or R-squared
- `baseline_metric` — rule-based baseline performance
- `deployment_ready` — boolean gate
- `training_date`, `data_start`, `data_end` — provenance

#### Scenario: Metadata accompanies model
- **WHEN** a model is trained and saved
- **THEN** a `{model_type}_v1_metadata.json` file exists alongside the `.joblib` file with all required fields

### Requirement: Deployment gates
A model SHALL be flagged `deployment_ready: true` only when all of the following are met:
- Mean OOS accuracy >= 55% for classification (or mean OOS R-squared > 0 for regression)
- OOS metric improvement >= 0.05 over rule-based baseline (accuracy) or OOS Sharpe improvement >= 0.3 (from comparative backtest)
- Feature importance stability: top-10 features appear in at least 60% of walk-forward windows

#### Scenario: Model passes all gates
- **WHEN** a model achieves OOS accuracy 62%, baseline is 48%, and top-10 features are stable across 4/5 windows
- **THEN** `deployment_ready` is `true`

#### Scenario: Model fails accuracy gate
- **WHEN** a model achieves OOS accuracy 52%
- **THEN** `deployment_ready` is `false` with a warning in metadata

### Requirement: Model types — staged
The research pipeline SHALL support three model types, to be implemented in stages:
- Stage 1: `regime` — LightGBM classifier predicting forward volatility bucket (WHEN to trade)
- Stage 2: `direction` — LightGBM classifier predicting forward return sign/bucket (WHERE price goes)
- Stage 3: `sizing` — LightGBM regressor predicting tradability score (HOW MUCH to risk)

#### Scenario: Stage 1 training
- **WHEN** `--model-type regime` is specified
- **THEN** the model is trained to predict `fwd_vol_bucket_15m` using the feature pipeline output
