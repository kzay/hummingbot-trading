## ADDED Requirements

### Requirement: Download historical trade ticks

The system SHALL download historical trade ticks for a given exchange, trading pair, and date range using `DataDownloader.download_trades()`. Trade ticks SHALL be stored in parquet format with schema `(timestamp_ms: int64, side: str, price: float64, size: float64, trade_id: str)` at the canonical path `{base_dir}/{exchange}/{pair}/trades/data.parquet`. The download SHALL be registered in the data catalog with `resolution="trades"`.

#### Scenario: Download trade ticks for BTC-USDT

- **WHEN** the user runs `DataDownloader.download_trades("BTC/USDT:USDT", since_ms, until_ms)`
- **THEN** trade ticks are fetched from the exchange via ccxt `fetch_trades()`, stored in parquet at the canonical path, and registered in the catalog with `resolution="trades"` including `start_ms`, `end_ms`, `row_count`, and `file_size_bytes`

#### Scenario: Resume interrupted trade download with deduplication

- **WHEN** a partial trade dataset already exists in the catalog for the requested range
- **THEN** the download SHALL resume from the last `end_ms` in the existing data, appending new rows. Appended rows SHALL be deduplicated by `trade_id` (or documented stable key) when overlapping pages from the exchange could repeat ticks; duplicate keys SHALL NOT double-count in stored parquet

#### Scenario: CCXT failure after retries

- **WHEN** `fetch_trades()` fails after the configured retry/backoff cap (rate limit, network, gateway)
- **THEN** the downloader SHALL raise a clear error with exchange and symbol context and SHALL NOT write a partial catalog entry that claims full coverage

### Requirement: Download historical funding rates

The system SHALL provide a `download_funding_rates()` method on `DataDownloader` that fetches funding-rate history using ccxt's `fetch_funding_rate_history()`. Funding rates SHALL be stored in parquet with schema `(timestamp_ms: int64, rate: float64)` at `{base_dir}/{exchange}/{pair}/funding/data.parquet`. The download SHALL be registered in the catalog with `resolution="funding"`.

#### Scenario: Download funding rates for BTC-USDT

- **WHEN** the user calls `download_funding_rates("BTC/USDT:USDT", since_ms, until_ms)`
- **THEN** funding rates are fetched, stored in parquet, and registered in the catalog with `resolution="funding"`

#### Scenario: Exchange does not support funding rate history

- **WHEN** the exchange does not support `fetch_funding_rate_history()`
- **THEN** the method SHALL raise a clear error indicating funding history is not available for this exchange

#### Scenario: CCXT failure after retries for funding

- **WHEN** funding download fails after retry cap
- **THEN** the method SHALL raise with clear context and SHALL NOT register misleading catalog metadata

### Requirement: Store and load funding rates

The `DataStore` module SHALL provide `save_funding_rates(path, rates)` and `load_funding_rates(path) -> list[FundingRow]` methods. `FundingRow` SHALL be a named tuple or dataclass with fields `timestamp_ms: int` and `rate: Decimal`.

#### Scenario: Round-trip funding rate storage

- **WHEN** funding rates are saved with `save_funding_rates()` and loaded with `load_funding_rates()`
- **THEN** the loaded data SHALL match the saved data exactly (no precision loss beyond Decimal conversion)

#### Scenario: Funding floor-search edge cases

- **WHEN** funding rates are loaded and queried at a timestamp before the first rate, at an exact rate timestamp, and in a gap between rates
- **THEN** the documented floor-search behavior SHALL match harness expectations (e.g. zero or last known rate per design)

### Requirement: Catalog supports trades and funding resolution

The `DataCatalog` SHALL accept entries with `resolution="trades"` and `resolution="funding"` in addition to the existing candle resolutions (`1m`, `5m`, etc.). The `find()` method SHALL support filtering by these resolutions.

#### Scenario: Find trade data in catalog

- **WHEN** `catalog.find(exchange="bitget", pair="BTC-USDT", resolution="trades")` is called
- **THEN** the catalog SHALL return the matching entry with `file_path`, `start_ms`, `end_ms`, and `row_count`

#### Scenario: Find funding data in catalog

- **WHEN** `catalog.find(exchange="bitget", pair="BTC-USDT", resolution="funding")` is called
- **THEN** the catalog SHALL return the matching entry

#### Scenario: Duplicate catalog entries disambiguated

- **WHEN** more than one catalog entry matches the same `(exchange, pair, resolution)` query
- **THEN** `find()` SHALL either return the single best match by documented rule (e.g. narrowest range containing the requested window, or newest `registered_at`) or SHALL raise with instructions to resolve ambiguity — it SHALL NOT silently pick an arbitrary file

#### Scenario: Corrupt or missing parquet

- **WHEN** a catalog entry points to a missing file or unreadable parquet
- **THEN** load SHALL fail fast with a path and clear error

### Requirement: Cross-stream date range alignment

When candles, trades, and funding are loaded for a replay window, the system SHALL validate coverage. **Default policy for v1 (full-fidelity replay):** if trades are required by the replay config and the trade dataset does not cover `[start_date, end_date]` (per candle alignment rules), the harness SHALL fail fast. If funding is required and missing for part of the window, the harness SHALL fail fast or run in an explicit **degraded mode** only when `replay.allow_missing_funding: true` (or equivalent) is set, and the result SHALL include `degraded: true` and list missing intervals.

#### Scenario: Trades shorter than candle range

- **WHEN** candles cover the full replay range but trades end before `end_date` and trades are required
- **THEN** the replay SHALL NOT complete as success without degraded flag; it SHALL fail fast unless degraded mode is explicitly enabled in config

#### Scenario: Optional degraded mode documented

- **WHEN** `replay.allow_missing_trades: true` is set (if ever supported)
- **THEN** the result SHALL include `degraded: true` and limitations SHALL state trade-flow signals are unreliable

### Requirement: CLI command for data download

A CLI entry point SHALL allow downloading candles, trades, and funding rates in a single command or individually. The CLI SHALL accept exchange, pair, date range, and data types. Date arguments SHALL be documented as UTC end-of-day or ISO-8601 with timezone as implemented.

#### Scenario: Download all data types

- **WHEN** the user runs the download CLI with `--types candles,trades,funding`
- **THEN** all three data types are downloaded, stored, and cataloged

#### Scenario: Download only trades

- **WHEN** the user runs the download CLI with `--types trades`
- **THEN** only trade ticks are downloaded
