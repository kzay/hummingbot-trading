## Why

The trading system has a rule-based regime detector (EMA + ATR + drift thresholds) that is hand-tuned and identical across all market conditions. Meanwhile, 128k+ rows of historical 1m candles are already downloaded, and Bitget's API offers additional data (mark/index candles, long/short ratio history, tick trades, funding) that could power genuinely predictive signals. The current ML infrastructure (ROAD-10, ROAD-11) is blocked on paper-trading data volume, but the real blocker is the wrong data source — the system should learn from historical market structure, not wait months for the bot's own labeled logs.

The system also needs to serve multiple bots (bot1-bot7), multiple strategies (MM, pullback, CVD divergence), and multiple pairs (BTC-USDT, ETH-USDT, future additions) concurrently. Today the signal_service is hardcoded to bot1. A shared, pair-keyed ML feature service removes this limitation.

## What Changes

- New multi-resolution, multi-type data download capability: mark/index OHLCV, long/short ratio history, multi-resolution candles (1m/5m/15m/1h), all for any pair
- New strategy-agnostic feature engineering pipeline: 40-60 market-structure features (multi-TF returns, volatility structure, microstructure, derivatives sentiment, time encoding) — pure functions usable in both offline research and live serving
- New label generator that computes forward price outcomes (returns, volatility, MAE/MFE, tradability) from raw OHLCV — no circular dependency on the bot's own regime detector
- New offline research pipeline: data assembly, feature+label join, walk-forward training (LightGBM), baseline comparison against rule-based regime detector
- New model registry keyed by `(exchange, pair, model_type)` so each pair gets its own trained model
- New `ml-feature-service` microservice: shared, multi-tenant, publishes features and predictions per pair to `hb.ml_features.v1` for any bot to consume
- Enhanced bot consumption: bots filter `MlFeatureEvent` by `trading_pair` and route predictions to `apply_execution_intent()`

## Capabilities

### New Capabilities
- `multi-source-data-download`: Extend DataDownloader with mark/index candles, long/short ratio, multi-resolution support, and multi-pair CLI orchestration
- `feature-pipeline`: Strategy-agnostic, pair-agnostic feature computation (price, volatility, microstructure, sentiment, time) — same code for research and live
- `label-generator`: Forward-looking label computation from raw OHLCV (returns, vol buckets, MAE/MFE, tradability score)
- `ml-research-pipeline`: Offline training pipeline with walk-forward CV, per-pair model registry, baseline comparison, and go/no-go deployment gates
- `ml-feature-service`: Shared multi-tenant microservice that computes features and serves predictions per pair to all bots via Redis stream

### Modified Capabilities
- (none — new capabilities only; existing signal_service is not modified, it will be deprecated gradually)

## Impact

- **New files**: `controllers/ml/feature_pipeline.py`, `controllers/ml/label_generator.py`, `controllers/ml/research.py`, `controllers/ml/model_registry.py`, `services/ml_feature_service/` (new service directory)
- **Modified files**: `controllers/backtesting/data_downloader.py` (new download methods), `controllers/backtesting/types.py` (new row types), `controllers/backtesting/data_store.py` (new persistence), `services/contracts/event_schemas.py` (new `MlFeatureEvent`), `services/contracts/stream_names.py` (new stream name), `compose/docker-compose.yml` (new service)
- **Dependencies**: `lightgbm`, `pandas`, `pyarrow`, `numpy` (most already available; `lightgbm` is new for training)
- **Data**: New catalog entries under `data/historical/{exchange}/{pair}/` for mark, index, ls_ratio resolutions
- **Redis**: New stream `hb.ml_features.v1`
- **No breaking changes**: All ML features are additive. Bots ignore `hb.ml_features.v1` if not subscribed. Rule-based fallback remains default.
