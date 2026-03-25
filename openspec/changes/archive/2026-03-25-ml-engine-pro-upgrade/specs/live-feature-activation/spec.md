## ADDED Requirements

### Requirement: Consume trades stream for microstructure features
The `ml_feature_service` SHALL consume the `hb.market_trade.v1` Redis stream to build trade-derived microstructure features.

#### Scenario: Trade stream consumed on startup
- **WHEN** `ml_feature_service` starts and Redis is available
- **THEN** it creates a consumer group on `hb.market_trade.v1` and begins accumulating trades

#### Scenario: Trades aggregated into micro-bars
- **WHEN** trades arrive on `hb.market_trade.v1`
- **THEN** `PairFeatureState` aggregates them into the existing `bar_builder` flow and maintains a rolling trade buffer for microstructure computation

### Requirement: Microstructure features populated in live
`compute_features` SHALL receive a trades DataFrame when called from `ml_feature_service`, producing non-NaN microstructure columns.

#### Scenario: CVD and flow imbalance computed
- **WHEN** `compute_features` is called with a trades DataFrame containing at least 100 trades
- **THEN** `cvd`, `flow_imbalance`, `large_trade_ratio`, `trade_arrival_rate`, and `vwap_deviation` columns are populated (not NaN)

#### Scenario: Insufficient trades gracefully handled
- **WHEN** `compute_features` is called with fewer than 10 trades
- **THEN** microstructure columns are NaN with no errors raised

### Requirement: Mark and index prices for basis features
The `ml_feature_service` SHALL obtain mark price and index price data for computing basis and funding-related features.

#### Scenario: Mark/index seeded from catalog on startup
- **WHEN** `ml_feature_service` starts
- **THEN** it loads recent mark_1m and index_1m data from the data catalog if available

#### Scenario: Mark/index refreshed periodically
- **WHEN** 60 seconds have elapsed since the last refresh
- **THEN** the service fetches current mark and index prices from the exchange REST API

#### Scenario: Basis features populated
- **WHEN** `compute_features` is called with mark_1m and index_1m DataFrames
- **THEN** `basis`, `basis_momentum`, `annualized_funding` columns are populated (not NaN)

### Requirement: Graceful degradation when data sources unavailable
The service SHALL continue operating with partial features when trades or mark/index data is unavailable.

#### Scenario: No trades available
- **WHEN** `hb.market_trade.v1` stream is empty or not configured
- **THEN** microstructure features are NaN; all other feature groups compute normally

#### Scenario: Mark/index API unreachable
- **WHEN** the exchange REST API for mark/index prices fails
- **THEN** basis features use stale data (last known values) or NaN; service logs a warning but does not crash
