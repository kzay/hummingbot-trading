## ADDED Requirements

### Requirement: Persist compact feature importance summary in model metadata
The training pipeline SHALL persist a compact, machine-readable feature-importance summary in model metadata for each trained model.

#### Scenario: Metadata includes top-k feature summary
- **WHEN** a model is trained and saved
- **THEN** its metadata includes the top-k aggregated feature importances and feature stability metrics across CV folds

#### Scenario: Metadata remains runtime-friendly
- **WHEN** fold-level importances are large
- **THEN** only the compact summary is stored in metadata, not the full fold-by-fold table

### Requirement: Write detailed feature-importance report artifact
The training pipeline SHALL write a detailed feature-importance report artifact alongside the saved model.

#### Scenario: Fold-level report written
- **WHEN** a model completes cross-validation
- **THEN** a report artifact is created containing per-fold top features, scores, and stability analysis

#### Scenario: Report is linked from metadata
- **WHEN** the detailed feature-importance report is written
- **THEN** the model metadata includes the report path or artifact reference

### Requirement: Feature stability metric is computed consistently
Feature stability SHALL be defined as the fraction of folds in which a feature appears in the top-k ranked features.

#### Scenario: Stable feature identified
- **WHEN** a feature appears in the top-10 features for 4 out of 5 folds
- **THEN** its stability score is recorded as `0.8`

#### Scenario: Unstable feature identified
- **WHEN** a feature appears in the top-10 features for 1 out of 5 folds
- **THEN** its stability score is recorded as `0.2`
