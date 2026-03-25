## Context

The ML engine currently runs a live `ml_feature_service` that computes features from 1m OHLCV bars, runs LightGBM inference for regime/direction/sizing, and publishes predictions to Redis. The trading kernel consumes these via `signal_consumer.py` → `regime_mixin.py`. An independent adverse-fill classifier runs inside the bridge.

**Current state problems:**
- Live inference uses only 1m-resolution features despite the pipeline supporting 5m/15m/1h resampling
- Microstructure and basis features are NaN in live (no trades/mark/index data fed)
- Two divergent training paths produce incompatible model artifacts
- No hyperparameter search — fixed params across all experiments
- Walk-forward CV lacks embargo gaps → potential lookahead leakage
- No shadow/A-B comparison for model promotion

## Goals / Non-Goals

**Goals:**
- Multi-TF features flowing end-to-end: data → features → training → live inference → kernel
- All feature groups populated in live (microstructure, basis, multi-TF price)
- Scientifically rigorous validation (purged CV, embargo, baseline comparison)
- Automated hyperparameter tuning with configurable budgets
- Single unified training pipeline for all model types
- Safe model promotion via shadow comparison before activation

**Non-Goals:**
- Deep learning / transformer models (LightGBM remains the primary algorithm)
- Real-time model retraining (offline batch retraining remains the pattern)
- New model types beyond regime/direction/sizing/adverse (scope to existing types)
- Replacing the `model_registry.py` filesystem layout (extend, don't replace)
- Live A/B split of execution (shadow mode is prediction-only logging)

## Decisions

### D1: Multi-TF feature flow — resample inside ml_feature_service vs. separate TF streams

**Decision**: Resample inside `ml_feature_service` (current pattern, extended).

**Rationale**: The service already has `ML_TIMEFRAMES` env var and `_resample_bars()`. Extending this avoids new Redis streams for each TF. The rolling window in `PairFeatureState` already holds enough 1m bars (default 300) to build 1h bars. Keeping `4h` as an explicit opt-in timeframe avoids unnecessary warmup cost while still allowing richer experiments when enough history is available.

**Alternative rejected**: Separate stream per TF — adds operational complexity, synchronization issues, and Redis memory overhead for minimal benefit.

### D2: Trades and mark/index data — new Redis consumers vs. REST polling

**Decision**: Add Redis stream consumers for `hb.market_trade.v1` (already exists) and add mark/index via catalog seeding + periodic REST refresh.

**Rationale**: Trades arrive high-frequency on `hb.market_trade.v1` — consuming this stream in `ml_feature_service` gives real-time CVD/flow. Mark/index prices are lower-frequency; seeding from catalog on startup + polling exchange API every 60s avoids adding new streams. `PairFeatureState` already has a `_trades` buffer concept in `bar_builder.py`.

### D3: Purged CV implementation — custom vs. sklearn's TimeSeriesSplit

**Decision**: Custom `purged_walk_forward_cv()` function in `research.py`.

**Rationale**: sklearn's `TimeSeriesSplit` doesn't support embargo gaps or purging. The custom implementation is straightforward: for each fold, add `embargo_bars` (default: `2 × max_label_horizon`) between train-end and test-start, and purge any training samples whose label window overlaps the test period. This is standard in quant ML (de Prado, "Advances in Financial ML").

### D4: Hyperparameter tuning — Optuna vs. GridSearch vs. manual

**Decision**: Optuna with TPE sampler, integrated into `train_and_evaluate()`.

**Rationale**: Optuna's TPE sampler is efficient for small search budgets (50-200 trials). It already handles early pruning of bad trials. The budget is configurable per model type via config. Grid search is wasteful for >3 hyperparameters. Manual tuning doesn't scale.

**Search space** (LightGBM): `n_estimators` [50-500], `max_depth` [3-8], `learning_rate` [0.01-0.3], `num_leaves` [15-63], `min_child_samples` [10-100], `subsample` [0.6-1.0], `colsample_bytree` [0.6-1.0], `reg_alpha` [0-1], `reg_lambda` [0-1].

### D5: Unified training — merge scripts into research.py vs. keep separate

**Decision**: Keep `research.py` as the single entry point; standalone scripts become thin wrappers that call `research.train_and_evaluate()`.

**Rationale**: `research.py` already has the registry-aligned output, deployment gates, and walk-forward CV. The standalone scripts add dataset builders and different label mappings — these become config options, not separate code paths. The adverse-fill model's custom feature vector (from `get_custom_info()`) is handled by adding `model_type='adverse'` support to `research.py` with a pluggable feature extractor.

### D6: Shadow model comparison — dual inference vs. offline replay

**Decision**: Dual inference in `ml_feature_service` with structured divergence logging, plus offline evaluation for promotion decisions.

**Rationale**: The service already loads models by type. Adding a `shadow_models` dict alongside `_models` is minimal code change. Shadow predictions should be written to a structured comparison stream/report, never routed to the bridge. Real performance against future outcomes cannot be decided inside the live inference loop because labels arrive later; promotion scoring therefore belongs in an offline evaluator/report step fed by the logged shadow events.

### D7: Feature-importance tracking — metadata only vs. separate reports

**Decision**: Persist a compact summary in model metadata and write a detailed report artifact alongside the model.

**Rationale**: Metadata should remain machine-readable and small enough for runtime loading, while fold-level importances and stability analysis are more useful as a separate report for research review. The metadata keeps top-k summaries and stability metrics; the report keeps the full fold table.

## Risks / Trade-offs

**[Risk: Increased ml_feature_service latency from trades consumption]**
→ Mitigation: Trades are aggregated into 1s micro-bars in `bar_builder.py`, not processed tick-by-tick. Feature computation only triggers on 1m bar close, same as today.

**[Risk: Optuna tuning takes too long for CI/promotion gates]**
→ Mitigation: Default budget is 50 trials (fast mode) for CI, 200 trials for manual training runs. Tuning is optional and skipped when `tune=False` (default for quick runs).

**[Risk: Purged CV reduces effective training data]**
→ Mitigation: Embargo is typically 60 bars (1h for 1m data) — less than 1% of a 30-day dataset. The data integrity gain far outweighs the small sample reduction.

**[Risk: Shadow mode doubles inference compute]**
→ Mitigation: Shadow models only run when explicitly enabled via config. The cost is one extra `model.predict_proba()` per tick — negligible for LightGBM (sub-millisecond).

**[Risk: Shadow promotion logic depends on future outcomes not available in the live loop]**
→ Mitigation: Treat the live service as a logger only; compute promotion-ready metrics in a separate offline evaluation/report job.

**[Risk: Feature dimension explosion with full multi-TF + microstructure]**
→ Mitigation: Feature importance tracking automatically identifies low-value features. The deployment gate already requires feature stability (≥5 features in top-10 across 60% of CV windows). Post-training pruning can be added as a follow-up.

**[Trade-off: Unified pipeline reduces flexibility for experimental scripts]**
→ Accepted: The cost of two divergent paths (incompatible registries, untested integration) is higher than the flexibility loss. Experiments can still override config, just not the output schema.
