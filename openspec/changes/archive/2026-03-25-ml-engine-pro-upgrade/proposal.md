## Why

The ML engine has pro-grade architecture (contracts, governance, runtime integration) but semi-pro methodology. Five critical gaps prevent it from delivering real edge:

1. **Single-timeframe features in live**: The feature pipeline supports multi-TF (5m, 15m, 1h, 4h) but live inference only publishes at 1m resolution — higher-TF context is computed but under-utilized for cross-TF confluence signals.
2. **Dead feature groups in production**: Microstructure (CVD, flow imbalance, trade arrival rate) and basis/funding features are NaN in live because `ml_feature_service` doesn't pass trades, mark, or index data to `compute_features`.
3. **No hyperparameter tuning or purged validation**: Training uses fixed hyperparameters and simple expanding-window CV without embargo/purge gaps, risking lookahead contamination and sub-optimal models.
4. **Dual training paths with divergent schemas**: `controllers/ml/research.py` and `scripts/ml/train_*.py` produce models with incompatible registry layouts and label mappings.
5. **No model A/B testing**: New models replace old ones without shadow comparison, making it impossible to measure incremental improvement.

## What Changes

- **Multi-timeframe feature enrichment**: Wire higher-TF (5m, 15m, 1h) features as first-class inputs to live inference, with cross-TF confluence signals (trend alignment, volatility regime agreement across TFs).
- **Activate dead features**: Feed trades DataFrame and mark/index 1m data into `compute_features` in the live service so microstructure and basis columns are populated.
- **Purged walk-forward CV**: Add embargo gaps between train/test windows to prevent lookahead, implement purged k-fold as the default validation strategy.
- **Hyperparameter tuning**: Integrate Optuna for automated hyperparameter search within each CV fold, with configurable search budgets.
- **Unified training pipeline**: Consolidate `scripts/ml/train_*.py` into `controllers/ml/research.py` path, producing registry-compatible models with consistent label mappings and metadata.
- **Shadow model comparison**: Add a shadow inference mode where a candidate model runs alongside the active model, logging prediction divergence without affecting execution.
- **Feature importance tracking**: Persist per-window feature importances and stability metrics in model metadata for drift detection.

## Capabilities

### New Capabilities
- `multi-tf-features`: Multi-timeframe feature engineering — cross-TF confluence signals, TF-aware feature aggregation, and higher-TF context for live inference.
- `live-feature-activation`: Activate microstructure (trades-based) and basis (mark/index-based) feature groups in the live ml_feature_service.
- `purged-walk-forward`: Purged walk-forward cross-validation with embargo gaps and optional purged k-fold for time-series models.
- `hyperparameter-tuning`: Optuna-based hyperparameter optimization integrated into the training pipeline with configurable search budgets per model type.
- `unified-training`: Single training entry point that produces registry-aligned models for all model types (regime, direction, sizing, adverse-fill) with consistent schemas.
- `shadow-model-comparison`: Shadow inference mode for candidate models running alongside active models, with divergence logging and promotion metrics.
- `feature-importance-tracking`: Persist fold-level feature importances and stability summaries in model metadata and reports for drift detection and model review.

### Modified Capabilities
_(none — all new capabilities, no existing spec requirements change)_

## Impact

- **Code**: `hbot/services/ml_feature_service/` (main, pair_state), `hbot/controllers/ml/` (research, feature_pipeline, model_registry), `hbot/scripts/ml/`, `hbot/simulation/bridge/signal_consumer.py`, `hbot/platform_lib/contracts/event_schemas.py`
- **Data**: Enriched live inputs for trades/mark/index to the ML service; shadow comparison reports/events; larger model metadata files
- **Config**: New config keys for TF lists, Optuna budgets, shadow mode toggles, embargo window sizes
- **Dependencies**: `optuna` package addition to the training environment dependencies
- **Tests**: New test coverage for purged CV, multi-TF features, shadow comparison, unified training, and feature-importance persistence
- **Backlog alignment**: Directly addresses ROAD-10 (regime classifier) and ROAD-11 (adverse classifier) unblock requirements; improves validation rigor needed for ROAD-1 (paper edge confidence)
