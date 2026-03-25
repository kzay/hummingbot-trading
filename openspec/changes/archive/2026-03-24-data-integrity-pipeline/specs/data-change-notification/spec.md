## ADDED Requirements

### Requirement: Data catalog event stream
The system SHALL publish events to a Redis stream (`hb.data_catalog.v1`) whenever historical data is successfully updated in the catalog.

#### Scenario: Event published after incremental download
- **WHEN** the data refresh script successfully downloads new bars for BTC-USDT 1m, merges them into the parquet, and registers in the catalog
- **THEN** the system SHALL publish a `DataCatalogEvent` to `hb.data_catalog.v1` containing: `event_type: "data_catalog_updated"`, `producer: "data_refresh"`, `exchange`, `pair`, `resolution`, `start_ms`, `end_ms`, `row_count`, `gaps_found`, `gaps_repaired`, and `timestamp_ms`

#### Scenario: Event published after gap repair
- **WHEN** the data refresh script detects and repairs 3 gaps in BTC-USDT 1m data
- **THEN** the published event SHALL include `gaps_found: 3` and `gaps_repaired: 3` (or less if some could not be repaired)

#### Scenario: No event on failed download
- **WHEN** the data refresh script fails to download new bars (API unreachable, all retries exhausted)
- **THEN** no event SHALL be published to `hb.data_catalog.v1`

### Requirement: Stream name registration
The data catalog stream SHALL be registered in the canonical stream names module.

#### Scenario: Stream constant defined
- **WHEN** the `platform_lib/contracts/stream_names.py` module is loaded
- **THEN** it SHALL export `DATA_CATALOG_STREAM = "hb.data_catalog.v1"` and include it in `STREAM_RETENTION_MAXLEN` with a default maxlen of 1,000

### Requirement: ML feature service subscribes to data catalog events
The ML feature service SHALL optionally subscribe to `hb.data_catalog.v1` to hot-reload historical data without restart.

#### Scenario: Hot-reload triggered by data update event
- **WHEN** the ML feature service receives a `data_catalog_updated` event for its configured pair and "1m" resolution
- **THEN** the service SHALL re-read the parquet tail, combine it with currently retained live bars, rebuild the rolling window from the sorted unique union, keep the newest `ML_ROLLING_WINDOW` bars, and log "Hot-reloaded N bars from parquet for {pair}"

#### Scenario: Irrelevant event ignored
- **WHEN** the ML feature service receives a `data_catalog_updated` event for a pair it is not configured to serve (e.g., ETH-USDT when only BTC-USDT is configured)
- **THEN** the service SHALL ignore the event

#### Scenario: Hot-reload does not disrupt live bar building
- **WHEN** the ML feature service hot-reloads from parquet while simultaneously building bars from the live trade stream
- **THEN** the hot-reload SHALL preserve the newest live bars, SHALL not mutate the bounded deque by prepending into a full window, and live bar building SHALL continue uninterrupted

#### Scenario: Fallback periodic parquet check
- **WHEN** Redis is temporarily unavailable and the data catalog event is missed
- **THEN** the ML feature service SHALL check parquet freshness every `ML_REFRESH_INTERVAL_S` (default 3600s) as a fallback, re-reading the parquet tail if the file's last bar is newer than what was previously loaded
