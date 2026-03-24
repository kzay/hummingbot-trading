## ADDED Requirements

### Requirement: Filtered candle loader preserves domain row contract
`data_store.py` SHALL provide a timestamp-filtered candle loader that reads only the requested parquet window and returns `list[CandleRow]`.

#### Scenario: Load requested candle window only
- **WHEN** a caller requests candles for a bounded `[start_ms, end_ms]` range
- **THEN** the loader SHALL apply parquet timestamp filters before materializing rows
- **AND** it SHALL return only `CandleRow` objects whose `timestamp_ms` values fall within the requested range

#### Scenario: Existing full-file candle loader remains available
- **WHEN** `load_candles()` is called without a range
- **THEN** it SHALL continue to return the full file as `list[CandleRow]`

#### Scenario: Filtered candle loader preserves chronological order
- **WHEN** the filtered candle loader returns rows for a bounded time window
- **THEN** the returned `CandleRow` objects SHALL remain ordered by `timestamp_ms` ascending

### Requirement: Filtered trade and funding loaders preserve domain row contracts
`data_store.py` SHALL provide timestamp-filtered trade and funding loaders that return `list[TradeRow]` and `list[FundingRow]` respectively.

#### Scenario: Load requested trade window only
- **WHEN** a caller requests trades for a bounded `[start_ms, end_ms]` range
- **THEN** the loader SHALL apply parquet timestamp filters before materializing rows
- **AND** it SHALL return only `TradeRow` objects within the requested range

#### Scenario: Load requested funding window only
- **WHEN** a caller requests funding rows for a bounded `[start_ms, end_ms]` range
- **THEN** the loader SHALL apply parquet timestamp filters before materializing rows
- **AND** it SHALL return only `FundingRow` objects within the requested range

#### Scenario: Filtered loaders preserve chronological order
- **WHEN** the filtered trade or funding loader returns rows
- **THEN** the returned rows SHALL remain ordered by `timestamp_ms` ascending

### Requirement: Backtest harness uses filtered window loading
`harness.py` SHALL request only the configured date window from parquet storage and SHALL continue to return `list[CandleRow]` from its internal loading helper.

#### Scenario: Harness clips at storage boundary
- **WHEN** the backtest harness loads historical candles for a configured start and end date
- **THEN** it SHALL use the filtered parquet loader instead of loading the full file and filtering in Python
- **AND** the returned value SHALL remain compatible with existing downstream `CandleRow` consumers

### Requirement: Replay harness uses filtered window loading
`replay_harness.py` SHALL request only the configured date window from parquet storage for candles, trades, and funding, while preserving existing replay domain-row types.

#### Scenario: Replay uses filtered parquet loading
- **WHEN** the replay harness prepares market data for a date window
- **THEN** it SHALL use filtered parquet loaders for candles, trades, and funding
- **AND** it SHALL preserve `list[CandleRow]`, `list[TradeRow]`, and `list[FundingRow]` outputs for downstream replay components

### Requirement: Walk-forward compatibility is preserved
Optimization of the harness read path SHALL NOT break `walkforward.py` assumptions about `BacktestHarness._load_candles()` returning sliceable candle-domain rows that can be passed to `save_candles()`.

#### Scenario: Walk-forward still slices harness candles
- **WHEN** `walkforward.py` calls `BacktestHarness._load_candles()`
- **THEN** it SHALL receive a sliceable candle-domain sequence compatible with `save_candles()`

### Requirement: Catalog lookup is range-aware for duplicate datasets
Historical dataset lookup SHALL choose the dataset that best satisfies the requested `(exchange, pair, resolution, start_ms, end_ms)` window rather than always preferring the narrowest registered range.

#### Scenario: Prefer dataset that fully covers requested window
- **WHEN** multiple datasets exist for the same `(exchange, pair, resolution)`
- **AND** one dataset fully covers the requested time window while another narrower dataset does not
- **THEN** the lookup SHALL return the dataset that fully covers the requested window

#### Scenario: Prefer newest among equally suitable datasets
- **WHEN** multiple datasets exist for the same `(exchange, pair, resolution)` and coverage suitability is equal
- **THEN** the lookup SHALL prefer the newest registration
