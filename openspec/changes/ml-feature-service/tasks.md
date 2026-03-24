## 1. Data Layer — Multi-Source Downloads

- [x] 1.1 Add `LongShortRatioRow` dataclass to `controllers/backtesting/types.py` with fields: `timestamp_ms`, `long_account_ratio`, `short_account_ratio`, `long_short_ratio`
- [x] 1.2 Add `save_long_short_ratio()`, `load_long_short_ratio()`, and `load_candles_df()` to `controllers/backtesting/data_store.py` — `load_candles_df()` reads Parquet directly into a pandas DataFrame with float64 columns, bypassing Decimal/CandleRow conversion
- [x] 1.3 Add `download_mark_candles()` method to `DataDownloader` — calls `fetch_ohlcv` with `params={"price": "mark"}`, returns `list[CandleRow]`. Note: Bitget mark candles may return volume=0; skip volume validation warning for mark/index types
- [x] 1.4 Add `download_index_candles()` method to `DataDownloader` — calls `fetch_ohlcv` with `params={"price": "index"}`, returns `list[CandleRow]`
- [x] 1.5 Add `download_long_short_ratio()` method to `DataDownloader` — calls `fetch_long_short_ratio_history()`, returns `list[LongShortRatioRow]`. Guard with `has.get("fetchLongShortRatioHistory")` capability check
- [x] 1.6 Add `download_and_register_mark_candles()`, `download_and_register_index_candles()`, `download_and_register_long_short_ratio()` convenience methods with resume support and catalog registration (resolution keys: `mark_{tf}`, `index_{tf}`, `ls_ratio`)
- [x] 1.7 Update CLI `main()` in `data_downloader.py`: support `--types candles,mark,index,trades,funding,ls_ratio` and `--resolution 1m,5m,15m,1h` (comma-separated, loop over each combination)
- [x] 1.8 Write tests for new download methods: mock ccxt exchange, verify Parquet round-trip for LongShortRatioRow, verify `load_candles_df()` returns float64 DataFrame, verify catalog registration with resolution keys
- [ ] 1.9 Download 12+ months of all data types for BTC-USDT: `--types candles,mark,index,funding,ls_ratio --resolution 1m,5m,15m,1h --start 2024-06-01 --end 2026-03-21`
- [ ] 1.10 Download 12+ months of all data types for ETH-USDT (same parameters)

## 2. Feature Pipeline — Core Module

- [x] 2.1 Create `controllers/ml/__init__.py` (empty)
- [x] 2.2 Create `controllers/ml/feature_pipeline.py` with top-level `compute_features()` function signature accepting all data source DataFrames (all float64, no Decimal)
- [x] 2.3 Implement float-native indicator helpers in `controllers/ml/_indicators.py`: EMA, SMA, ATR, RSI, ADX, Bollinger Bands, stddev — numpy/pandas vectorized on float64 arrays. Use `controllers/common/indicators.py` as reference for correctness but do NOT import it. Add cross-validation test comparing outputs within tolerance
- [x] 2.4 Implement `compute_price_features()`: multi-TF returns, ATR per TF (using float-native ATR), ATR ratios, close-in-range, body ratio, trend alignment, BB position, RSI, ADX
- [x] 2.5 Implement `compute_volatility_features()`: realized vol (15m/1h/4h windows), Parkinson vol, Garman-Klass vol, vol-of-vol, ATR percentile vs 24h/7d, range expansion
- [x] 2.6 Implement `compute_microstructure_features()`: CVD, flow imbalance, large trade ratio, trade arrival rate, VWAP deviation — all aligned to 1m timestamps
- [x] 2.7 Implement `compute_sentiment_features()`: funding rate + momentum, LS ratio + momentum, basis (mark-index), basis momentum, annualized funding — forward-fill to 1m alignment
- [x] 2.8 Implement `compute_time_features()`: hour/day sin/cos, session flag, minutes since funding
- [x] 2.9 Wire `compute_features()` to call all sub-functions, concatenate horizontally, return unified DataFrame with `timestamp_ms` + feature columns
- [x] 2.10 Handle graceful NaN for missing data sources (trades=None, ls_ratio=None, etc.)
- [x] 2.11 Write unit tests: deterministic output, NaN handling for missing sources, column name stability, no strategy imports, float-native indicator accuracy vs Decimal reference

## 3. Label Generator

- [x] 3.1 Create `controllers/ml/label_generator.py` with `compute_labels(candles_1m, horizons)` signature — input is float64 DataFrame, not CandleRow
- [x] 3.2 Implement forward return labels: `fwd_return_{N}m`, `fwd_return_sign_{N}m`, `fwd_return_bucket_{N}m` with rolling percentile bucket boundaries
- [x] 3.3 Implement forward volatility labels: `fwd_vol_{N}m`, `fwd_vol_bucket_{N}m` with percentile thresholds
- [x] 3.4 Implement MAE/MFE labels: `fwd_mae_{N}m`, `fwd_mfe_{N}m` for both long and short sides
- [x] 3.5 Implement tradability score: `tradability_{N}m = mfe / (mae + epsilon)`
- [x] 3.6 Handle trailing NaN rows where forward data is insufficient
- [x] 3.7 Write unit tests: correct forward return computation, bucket distribution, MAE/MFE on known price sequences, no strategy imports

## 4. Research Pipeline — Training

- [x] 4.1 Create `controllers/ml/model_registry.py`: functions to save/load models and metadata by `(exchange, pair, model_type)`, directory structure `data/ml/models/{exchange}/{pair}/`
- [x] 4.2 Create `controllers/ml/research.py` with `assemble_dataset(exchange, pair, catalog_dir)`: use `load_candles_df()` and equivalent loaders for all data types, compute features + labels, join on timestamp_ms, save as Parquet
- [x] 4.3 Implement walk-forward CV in `research.py`: temporal splits (5 windows default), train LightGBM per window, report OOS metrics per window
- [x] 4.4 Implement baseline comparison: run `RegimeDetector` on the same candle data (via Decimal conversion for the detector only), compute rule-based accuracy on the same forward-outcome labels, include in report
- [x] 4.5 Implement deployment gates: OOS accuracy >= 55%, improvement >= 0.05 over baseline, feature importance stability (top-10 in 60%+ of windows)
- [x] 4.6 Implement model registry save: `{model_type}_v1.joblib` + `{model_type}_v1_metadata.json` with all required fields including `feature_columns` (ordered list for serving parity)
- [x] 4.7 Add CLI entry point: `python -m controllers.ml.research --exchange bitget --pair BTC-USDT --model-type regime --output data/ml/models`
- [x] 4.8 Write integration test: assemble small synthetic dataset, run CV, verify metadata output and gate logic

## 5. Train and Validate Models

- [ ] 5.1 Assemble BTC-USDT feature+label dataset from downloaded data
- [ ] 5.2 Train BTC-USDT regime model (Stage 1: predict `fwd_vol_bucket_15m`), run 5-window walk-forward CV
- [ ] 5.3 Evaluate BTC-USDT regime model: check OOS accuracy, baseline comparison, feature importance stability
- [ ] 5.4 Assemble ETH-USDT feature+label dataset
- [ ] 5.5 Train ETH-USDT regime model, evaluate
- [ ] 5.6 If regime models pass gates: train direction models (Stage 2: predict `fwd_return_sign_15m`), evaluate
- [ ] 5.7 If direction models pass gates: train sizing models (Stage 3: predict `tradability_15m`), evaluate
- [ ] 5.8 Document results in `docs/strategy/experiment_ledger.md`

## 6. Event Schema and Stream

- [x] 6.1 Add `MlFeatureEvent` to `services/contracts/event_schemas.py`: fields `exchange`, `trading_pair`, `timestamp_ms`, `features` (dict), `predictions` (dict), `model_versions` (dict). Extends `EventEnvelope` with `event_type: Literal["ml_features"]`
- [x] 6.2 Add `ML_FEATURES_STREAM = "hb.ml_features.v1"` to `services/contracts/stream_names.py` and add entry to `STREAM_RETENTION_MAXLEN`
- [x] 6.3 Add new intent actions to `SharedRuntimeKernel.apply_execution_intent()`: `set_ml_regime`, `set_ml_direction_hint`, `set_ml_sizing_hint` — called directly in-process by the ML consumer (not via ExecutionIntentEvent to avoid Literal type change)

## 7. ML Feature Service — Live

- [x] 7.1 Create `services/ml_feature_service/` directory with `__init__.py`, `main.py`, `pair_state.py`, `bar_builder.py`
- [x] 7.2 Implement `BarBuilder` in `bar_builder.py`: accumulates individual trades from `hb.market_trade.v1` into 1m OHLCV bars per pair. Emits a completed bar when the minute boundary crosses. Handles out-of-order trades and gap detection
- [x] 7.3 Implement `PairFeatureState` in `pair_state.py`: rolling 1440-bar window, higher-TF resampling (5m/15m/1h from 1m bars), warmup tracking, cached sentiment data (LS ratio, funding)
- [x] 7.4a Implement startup seeding in `main.py`: on boot, fetch the last 1440 1m candles per pair from ccxt `fetch_ohlcv()` to fill the rolling window immediately (avoids 24h blind period on restart). Follow the same pattern as `_maybe_seed_price_buffer` in `shared_runtime_v24.py`
- [x] 7.4b Implement exchange-API fallback: if `hb.market_trade.v1` produces no trade events for a configured pair within 2 minutes of startup, fall back to polling ccxt `fetch_ohlcv()` every 60s for fresh 1m bars. Switch back to live bar building when trades resume
- [x] 7.4c Implement main loop in `main.py`: subscribe to `hb.market_trade.v1` with own consumer group `hb_group_ml_features`, route trades by `trading_pair` to per-pair `BarBuilder`, compute features on bar close using `compute_features()` from feature_pipeline.py. Pair list from `ML_PAIRS` env var
- [x] 7.5 Implement model loading from registry: lazy load per `(exchange, pair, model_type)`, periodic refresh (default 1h). Use `joblib.load()` directly (same format as existing model_loader.py)
- [x] 7.6 Implement inference: run model predictions on computed features, format `MlFeatureEvent` with features + predictions + model_versions
- [x] 7.7 Implement live sentiment polling: periodic `fetch_long_short_ratio_history()` and `fetch_funding_rate_history()` per pair via ccxt, cache results in `PairFeatureState`
- [x] 7.8 Implement graceful degradation: missing model = publish features only (empty predictions dict), API failure = use stale cached sentiment data, trade stream gap = log warning and continue
- [x] 7.9 Publish `MlFeatureEvent` to `hb.ml_features.v1` per pair per bar
- [x] 7.10 Write tests: multi-pair state independence, bar building from trade ticks, feature parity with offline pipeline on same data, graceful handling of missing model

## 8. Bot Consumption

- [x] 8.1 Add ML feature consumer to `paper_engine_v2/signal_consumer.py`: extend existing `xread` call to also poll `hb.ml_features.v1` (non-blocking, same pattern). Add `last_ml_features_id` to `BridgeState`. Filter events by bot's `trading_pair` matching `controller.config.trading_pair`
- [x] 8.2 Route predictions to `apply_execution_intent()` directly in-process with confidence gating (threshold configurable, default 0.5). Do NOT go through ExecutionIntentEvent stream
- [x] 8.3 Add config flags to strategy YAML: `ml_features_enabled: false`, `ml_confidence_threshold: 0.5`, `ml_regime_override_enabled: false`, `ml_direction_hint_enabled: false`, `ml_sizing_hint_enabled: false`
- [x] 8.4 Verify graceful degradation: bot operates normally when ml-feature-service is absent (no events on stream = no action, no errors)

## 9. Docker Compose and Deployment

- [x] 9.1 Add `ml-feature-service` to `compose/docker-compose.yml` under profile `ml`: depends on redis, documents requirement for `market-data-service` (external profile) but can operate without it via exchange-API fallback. Volumes for model artifacts and workspace, env vars for config. Follow signal-service template pattern
- [x] 9.2 Create `compose/images/ml_feature_service/Dockerfile` and `requirements-ml-feature-service.txt` (lightgbm, pandas, pyarrow, numpy, ccxt, redis, joblib)
- [x] 9.3 Add `ML_PAIRS`, `ML_MODEL_DIR`, `ML_REFRESH_INTERVAL_S`, `ML_WARMUP_BARS`, `ML_POLL_INTERVAL_S` to `env/.env.template` with defaults
- [ ] 9.4 Test: `docker compose --profile ml up` starts the service, seeds rolling window from exchange API, subscribes to `hb.market_trade.v1`, and begins publishing features within 30 seconds of startup
- [ ] 9.5 Test: `docker compose --profile ml up` (without external profile) starts the service, seeds from exchange API, falls back to polling, and publishes features without market-data-service
