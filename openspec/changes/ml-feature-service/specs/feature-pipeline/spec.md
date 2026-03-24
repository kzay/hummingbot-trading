## ADDED Requirements

### Requirement: Strategy-agnostic feature computation
The feature pipeline SHALL compute market-structure features from raw market data (OHLCV, trades, funding, LS ratio) without any dependency on bot state, strategy config, or internal controller modules. The pipeline SHALL be implemented as pure functions in `controllers/ml/feature_pipeline.py`.

#### Scenario: Feature pipeline has no strategy imports
- **WHEN** the feature pipeline module is inspected
- **THEN** it imports no modules from `controllers/bots/`, `controllers/epp_v2_4*`, `controllers/shared_runtime*`, or `services/signal_service/`

#### Scenario: Feature computation is deterministic
- **WHEN** `compute_features()` is called twice with the same input DataFrames
- **THEN** the output DataFrames are identical (same values, same column order)

### Requirement: Multi-timeframe price features
The function `compute_price_features()` SHALL accept candle DataFrames at multiple resolutions (1m required, 5m/15m/1h optional) and compute:
- Returns at each available timeframe
- ATR at each timeframe and cross-timeframe ATR ratios
- Close-in-range position `(close - low) / (high - low)` per timeframe
- Bar body ratio `|close - open| / (high - low)`
- Higher-TF trend alignment (sign comparison of 1m vs 1h returns)
- Bollinger band position `(close - lower) / (upper - lower)`
- RSI and ADX at 1m resolution

All outputs SHALL be float64. Missing timeframe inputs SHALL result in NaN for the corresponding features.

#### Scenario: Compute with all timeframes
- **WHEN** `compute_price_features()` is called with 1m, 5m, 15m, and 1h candle DataFrames
- **THEN** the output contains return, ATR, and range features for all 4 timeframes plus cross-TF ratios

#### Scenario: Compute with 1m only
- **WHEN** `compute_price_features()` is called with only 1m candles (5m, 15m, 1h are None)
- **THEN** the output contains 1m features with NaN for all higher-timeframe features, and no error is raised

### Requirement: Volatility structure features
The function `compute_volatility_features()` SHALL compute from 1m candles:
- Realized volatility (rolling std of log returns) at 15m, 1h, 4h windows
- Parkinson volatility estimator using high/low prices
- Garman-Klass volatility estimator using OHLC
- Volatility-of-volatility (rolling std of realized vol)
- ATR percentile vs trailing 24h and 7d distributions
- Range expansion ratio (current bar range vs rolling median range)

#### Scenario: Volatility features with sufficient history
- **WHEN** `compute_volatility_features()` is called with 2000+ 1m candle rows
- **THEN** all volatility features are computed with no NaN values after the warmup period

#### Scenario: Volatility features with insufficient history
- **WHEN** `compute_volatility_features()` is called with fewer bars than the longest lookback window
- **THEN** features requiring more history than available are NaN; shorter-window features are computed normally

### Requirement: Microstructure features from trades
The function `compute_microstructure_features()` SHALL compute from tick trade data:
- Cumulative volume delta (CVD)
- Trade flow imbalance (rolling buy_volume / total_volume)
- Large trade ratio (volume from trades > 2x rolling median size)
- Trade arrival rate (count per minute)
- VWAP deviation (close price vs VWAP)

These features SHALL be aligned to 1m timestamps by aggregating trades within each minute.

#### Scenario: Compute with trade data available
- **WHEN** `compute_microstructure_features()` is called with trade data spanning the candle range
- **THEN** per-minute microstructure features are computed and aligned to candle timestamps

#### Scenario: Compute without trade data
- **WHEN** trade data is None or empty
- **THEN** all microstructure features are NaN (graceful degradation, no error)

### Requirement: Derivatives sentiment features
The function `compute_sentiment_features()` SHALL compute from funding, LS ratio, mark candles, and index candles:
- Funding rate value (forward-filled to 1m timestamps)
- Funding rate momentum (rate of change over 3 funding intervals)
- Long/short ratio (forward-filled to 1m timestamps)
- LS ratio momentum
- Basis: `(mark_close - index_close) / index_close`
- Basis momentum
- Annualized funding rate

#### Scenario: Compute with all sentiment data
- **WHEN** all four data sources are provided
- **THEN** all sentiment features are computed

#### Scenario: Partial sentiment data
- **WHEN** LS ratio data is None but funding and mark/index are provided
- **THEN** LS-derived features are NaN; basis and funding features are computed normally

### Requirement: Time encoding features
The function `compute_time_features()` SHALL compute:
- Hour-of-day sine and cosine encoding
- Day-of-week sine and cosine encoding
- Trading session flag (Asia=0, Europe=1, US=2, overlap=3)
- Minutes since last funding interval (8h cycle)

#### Scenario: Time features from timestamps
- **WHEN** `compute_time_features()` is called with a list of Unix millisecond timestamps
- **THEN** cyclical time features are computed with values in [-1, 1] for sine/cosine

### Requirement: Unified feature assembly
The function `compute_features()` SHALL accept all data sources and return a single DataFrame with columns `[timestamp_ms, feat_1, feat_2, ...]` aligned to 1m timestamps. It SHALL call each sub-function and horizontally concatenate results. Feature column names SHALL be stable strings that do not change between versions.

#### Scenario: Full feature assembly
- **WHEN** `compute_features()` is called with all data sources
- **THEN** the output DataFrame has one row per 1m bar and 40-60 float64 feature columns

#### Scenario: Feature column stability
- **WHEN** a new feature group is added in a future version
- **THEN** existing feature column names and positions are preserved (new columns appended)

### Requirement: Float-native indicator implementations
The feature pipeline SHALL include its own float64/numpy indicator implementations (EMA, SMA, ATR, RSI, ADX, Bollinger Bands, stddev) in `controllers/ml/_indicators.py`. These SHALL NOT import from `controllers/common/indicators.py` (which uses Decimal). Correctness SHALL be validated by cross-checking outputs against the Decimal reference implementations within a tolerance of 1e-6.

#### Scenario: Float ATR matches Decimal ATR
- **WHEN** the float-native ATR is computed on the same price series as the Decimal ATR from `controllers/common/indicators.py`
- **THEN** the results match within a relative tolerance of 1e-6

#### Scenario: No Decimal in feature pipeline
- **WHEN** the feature pipeline module is inspected
- **THEN** it does not import `Decimal` from the `decimal` module

### Requirement: Train/serve parity
The feature pipeline code SHALL be used identically in offline research (operating on Parquet DataFrames loaded via `load_candles_df()`) and in the live ml-feature-service (operating on DataFrames built from rolling bar windows). No separate feature computation logic SHALL exist for live serving.

#### Scenario: Offline and online produce identical features
- **WHEN** the same 1440-bar window of candle data is processed offline (from Parquet via `load_candles_df()`) and online (from trade-built bars in the ml-feature-service)
- **THEN** the resulting feature vectors are numerically identical (within float64 precision) for features that do not depend on sub-bar resolution (microstructure features may have minor differences due to trade-tick vs exchange-aggregated bar construction)
