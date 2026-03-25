## ADDED Requirements

### Requirement: Optuna-based hyperparameter tuning
The training pipeline SHALL support automated hyperparameter tuning via Optuna with TPE sampler, integrated into `train_and_evaluate()`.

#### Scenario: Tuning enabled with default budget
- **WHEN** `train_and_evaluate(tune=True)` is called without specifying `n_trials`
- **THEN** Optuna runs 50 trials using TPE sampler, optimizing the mean OOS metric from purged walk-forward CV

#### Scenario: Custom trial budget
- **WHEN** `train_and_evaluate(tune=True, n_trials=200)` is called
- **THEN** Optuna runs exactly 200 trials

#### Scenario: Tuning disabled by default
- **WHEN** `train_and_evaluate()` is called without `tune` parameter
- **THEN** training uses fixed default hyperparameters (current behavior preserved)

### Requirement: Search space per model type
Each model type SHALL have a defined hyperparameter search space appropriate to its algorithm.

#### Scenario: LightGBM search space
- **WHEN** tuning a LightGBM model (regime, direction, sizing)
- **THEN** the search space includes `n_estimators`, `max_depth`, `learning_rate`, `num_leaves`, `min_child_samples`, `subsample`, `colsample_bytree`, `reg_alpha`, `reg_lambda`

#### Scenario: Adverse-fill model search space
- **WHEN** tuning the adverse-fill model
- **THEN** the search space is adapted to the adverse classifier's algorithm (GradientBoosting or LightGBM)

### Requirement: Best hyperparameters persisted in model metadata
The selected hyperparameters SHALL be saved in the model's metadata JSON alongside the existing fields.

#### Scenario: Metadata includes tuning results
- **WHEN** a model is trained with `tune=True`
- **THEN** the metadata JSON includes `tuning.best_params`, `tuning.n_trials`, `tuning.best_score`, and `tuning.search_space`

#### Scenario: No tuning metadata when disabled
- **WHEN** a model is trained with `tune=False`
- **THEN** the metadata JSON does not include a `tuning` key

### Requirement: Optuna study reproducibility
Tuning runs SHALL be reproducible given the same data and random seed.

#### Scenario: Same seed produces same results
- **WHEN** two tuning runs use the same dataset and `seed=42`
- **THEN** both runs produce identical best hyperparameters

### Requirement: Optuna is an optional dependency
The `optuna` package SHALL only be required when tuning is enabled.

#### Scenario: Import error handled gracefully
- **WHEN** `tune=True` is passed but `optuna` is not installed
- **THEN** a clear `ImportError` is raised: "Install optuna for hyperparameter tuning: pip install optuna"
