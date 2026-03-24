## ADDED Requirements

### Requirement: Multi-tenant feature service
The `ml-feature-service` SHALL be a standalone Docker service that computes features and serves predictions for all active trading pairs simultaneously. It SHALL maintain independent state per pair and support any number of pairs without code changes.

#### Scenario: Two pairs active
- **WHEN** trade ticks arrive for both BTC-USDT and ETH-USDT on `hb.market_trade.v1`
- **THEN** features and predictions are computed independently for each pair and published as separate events

#### Scenario: New pair added to configuration
- **WHEN** `ML_PAIRS` is updated to include a new pair and the service is restarted
- **THEN** the service creates a new per-pair state and begins computing features for that pair (model loaded lazily if available)

### Requirement: Build 1m bars from trade stream
The service SHALL subscribe to `hb.market_trade.v1` (published by `market_data_service`) and build 1m OHLCV bars per pair from individual trade ticks. This makes the service independent of bot availability — it operates as long as `market_data_service` is running.

#### Scenario: Bar construction from trades
- **WHEN** trades for BTC-USDT arrive on `hb.market_trade.v1` over a 1-minute window
- **THEN** the service constructs a 1m bar with open (first trade price), high (max trade price), low (min trade price), close (last trade price), volume (sum of trade sizes)

#### Scenario: No bot running for pair
- **WHEN** no bot is actively running for ETH-USDT but `market_data_service` is publishing ETH-USDT trades
- **THEN** the service still builds bars and computes features for ETH-USDT

#### Scenario: Trade stream gap
- **WHEN** no trades arrive for a pair within a 1-minute window
- **THEN** the service logs a warning and either produces a zero-volume bar (using last close as OHLC) or skips the bar, preserving feature continuity

### Requirement: Startup seeding from exchange API
On startup, the service SHALL fetch the last 1440 1m candles per configured pair directly from the exchange API via ccxt `fetch_ohlcv()`. This fills the rolling window immediately and avoids a 24-hour blind period. After seeding, the service switches to live bar building from `hb.market_trade.v1`.

#### Scenario: Cold start with exchange seeding
- **WHEN** the service starts for the first time
- **THEN** it fetches the last 1440 1m candles from the exchange for each pair in `ML_PAIRS`, fills the rolling window, and begins computing features and predictions within 30 seconds of startup

#### Scenario: Restart recovery
- **WHEN** the service restarts after a crash or deployment
- **THEN** the rolling window is re-seeded from the exchange API and predictions resume within 30 seconds, not 24 hours

#### Scenario: Exchange API unavailable at startup
- **WHEN** the exchange API is unreachable during startup seeding
- **THEN** the service logs an error, falls back to accumulating bars from the live trade stream, and starts publishing predictions after the minimum warmup (60 bars)

### Requirement: Fallback when market-data-service is absent
If `hb.market_trade.v1` produces no trade events for a configured pair within 2 minutes of startup, the service SHALL fall back to polling ccxt `fetch_ohlcv()` every 60 seconds for fresh 1m bars. This ensures the ML service can operate independently of `market-data-service`.

#### Scenario: No trade stream available
- **WHEN** `market-data-service` is not running and no trades arrive on `hb.market_trade.v1`
- **THEN** the service polls the exchange API for 1m candles every 60 seconds and continues computing features with ~60s delay

#### Scenario: Trade stream recovers
- **WHEN** trade events start arriving on `hb.market_trade.v1` after a period of exchange-API-only operation
- **THEN** the service switches back to live bar building from trades (lower latency) and stops polling

### Requirement: Per-pair rolling feature window
The service SHALL maintain a rolling window of 1m bars per pair (default 1440 bars = 24h) in memory. On each new bar close (detected via minute boundary crossing in the bar builder or exchange API poll), the window is updated and features are recomputed.

#### Scenario: Window initialization from seed
- **WHEN** the service seeds the rolling window from the exchange API
- **THEN** feature computation begins immediately on the first live bar close

#### Scenario: Window rolling
- **WHEN** the window reaches 1440 bars
- **THEN** the oldest bar is dropped when a new bar arrives, maintaining constant memory usage

### Requirement: Pair configuration
The service SHALL read the list of pairs to serve from the `ML_PAIRS` environment variable (comma-separated, e.g., `BTC-USDT,ETH-USDT`). Only trades for configured pairs SHALL be processed.

#### Scenario: Configured pair list
- **WHEN** `ML_PAIRS=BTC-USDT,ETH-USDT` is set
- **THEN** the service processes trades for BTC-USDT and ETH-USDT only, ignoring trades for other pairs

### Requirement: Feature computation using shared pipeline
The service SHALL compute features using the same `compute_features()` functions from `controllers/ml/feature_pipeline.py` that are used in offline research. The bar window is converted to a pandas DataFrame and passed to the same pure functions. No separate feature logic SHALL exist in the service.

#### Scenario: Feature parity with research
- **WHEN** the service computes features for a 1440-bar window
- **THEN** the feature values are numerically identical to running `compute_features()` on the same 1440 bars offline (within float64 precision, noting that trade-built bars may have minor H/L differences from exchange-aggregated OHLCV)

### Requirement: Model loading from registry
The service SHALL load models from the model registry at `data/ml/models/{exchange}/{pair}/{model_type}_v1.joblib`. Models SHALL be loaded lazily on first prediction request for a pair. The service SHALL support periodic model refresh (configurable interval, default 1 hour) to pick up retrained models without restart.

#### Scenario: Model available for pair
- **WHEN** a trained model exists for `bitget/BTC-USDT/regime_v1.joblib`
- **THEN** the service loads it and includes predictions in the output event

#### Scenario: No model available for pair
- **WHEN** no trained model exists for a pair
- **THEN** the service publishes features without predictions (empty `predictions` dict) — no error

#### Scenario: Model hot reload
- **WHEN** a model file is updated on disk and the refresh interval elapses
- **THEN** the service loads the new model version and logs the transition

### Requirement: Publish MlFeatureEvent to Redis
The service SHALL publish an `MlFeatureEvent` to `hb.ml_features.v1` per pair per bar containing:
- `exchange`: exchange identifier
- `trading_pair`: pair identifier (e.g., "BTC-USDT")
- `timestamp_ms`: bar timestamp
- `features`: dict of all computed feature name-value pairs (float)
- `predictions`: dict of model predictions, keyed by model_type (e.g., `{"regime": {"label": "elevated", "confidence": 0.73, "probabilities": {...}}, "direction_5m": {...}}`)
- `model_versions`: dict of model versions used (e.g., `{"regime": "v1"}`)

#### Scenario: Event published with predictions
- **WHEN** features are computed and a regime model is loaded for the pair
- **THEN** an `MlFeatureEvent` is published with both `features` and `predictions` populated

#### Scenario: Event published without predictions
- **WHEN** features are computed but no model is available
- **THEN** an `MlFeatureEvent` is published with `features` populated and `predictions` as empty dict

### Requirement: Live sentiment data polling
The service SHALL periodically poll the exchange API for data not available via WebSocket:
- Long/short ratio: every 5 minutes via ccxt `fetch_long_short_ratio_history()`
- Funding rate: every 5 minutes via ccxt `fetch_funding_rate_history()` (recent)
These values SHALL be cached per pair and used in sentiment feature computation.

#### Scenario: LS ratio polling
- **WHEN** 5 minutes have elapsed since the last LS ratio fetch for a pair
- **THEN** the service fetches the latest LS ratio and updates the sentiment feature inputs

#### Scenario: Exchange API unavailable
- **WHEN** the LS ratio or funding API call fails
- **THEN** the service uses the last cached value and logs a warning; feature computation continues with stale data

### Requirement: Bot consumption via apply_execution_intent
Bots SHALL consume `MlFeatureEvent` from `hb.ml_features.v1`, filter by their `trading_pair`, and route predictions to `apply_execution_intent()`. The following new intent actions SHALL be supported:
- `set_ml_regime`: override regime based on ML prediction (replaces rule-based if confidence above threshold)
- `set_ml_direction_hint`: provide directional bias for entry decisions
- `set_ml_sizing_hint`: provide sizing multiplier based on tradability prediction

#### Scenario: Bot receives regime prediction
- **WHEN** bot7 (BTC-USDT pullback) receives an `MlFeatureEvent` with `predictions.regime.label = "elevated"` and `confidence > 0.6`
- **THEN** `apply_execution_intent({"action": "set_ml_regime", "regime": "elevated", "confidence": 0.73})` is called

#### Scenario: Bot ignores irrelevant pair
- **WHEN** bot7 (BTC-USDT) receives an `MlFeatureEvent` with `trading_pair = "ETH-USDT"`
- **THEN** the event is ignored

#### Scenario: Low confidence prediction
- **WHEN** a prediction has `confidence < 0.5`
- **THEN** the bot does not act on it (stays with rule-based logic)

### Requirement: Graceful degradation
If the ml-feature-service is stopped, unresponsive, or produces no events, bots SHALL continue operating with their rule-based logic unchanged. No bot SHALL fail or degrade due to absence of ML predictions.

#### Scenario: Service unavailable
- **WHEN** the ml-feature-service container is stopped
- **THEN** all bots continue operating with `RegimeDetector` and their existing signal logic; no errors in bot logs

#### Scenario: Service restart
- **WHEN** the ml-feature-service restarts
- **THEN** it re-seeds the rolling window from the exchange API and resumes publishing predictions within 30 seconds (see: Startup seeding from exchange API)

### Requirement: Docker compose integration
The ml-feature-service SHALL be defined in `docker-compose.yml` as an optional service (profile: `ml`) with:
- Dependency on `redis`
- Volume mount for model artifacts: `../data/ml/models`
- Environment variables: `REDIS_HOST`, `ML_PAIRS`, `ML_MODEL_DIR`, `ML_REFRESH_INTERVAL_S`, `ML_WARMUP_BARS`, `ML_POLL_INTERVAL_S`
- Documentation that `market-data-service` (external profile) is recommended but not required — the ML service falls back to exchange API polling if the trade stream is absent

#### Scenario: Start with ML profile and external profile
- **WHEN** `docker compose --profile ml --profile external up` is run
- **THEN** the ml-feature-service starts, seeds from exchange API, and switches to live bar building from `hb.market_trade.v1`

#### Scenario: Start with ML profile only (no external)
- **WHEN** `docker compose --profile ml up` is run without the external profile
- **THEN** the ml-feature-service starts, seeds from exchange API, detects no trade stream within 2 minutes, and falls back to polling the exchange API every 60 seconds — still publishes features and predictions
