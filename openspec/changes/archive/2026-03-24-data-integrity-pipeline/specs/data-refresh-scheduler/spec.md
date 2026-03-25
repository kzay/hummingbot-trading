## ADDED Requirements

### Requirement: Automated incremental canonical dataset refresh
The system SHALL periodically download new canonical market datasets from the exchange, append them to existing parquet files without re-downloading already-stored rows, and materialize derived higher-timeframe datasets locally.

#### Scenario: Incremental download appends new canonical bars
- **WHEN** the data-refresh job runs and the catalog shows BTC-USDT 1m data ending at timestamp T
- **THEN** the system SHALL download canonical rows from T to now, merge them with existing data (deduplicating by timestamp_ms), validate the combined dataset, save the updated parquet, and re-register in the catalog with the new end_ms and row_count

#### Scenario: First run uses bootstrap policy
- **WHEN** the data-refresh job runs and no catalog entry exists for a configured pair/dataset
- **THEN** the system SHALL download rows from the consumer-defined bootstrap start to now, save to parquet, and register in the catalog

#### Scenario: Exchange API failure during download
- **WHEN** the exchange API returns transient errors (429, 502, 503, 504, timeout) during incremental download
- **THEN** the system SHALL retry with exponential backoff up to 5 attempts per batch, log the failure, and continue with the next pair/dataset without crashing

### Requirement: Higher-timeframe materialization from canonical 1m
The system SHALL materialize `5m`, `15m`, and `1h` parquet datasets locally from canonical `1m` candles instead of downloading those higher timeframes independently from the exchange.

#### Scenario: Materialize 5m after 1m refresh
- **WHEN** BTC-USDT 1m candles are refreshed successfully
- **THEN** the system SHALL rebuild or incrementally materialize BTC-USDT 5m candles from the canonical 1m file and register the resulting `5m` parquet in the catalog

#### Scenario: Materialized datasets stay aligned with 1m
- **WHEN** the canonical 1m dataset contains no gaps across a time range
- **THEN** the locally materialized 5m, 15m, and 1h datasets SHALL align exactly to that 1m history with deterministic bar boundaries

### Requirement: ops-scheduler integration
The system SHALL run the data-refresh job as a scheduled task within the existing ops-scheduler service.

#### Scenario: Periodic execution
- **WHEN** the ops-scheduler is running
- **THEN** the data-refresh job SHALL execute at the interval specified by `DATA_REFRESH_INTERVAL_SEC` (default 21600 = 6 hours)

#### Scenario: Job isolation
- **WHEN** the data-refresh job crashes or times out
- **THEN** other ops-scheduler jobs SHALL continue running unaffected, and the data-refresh job SHALL be retried at the next interval

### Requirement: Gap detection in stored data
The system SHALL scan parquet files after each incremental download to detect gaps (missing bars) larger than a configurable threshold.

#### Scenario: Gaps detected and reported
- **WHEN** the system scans a parquet file and finds 3 missing 1m bars between timestamps A and B
- **THEN** the system SHALL log a warning with the gap location, size in minutes, and count of gaps found

#### Scenario: No gaps found
- **WHEN** the system scans a parquet file and all consecutive bars are within the expected interval
- **THEN** the system SHALL log an info message confirming zero gaps

### Requirement: Automatic gap backfill
The system SHALL attempt to repair detected gaps by fetching the missing bars from the exchange API.

#### Scenario: Successful gap repair
- **WHEN** gaps are detected and the exchange API has data for the missing range
- **THEN** the system SHALL download the missing bars, merge into the parquet file (deduplicating), re-validate, and re-register in the catalog

#### Scenario: Gap cannot be repaired
- **WHEN** the exchange API does not have data for a gap range (exchange was down, data too old)
- **THEN** the system SHALL log a warning that the gap could not be repaired and continue with the remaining gaps

### Requirement: Configurable pairs and datasets
The system SHALL accept configuration for which exchange/pair/dataset combinations to refresh.

#### Scenario: Environment variable configuration
- **WHEN** `DATA_REFRESH_PAIRS=BTC-USDT,ETH-USDT`, `DATA_REFRESH_EXCHANGE=bitget`, and `DATA_REFRESH_DATASETS=1m,mark_1m,index_1m,funding,ls_ratio` are set
- **THEN** the system SHALL refresh data for all configured canonical dataset combinations and materialize any configured derived datasets locally

#### Scenario: Default configuration
- **WHEN** no `DATA_REFRESH_*` env vars are set
- **THEN** the system SHALL default to exchange=bitget, pairs=BTC-USDT, resolutions=1m
