## ADDED Requirements

### Requirement: Purged walk-forward cross-validation
The training pipeline SHALL implement purged walk-forward CV that adds embargo gaps between train and test windows to prevent lookahead contamination.

#### Scenario: Default embargo size
- **WHEN** `purged_walk_forward_cv` is called without explicit embargo
- **THEN** the embargo gap is `2 × max_label_horizon` bars (e.g., 120 bars for 60-min horizon on 1m data)

#### Scenario: Custom embargo size
- **WHEN** `purged_walk_forward_cv` is called with `embargo_bars=90`
- **THEN** exactly 90 bars are excluded between each train-end and test-start

#### Scenario: Purging overlapping samples
- **WHEN** a training sample's label window overlaps the test period start
- **THEN** that sample is removed from the training set for that fold

#### Scenario: Fold structure preserved
- **WHEN** `purged_walk_forward_cv` is called with `n_windows=5`
- **THEN** exactly 5 folds are produced, each with expanding train and fixed-size test windows, with embargo gaps between them

### Requirement: Embargo reduces but does not eliminate folds
The CV function SHALL NOT reduce the number of folds below the requested count due to embargo gaps.

#### Scenario: Small dataset with large embargo
- **WHEN** the dataset has fewer samples than required for all folds plus embargo gaps
- **THEN** the function raises a `ValueError` with a clear message about insufficient data

### Requirement: Purged CV is the default for all model types
All model types (regime, direction, sizing, adverse) SHALL use purged walk-forward CV as the default validation strategy.

#### Scenario: Regime model uses purged CV
- **WHEN** `train_and_evaluate(model_type='regime')` is called
- **THEN** purged walk-forward CV is used with embargo based on the regime label horizon

#### Scenario: Adverse model uses purged CV
- **WHEN** `train_and_evaluate(model_type='adverse')` is called
- **THEN** purged walk-forward CV is used with embargo based on the adverse label horizon

### Requirement: CV metrics include fold-level detail
Each CV fold SHALL report individual metrics alongside the aggregated summary.

#### Scenario: Fold-level accuracy reported
- **WHEN** purged walk-forward CV completes
- **THEN** results include per-fold accuracy/R², train size, test size, embargo size, and number of purged samples for each fold
