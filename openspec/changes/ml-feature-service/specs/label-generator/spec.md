## ADDED Requirements

### Requirement: Forward return labels
The label generator SHALL compute forward returns at configurable horizons (default: 5, 15, 60 minutes) from 1m OHLCV data. For each horizon N, it SHALL produce:
- `fwd_return_{N}m`: raw forward return as float `(close[t+N] - close[t]) / close[t]`
- `fwd_return_sign_{N}m`: sign as int (-1, 0, +1) with a deadzone of +/- 0.0001
- `fwd_return_bucket_{N}m`: quantized into 5 buckets (0=strong_down, 1=down, 2=flat, 3=up, 4=strong_up) using rolling percentile boundaries

#### Scenario: Compute 5-minute forward returns
- **WHEN** `compute_labels(candles_1m, horizons=[5])` is called with 1000 rows
- **THEN** the output has 995 rows with valid `fwd_return_5m` values and 5 trailing rows with NaN

#### Scenario: Bucket boundaries adapt to volatility
- **WHEN** forward return buckets are computed
- **THEN** bucket boundaries are determined by rolling percentiles (20th, 40th, 60th, 80th) of the forward return distribution over the trailing 1440 bars

### Requirement: Forward volatility labels
The label generator SHALL compute forward realized volatility:
- `fwd_vol_{N}m`: standard deviation of 1m log returns over the next N bars
- `fwd_vol_bucket_{N}m`: classified as {low=0, normal=1, elevated=2, extreme=3} using rolling percentile thresholds (25th, 75th, 95th)

#### Scenario: Forward vol with sufficient data
- **WHEN** labels are computed for a 1m candle series with 10000+ rows
- **THEN** `fwd_vol_15m` values are positive floats and `fwd_vol_bucket_15m` values are integers in [0, 3]

### Requirement: Max adverse and favorable excursion labels
The label generator SHALL compute per bar:
- `fwd_mae_{N}m`: maximum adverse excursion — the largest unfavorable price move within the next N bars, measured as `max(high[t+1:t+N]) - close[t]` for a hypothetical long, always positive
- `fwd_mfe_{N}m`: maximum favorable excursion — the largest favorable price move, measured as `close[t] - min(low[t+1:t+N])` for a hypothetical long, always positive

For directional symmetry, both long-side and short-side MAE/MFE SHALL be computed.

#### Scenario: MAE/MFE on trending market
- **WHEN** price trends up over 15 bars from bar t
- **THEN** `fwd_mfe_15m` (long) is large and `fwd_mae_15m` (long) is small

#### Scenario: MAE/MFE at end of data
- **WHEN** fewer than N bars remain after bar t
- **THEN** MAE/MFE values for horizon N are NaN

### Requirement: Tradability score
The label generator SHALL compute a composite tradability score:
- `tradability_{N}m`: `mfe / (mae + epsilon)` where epsilon prevents division by zero
- Higher values indicate bars where the forward risk/reward was favorable

#### Scenario: High tradability bar
- **WHEN** a bar has `fwd_mfe_15m = 0.005` and `fwd_mae_15m = 0.001`
- **THEN** `tradability_15m` is approximately 5.0

### Requirement: Labels from raw OHLCV only
The label generator SHALL compute all labels from raw candle data (timestamp, open, high, low, close, volume) without any dependency on strategy signals, regime labels, indicator values, or bot state. Labels represent pure market outcomes.

#### Scenario: No strategy dependency
- **WHEN** the label generator module is inspected
- **THEN** it imports no modules from `controllers/regime_detector`, `controllers/price_buffer`, `controllers/bots/`, or `services/`

### Requirement: Label output format
The `compute_labels()` function SHALL return a DataFrame with columns `[timestamp_ms, label_1, label_2, ...]`. All label columns SHALL be float64 or int64. The DataFrame SHALL have the same number of rows as the input candles, with NaN for bars where forward-looking data is insufficient.

#### Scenario: Label DataFrame structure
- **WHEN** `compute_labels(candles_1m, horizons=[5, 15, 60])` is called
- **THEN** the output contains columns for all 3 horizons: returns (raw, sign, bucket), volatility (raw, bucket), MAE, MFE, and tradability — approximately 30 label columns total
