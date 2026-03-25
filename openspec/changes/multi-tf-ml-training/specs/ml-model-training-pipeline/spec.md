## ADDED Requirements

### Requirement: LightGBM dependency is available

The ML training environment SHALL have `lightgbm` installed so that `research.py`, `train_regime_classifier.py`, and `train_adverse_classifier.py` can use LGBMClassifier/LGBMRegressor.

#### Scenario: LightGBM importable

- **WHEN** `import lightgbm` is executed in the training environment
- **THEN** the import succeeds without ImportError

### Requirement: Research pipeline produces regime model

`research.py --model-type regime` SHALL produce a trained LightGBM classifier predicting `fwd_vol_bucket_15m` (4 classes: low, normal, elevated, extreme) using walk-forward CV on BTC-USDT 1-year historical data from `data/historical`.

#### Scenario: Regime model trained and saved

- **WHEN** `python -m controllers.ml.research --exchange bitget --pair BTC-USDT --model-type regime --catalog-dir data/historical --output data/ml/models --windows 5` is executed
- **THEN** a model file at `data/ml/models/bitget/BTC-USDT/regime_v1.joblib` and metadata JSON are created

#### Scenario: Deployment gates evaluated

- **WHEN** training completes
- **THEN** metadata includes `deployment_ready` (bool), `gate_results` (list), `mean_oos_metric`, and `baseline_metric`

### Requirement: Research pipeline produces sizing model

`research.py --model-type sizing` SHALL produce a trained LightGBM regressor predicting `tradability_long_15m` using walk-forward CV.

#### Scenario: Sizing model trained and saved

- **WHEN** `python -m controllers.ml.research --exchange bitget --pair BTC-USDT --model-type sizing` is executed
- **THEN** a model file at `data/ml/models/bitget/BTC-USDT/sizing_v1.joblib` and metadata JSON are created

### Requirement: Research pipeline produces direction model for research

`research.py --model-type direction` SHALL produce a trained LightGBM classifier predicting `fwd_return_sign_15m`. This model is for research evaluation only; its results SHALL be analyzed with extra scrutiny per ml-trading-guardrails.

#### Scenario: Direction model trained with skepticism flag

- **WHEN** direction model training completes
- **THEN** metadata is saved and can be manually reviewed for feature stability and overfitting indicators

### Requirement: ROAD-10 regime classifier trainable from combined bot logs

`build_regime_dataset.py` SHALL support a `--roots` argument accepting multiple bot log directories. The script SHALL concatenate minute.csv rows from all specified bots, verify regime label consistency, and produce a combined dataset.

#### Scenario: Combined dataset from 3 bots

- **WHEN** `--roots data/bot5/logs/epp_v24/bot5_a,data/bot6/logs/epp_v24/bot6_a,data/bot7/logs/epp_v24/bot7_a` is provided
- **THEN** minute.csv rows from all 3 bots are concatenated, deduplicated by timestamp, and saved as a single parquet file

#### Scenario: Gate check on combined dataset

- **WHEN** the combined dataset has >= 10,000 rows
- **THEN** the gate check passes and training proceeds

### Requirement: ROAD-11 adverse fill classifier trainable from bot with sufficient fills

`build_adverse_fill_dataset.py` SHALL support loading fills from legacy fill files (fills.legacy_*.csv) in addition to the current fills.csv when `--include-legacy` is specified.

#### Scenario: Legacy fills included

- **WHEN** `--include-legacy` is specified and bot5 has `fills.csv` (3 rows) and `fills.legacy_*.csv` (10,663 rows)
- **THEN** all 10,666 fills are included in the dataset

#### Scenario: Gate check on fills dataset

- **WHEN** the dataset has >= 5,000 rows
- **THEN** the gate check passes and training proceeds
