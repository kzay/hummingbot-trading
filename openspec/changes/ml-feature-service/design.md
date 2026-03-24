## Context

The trading desk runs 7 bot instances across 2 pairs (BTC-USDT, ETH-USDT) and 4 strategy types (MM, pullback, CVD divergence, IFT jota). Regime detection is rule-based (EMA + ATR + drift thresholds in `RegimeDetector`). The ML infrastructure (signal_service, model_loader, inference_engine, feature_builder) exists but is unused — blocked on paper-trading data volume. Historical data (128k+ 1m candles from Bitget) is already available and the `DataDownloader` can fetch more. The backtest engine runs 90 days in ~2 minutes after recent performance optimizations.

The signal_service is hardcoded to bot1 via `HB_INSTANCE_NAME=bot1`. Redis streams are shared with `instance_name` routing in event payloads. The paper-exchange-service already uses per-tenant routing via `TenantRouter`.

## Goals / Non-Goals

**Goals:**
- Build a strategy-agnostic feature pipeline that describes market structure, not bot state
- Support any pair: features keyed by `(exchange, pair, timestamp)`, models trained per pair
- Serve all bots simultaneously: single service, multi-tenant, routing by `trading_pair`
- Use walk-forward validation with baseline comparison as the deployment gate
- Maintain train/serve feature parity: identical code in research and production
- Graceful degradation: bots fall back to rule-based logic if ML service is absent

**Non-Goals:**
- Price direction prediction at sub-5-minute horizons (too efficient, overfit risk)
- Deep learning or reinforcement learning (unnecessary complexity for tabular features)
- Online learning from live fills (feedback loop risk)
- Replacing the existing signal_service immediately (gradual deprecation after validation)
- Real-time order book depth features (no historical depth data available from Bitget)

## Decisions

### 1. Features describe the market, not the bot

**Decision**: Feature pipeline computes market-structure features (multi-TF returns, volatility structure, derivatives sentiment, order flow) independent of any strategy's internal state.

**Why not bot-state features** (equity, position, spread, fill_edge): These are outputs of the strategy, not inputs to market understanding. Training on them creates circular dependencies — the model learns the bot's behavior, not the market's behavior. Strategy-specific adjustments (sizing, spread) happen downstream in the bot after consuming ML predictions.

### 2. Per-pair model training

**Decision**: Train separate models for each `(exchange, pair)` combination. No cross-pair model.

**Why not a universal model**: BTC-USDT and ETH-USDT have different volatility profiles, liquidity depth, funding dynamics, and market microstructure. A shared model would either underfit both or require pair-specific feature engineering that defeats the purpose. Per-pair models are simpler, more interpretable, and easier to validate.

**Alternative considered**: Multi-task learning with pair as a categorical feature. Rejected because the number of pairs is small (2-5) and per-pair training with 500k+ rows each provides sufficient data.

### 3. LightGBM for all model types

**Decision**: Use LightGBM for classification (regime, direction) and regression (sizing). No neural networks.

**Why**: Tabular features, moderate dimensionality (40-60 features), large row count (500k+). LightGBM consistently outperforms other tree methods on this profile. Already a declared preference in `ml-trading-guardrails.mdc`. Fast training (~seconds), fast inference (~microseconds), native feature importance.

### 4. Separate ml-feature-service, not enhancing signal_service

**Decision**: Build a new `ml-feature-service` rather than extending the existing `signal_service`.

**Why**: The signal_service mixes concerns (model loading, feature computation, signal routing) and is hardcoded to bot1. A clean service allows parallel development, independent scaling, and the existing signal_service continues working as fallback. The new service follows the same Redis stream pattern but with a richer event schema (`MlFeatureEvent`) and proper multi-pair state.

**Alternative considered**: Refactoring signal_service to be multi-tenant. Rejected because the feature pipeline and feature set are fundamentally different (market-structure vs bot-state), and a parallel service avoids regression risk on the existing system.

### 5. Forward-outcome labels, not regime-detector labels

**Decision**: ML labels are computed from raw price data — forward returns, forward volatility, MAE/MFE — not from `RegimeDetector.detect()` output.

**Why**: Training a model to replicate a rule-based detector is circular. The model at best learns EMA + ATR thresholds, which the rules already encode perfectly. Forward outcomes are the ground truth — they answer "what actually happened next" rather than "what did our rules classify this as."

### 6. Data layer: download everything Bitget offers

**Decision**: Extend `DataDownloader` to fetch mark/index candles, long/short ratio history, and multi-resolution candles (5m, 15m, 1h) for each pair.

**Why not stick with 1m OHLCV only**: Multi-timeframe features (ATR ratios across timeframes, trend alignment) are among the strongest predictors in quantitative trading. Derivatives-specific data (basis, LS ratio, funding momentum) captures crowd positioning — a well-documented contrarian signal in crypto. The marginal cost is small (one-time download, ~5-10 min per pair per year of data).

### 7. Live service builds candles from trade stream, not market snapshots

**Decision**: The ml-feature-service subscribes to `hb.market_trade.v1` (individual trades published by `market_data_service`) and builds its own 1m OHLCV bars per pair. It does NOT consume `hb.market_data.v1` (bot market snapshots).

**Why not `hb.market_data.v1`**: `MarketSnapshotEvent` only contains `mid_price` — no open/high/low/close/volume. Building real OHLCV from a single mid-price snapshot is unreliable. Additionally, `hb.market_data.v1` only has data when a bot is running for that pair, making the ML service dependent on bot availability.

**Why `hb.market_trade.v1`**: The `market_data_service` runs independently of bots and publishes individual trades to this stream for all configured pairs. Building 1m bars from trade ticks gives accurate H/L (from actual trade prices) and real volume. The service is also available for pairs that have no active bot.

**Rolling window**: 1440 bars (24h) per pair. The longest feature lookback is ~288 bars (4h ATR percentile vs 24h distribution). 1440 bars provides 5x headroom. Memory cost is ~100KB per pair.

**Higher timeframes**: Resampled from 1m bars in-process (5m, 15m, 1h aggregation). For LS ratio and funding, the service polls the exchange API periodically (every 5 minutes).

**Pair configuration**: Pairs come from `ML_PAIRS` env var (e.g., `BTC-USDT,ETH-USDT`), not auto-discovered from bot events, ensuring the service works regardless of which bots are running.

**Startup seeding**: On boot, the service fetches the last 1440 1m candles per pair directly from the exchange API via ccxt `fetch_ohlcv()`. This fills the rolling window immediately (takes ~5-10 seconds per pair) and avoids a 24-hour blind period on restart. After seeding, the service switches to live bar building from `hb.market_trade.v1`. This follows the same pattern as `_maybe_seed_price_buffer` in `shared_runtime_v24.py`.

**market-data-service dependency**: `market-data-service` runs under the `external` profile and defaults to `MARKET_DATA_SERVICE_ENABLED=false`. The ML service's compose entry must depend on it and document this requirement. As a fallback, if `hb.market_trade.v1` produces no trade events for a configured pair within 2 minutes of startup, the service logs a warning and continues operating on seeded exchange OHLCV alone (refreshed every 60s via ccxt `fetch_ohlcv`). This makes the ML service functional even without `market-data-service`, at the cost of slightly delayed bar data.

### 8. Float-native indicator implementations for the feature pipeline

**Decision**: The feature pipeline implements its own float64/numpy indicator functions rather than using `controllers/common/indicators.py` (which expects `Sequence[Decimal]`).

**Why not reuse indicators.py**: The existing stateless indicator functions use Decimal arithmetic throughout. On 500k+ rows in the research pipeline, Decimal is prohibitively slow (the same performance issue we fixed in price_buffer). The ML pipeline needs numpy-vectorized float64 operations.

**Why not modify indicators.py to accept float**: The production runtime depends on Decimal precision. Adding float overloads risks accidental use of float in production paths. Keeping them separate ensures the ML pipeline's optimizations don't leak into the trading runtime.

**Feature pipeline indicators will include**: EMA, SMA, ATR, RSI, ADX, Bollinger Bands, stddev — all as numpy/pandas vectorized operations on float64 arrays. These are well-known formulas and the existing indicators.py serves as a reference implementation for correctness tests.

### 9. Direct DataFrame loading from Parquet

**Decision**: Add `load_candles_df()` to `data_store.py` that reads Parquet directly into a pandas DataFrame with float64 columns, bypassing the `CandleRow` / Decimal conversion.

**Why**: `load_candles()` reads Parquet floats, converts to Decimal (expensive), wraps in CandleRow dataclasses. The research pipeline would then convert back to float64 DataFrame. Skipping the Decimal round-trip is both faster and cleaner for ML use.

## Risks / Trade-offs

- **[Overfitting]** Models trained on 1-2 years of crypto data may not generalize to future regimes. Mitigation: walk-forward CV with 5+ windows, deflated Sharpe ratio test, and mandatory OOS Sharpe improvement >= 0.3 over rule-based baseline.

- **[Train/serve skew]** Features computed offline (pandas on Parquet) vs online (rolling window from trades) could diverge. Mitigation: the feature pipeline is pure functions operating on DataFrames. Both paths call the same functions. The live service builds DataFrames from its rolling bar window and passes them to the same `compute_features()`. Integration test compares offline and online feature outputs on the same data. Note: live bars are built from trade ticks while historical bars come from exchange OHLCV — minor H/L differences are possible but immaterial for ML features.

- **[Bar construction from trades]** Building 1m OHLCV from trade ticks may produce slightly different H/L values than exchange-native 1m candles (exchange may include auction/hidden trades). Mitigation: differences are typically < 0.01% and do not materially affect features. The model is trained on exchange OHLCV and served from trade-built bars; walk-forward validation on live data will catch any systematic divergence.

- **[Latency]** Feature computation adds latency to the prediction cycle. Mitigation: LightGBM inference is ~100us. Feature computation (40-60 features from cached arrays) is ~1ms. Total < 5ms — well within the 60s tick interval.

- **[Multi-pair model maintenance]** Each pair needs its own model trained and validated. With 5 pairs, this is 5x training + validation effort. Mitigation: the research pipeline is automated — a single CLI command trains all pairs. Retraining cadence is monthly (not continuous).

- **[Missing data types]** Tick trades may not be available for all pairs or time ranges on Bitget. LS ratio history depth varies. Mitigation: feature pipeline handles missing inputs gracefully — features from unavailable data sources are NaN, and models are trained with the same NaN pattern.

- **[Model staleness]** A model trained on 2024-2025 data may degrade as market structure evolves. Mitigation: the live service logs `model_version` and `confidence` per prediction. Monitoring detects accuracy drift. Retraining is scripted and can be triggered when OOS metrics degrade.

## Migration Plan

1. Deploy Phase 0-3 (data + features + labels + research) without touching production — pure offline work
2. Train and validate models per pair — go/no-go gate at OOS metrics
3. Deploy `ml-feature-service` as a new Docker service alongside existing services — no changes to existing bots
4. Enable consumption in one bot (bot7 paper) first — monitor for 48h
5. If validated, enable for remaining bots
6. After 2+ weeks of stable ML service, deprecate old signal_service's feature_builder (keep model_loader and inference_engine as they share the same model format)

**Rollback**: Set `ml_regime_enabled: false` in bot config (instant, per-bot). Or stop the `ml-feature-service` container — bots fall back to rule-based automatically since they ignore missing `hb.ml_features.v1` events.

## Open Questions

1. Should the live service also compute and publish raw features (without predictions) for bots that want to consume features directly for custom logic? (Likely yes — the `MlFeatureEvent` includes both `features` and `predictions` dicts.)
2. What is the minimum viable set of pairs to train on at launch? (Likely BTC-USDT + ETH-USDT, the two currently active pairs.)
3. Should model retraining be automated on a schedule (e.g., monthly cron) or manually triggered? (Start manual, automate after process is proven.)
