## ADDED Requirements

### Requirement: Centralized data requirements manifest
The system SHALL maintain a single YAML file (`config/data_requirements.yml`) that declares what historical data each consumer needs, including required lookback, bootstrap/retention policy, canonical datasets, materialized datasets, pairs, and the rationale for each requirement.

#### Scenario: Manifest defines ML feature service requirements
- **WHEN** the manifest is read
- **THEN** it SHALL contain an entry for `ml_feature_service` specifying `required_lookback_bars: 20160`, `bootstrap_from`, `canonical_datasets: ["1m"]`, `pairs: ["BTC-USDT"]`, `exchange: bitget`, and a `derived_from` annotation explaining the source of the lookback number (e.g., "feature_pipeline atr_pctl_7d = rolling(10080) * 2x buffer")

#### Scenario: Manifest defines backtesting requirements
- **WHEN** the manifest is read
- **THEN** it SHALL contain an entry for `backtesting` specifying `required_lookback_bars`, `retention_policy: "full_history"`, `canonical_datasets: ["1m"]`, `materialized_datasets: ["5m", "15m", "1h"]`, all configured pairs, warmup_bars, and exchange

#### Scenario: Manifest defines ML training requirements
- **WHEN** the manifest is read
- **THEN** it SHALL contain an entry for `ml_training` specifying `required_lookback_bars`, `retention_policy: "full_history"`, `canonical_datasets: ["1m", "mark_1m", "index_1m", "funding", "ls_ratio"]`, `materialized_datasets: ["5m", "15m", "1h"]`, all pairs used for training, `min_rows: 1000`, and exchange

#### Scenario: Manifest defines strategy controller requirements
- **WHEN** the manifest is read
- **THEN** it SHALL contain an entry for `strategy_controller` specifying `required_lookback_bars: 60`, `canonical_datasets: ["1m"]`, `source: "live_stream"` (indicating it does not use the parquet store), and exchange

### Requirement: Refresh pipeline derives scope from manifest
The data refresh script SHALL read the manifest to compute the union of all consumer requirements when determining what data to download.

#### Scenario: Pairs and canonical datasets computed from union
- **WHEN** the data refresh script starts and the manifest declares `ml_feature_service` needing canonical `["1m"]` for `["BTC-USDT"]` and `ml_training` needing canonical `["1m", "mark_1m", "index_1m", "funding", "ls_ratio"]` for `["BTC-USDT", "ETH-USDT"]`
- **THEN** the refresh script SHALL fetch canonical datasets `["1m", "mark_1m", "index_1m", "funding", "ls_ratio"]` for pairs `["BTC-USDT", "ETH-USDT"]`

#### Scenario: Materialized datasets derived locally
- **WHEN** the manifest declares `materialized_datasets: ["5m", "15m", "1h"]`
- **THEN** the refresh pipeline SHALL derive those datasets locally from canonical `1m` data instead of downloading them independently from the exchange

#### Scenario: Bootstrap and retention separated from minimum lookback
- **WHEN** the manifest declares `required_lookback_bars: 20160` and `bootstrap_from: "90d"`
- **THEN** the refresh script SHALL ensure at least 20,160 bars are always available for the consumer and SHALL use the bootstrap/retention policy to determine how much history to fetch/store beyond that minimum

#### Scenario: Manifest missing or invalid
- **WHEN** `config/data_requirements.yml` does not exist or cannot be parsed
- **THEN** the refresh script SHALL fall back to env var configuration (`DATA_REFRESH_PAIRS`, `DATA_REFRESH_RESOLUTIONS`, `DATA_REFRESH_EXCHANGE`) and log a warning

### Requirement: Consumer startup self-validation
Each consumer that reads from the parquet store SHALL validate at startup that the available data meets its manifest-declared requirements.

#### Scenario: Sufficient data available
- **WHEN** the ML feature service starts and the parquet store contains 639,360 bars of 1m BTC-USDT data, exceeding the manifest's `lookback_bars: 20160`
- **THEN** the service SHALL log an info message confirming data coverage is sufficient

#### Scenario: Insufficient data available
- **WHEN** the ML feature service starts and the parquet store contains only 5,000 bars of 1m data, less than `lookback_bars: 20160`
- **THEN** the service SHALL log a warning indicating partial coverage (5,000 of 20,160 bars) and proceed with available data

#### Scenario: Consumer not in manifest
- **WHEN** a consumer starts but has no entry in the manifest
- **THEN** the consumer SHALL skip manifest validation and proceed normally (backward compatible)
