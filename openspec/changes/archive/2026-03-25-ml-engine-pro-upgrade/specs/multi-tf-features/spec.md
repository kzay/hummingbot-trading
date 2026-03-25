## ADDED Requirements

### Requirement: Default ML timeframes include higher TFs
The `ml_feature_service` SHALL use `1m,5m,15m,1h` as the default `ML_TIMEFRAMES` list. The `4h` timeframe SHALL be supported when explicitly added to the env var.

#### Scenario: Service starts with default config
- **WHEN** `ml_feature_service` starts without `ML_TIMEFRAMES` env var
- **THEN** features are computed for `1m`, `5m`, `15m`, and `1h` timeframes

#### Scenario: Custom timeframe list via env
- **WHEN** `ML_TIMEFRAMES=1m,5m,15m,1h,4h` is set
- **THEN** features include `4h`-derived columns alongside the default TFs

### Requirement: Cross-TF confluence features
`compute_features` SHALL produce cross-timeframe confluence signals that measure agreement between timeframes.

#### Scenario: Trend alignment computed across TFs
- **WHEN** `compute_features` is called with multi-TF data
- **THEN** output includes `trend_alignment_{tf1}_{tf2}` for each TF pair (e.g., `trend_alignment_1m_5m`, `trend_alignment_5m_1h`)

#### Scenario: Volatility regime agreement
- **WHEN** `compute_features` is called with multi-TF data
- **THEN** output includes `vol_regime_agreement` measuring consistency of ATR-based volatility classification across TFs

#### Scenario: Williams %R divergence across TFs
- **WHEN** `compute_features` is called with multi-TF data
- **THEN** output includes `wr_divergence_{tf1}_{tf2}` for detecting cross-TF momentum divergence

### Requirement: Multi-TF features propagate to MlFeatureEvent
The `MlFeatureEvent` payload published to Redis SHALL include all multi-TF feature columns in the `features` dict.

#### Scenario: Event includes higher-TF features
- **WHEN** `ml_feature_service` publishes an `MlFeatureEvent`
- **THEN** `features` dict contains keys for all configured TFs (e.g., `return_5m`, `atr_15m`, `close_in_range_1h`)

### Requirement: Sufficient rolling window for highest TF
`PairFeatureState` SHALL maintain enough 1m bars to construct at least 2 complete bars of the highest configured timeframe.

#### Scenario: 1h requires 120+ bars
- **WHEN** `ML_TIMEFRAMES` includes `1h`
- **THEN** `PairFeatureState.max_bars` is at least `120` (2 × 60 minutes)

#### Scenario: 4h requires 480+ bars
- **WHEN** `ML_TIMEFRAMES` includes `4h`
- **THEN** `PairFeatureState.max_bars` is at least `480` (2 × 240 minutes)
