## 1. Purged Walk-Forward CV

- [x] 1.1 Implement `purged_walk_forward_cv()` function in `controllers/ml/research.py` with embargo gap and sample purging logic
- [x] 1.2 Add `embargo_bars` parameter (default: `2 × max_label_horizon`) and `purge=True` flag to the CV function
- [x] 1.3 Add per-fold detail reporting (train size, test size, embargo size, purged count, per-fold metric)
- [x] 1.4 Replace the existing `walk_forward_cv()` call in `train_and_evaluate()` with `purged_walk_forward_cv()`
- [x] 1.5 Write unit tests: fold structure, embargo gap correctness, purging behavior, insufficient data ValueError
- [x] 1.6 Validate that existing deployment gates still pass with purged CV on current datasets

## 2. Multi-Timeframe Features

- [x] 2.1 Update default `ML_TIMEFRAMES` in `ml_feature_service/main.py` from `5m,15m,1h` to `1m,5m,15m,1h`
- [x] 2.2 Add `4h` support in `compute_price_features()` when present in the timeframe list
- [x] 2.3 Implement cross-TF confluence features in `feature_pipeline.py`: `trend_alignment_{tf1}_{tf2}`, `vol_regime_agreement`, `wr_divergence_{tf1}_{tf2}`
- [x] 2.4 Update `PairFeatureState.max_bars` to dynamically adjust based on highest configured TF (120 for 1h, 480 for 4h)
- [x] 2.5 Ensure `MlFeatureEvent` payload includes all multi-TF feature columns
- [x] 2.6 Write unit tests for cross-TF feature computation and dynamic window sizing
- [x] 2.7 Run feature pipeline on historical data to verify no NaN explosion from TF misalignment

## 3. Live Feature Activation (Microstructure + Basis)

- [x] 3.1 Add `hb.market_trade.v1` Redis stream consumer to `ml_feature_service/main.py`
- [x] 3.2 Extend `PairFeatureState` to maintain a rolling trade buffer fed from the trades stream
- [x] 3.3 Pass trades DataFrame to `compute_features()` in the live service (currently passed as None)
- [x] 3.4 Add mark/index price seeding from data catalog on `ml_feature_service` startup
- [x] 3.5 Add periodic (60s) mark/index price refresh via exchange REST API
- [x] 3.6 Pass mark_1m and index_1m DataFrames to `compute_features()` for basis features
- [x] 3.7 Implement graceful degradation: NaN for missing trades/mark/index without service crash
- [x] 3.8 Write unit tests for microstructure feature population with sufficient/insufficient trades
- [x] 3.9 Write unit tests for basis feature computation with/without mark-index data

## 4. Hyperparameter Tuning

- [x] 4.1 Add `optuna` to the Python training environment dependencies used by research/training commands
- [x] 4.2 Implement `run_hyperparameter_tuning()` in `research.py` with Optuna TPE sampler objective
- [x] 4.3 Define search spaces per model type (LightGBM params for regime/direction/sizing/adverse)
- [x] 4.4 Add `tune=False` and `n_trials=50` parameters to `train_and_evaluate()`
- [x] 4.5 Persist tuning results (`best_params`, `n_trials`, `best_score`, `search_space`) in model metadata JSON
- [x] 4.6 Handle `ImportError` gracefully when `optuna` not installed but `tune=True`
- [x] 4.7 Add `seed` parameter for reproducible Optuna studies (sampler seed + CV seed)
- [x] 4.8 Write unit tests: tuning with mock objective, metadata persistence, import error handling

## 5. Unified Training Pipeline

- [x] 5.1 Add `model_type='adverse'` support to `research.train_and_evaluate()` with classification target
- [x] 5.2 Add adverse-specific deployment gates (higher accuracy threshold + lower improvement bar)
- [x] 5.3 Ensure all model types produce registry-compatible output via unified pipeline
- [x] 5.4 Add `label_mapping` dict to metadata for all model types (class index → human-readable name)
- [x] 5.5 Align regime class labels with `REGIME_VOL_BUCKET_MAP` (0-3 integer classes → kernel regime names)
- [x] 5.6 Convert `scripts/ml/train_regime_classifier.py` to thin wrapper calling `research.train_and_evaluate(model_type='regime')`
- [x] 5.7 Convert `scripts/ml/train_adverse_classifier.py` to thin wrapper calling `research.train_and_evaluate(model_type='adverse')`
- [x] 5.8 Write integration tests: adverse model support, label maps, deployment gate thresholds

## 6. Shadow Model Comparison

- [x] 6.1 Add `_shadow_models` dict to `ml_feature_service/main.py` alongside `_models`
- [x] 6.2 Implement shadow model loading: detect `shadow: true` in model metadata, load into `_shadow_models`
- [x] 6.3 Add dual inference logic: when shadow model exists for a type, run `predict_proba()` on both active and shadow
- [x] 6.4 Add a structured shadow-comparison contract/report format for timestamp, model_type, active_pred, shadow_pred, agreement, confidence delta
- [x] 6.5 Add `ML_SHADOW_MODE` env var toggle (default `false`)
- [x] 6.6 Implement live logging metrics: agreement_rate, mean_confidence_delta, prediction_correlation over configurable soak window
- [ ] 6.7 Implement an offline evaluator/report job that joins shadow logs with realized outcomes and produces promote/reject metrics (DEFERRED: needs real shadow soak data)
- [x] 6.8 Write unit tests for shadow loading, dual inference, divergence logging, and evaluator inputs/outputs

## 7. Feature Importance Tracking

- [x] 7.1 Extract per-fold feature importances from LightGBM during CV (already available via `feature_importances_`)
- [x] 7.2 Persist compact feature importance summary in model metadata: top-k features, stability scores, aggregate importances
- [x] 7.3 Compute feature stability metric: fraction of folds where each feature appears in top-k
- [x] 7.4 Write a detailed fold-level feature-importance report artifact alongside the saved model
- [x] 7.5 Add tests for metadata/report persistence and feature stability calculation

## 8. Contracts, Config, and Governance

- [x] 8.1 Update `event_schemas.py` and stream name contracts for any new shadow comparison/report payloads
- [x] 8.2 Update `data_requirements.yml` for mark/index/trades inputs required by live feature activation
- [x] 8.3 Update ML config/env docs for TF lists, shadow mode, Optuna budgets, and embargo window sizes
- [x] 8.4 Update `ml_governance_policy_v1.json` or related promotion checks to recognize shadow evaluation outputs
- [x] 8.5 Add tests for config parsing and contract serialization/deserialization

## 9. Integration Testing & Validation

- [x] 9.1 Run full training pipeline with purged CV on existing regime dataset — verify gates pass (58.83% OOS, deployment_ready=true)
- [x] 9.2 Run full training pipeline with purged CV on existing adverse dataset — verify gates pass (78.73% OOS, deployment_ready=true)
- [x] 9.3 Deploy updated `ml_feature_service` to paper environment with multi-TF features enabled (1m,5m,15m,1h active)
- [x] 9.4 Verify `MlFeatureEvent` payloads contain non-NaN microstructure and basis features (verified: basis, funding, flow_imbalance all populated)
- [x] 9.5 Verify cross-TF features are present and reasonable in live events (verified: trend_alignment, wr_divergence, atr_ratio all non-NaN)
- [ ] 9.6 Run the shadow evaluator/report step on soak data and review promote/reject outputs (DEFERRED: needs real shadow soak data)
- [x] 9.7 Run architecture contract tests: `python -m pytest hbot/tests/architecture/ -q`
- [x] 9.8 Compile all modified modules: `python -m py_compile` on each changed file
