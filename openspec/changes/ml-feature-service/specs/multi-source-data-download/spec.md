## ADDED Requirements

### Requirement: Download mark price candles
The DataDownloader SHALL support downloading mark-price OHLCV candles for any ccxt-supported pair and timeframe by passing `params={"price": "mark"}` to `fetch_ohlcv`. The downloaded data SHALL be persisted as Parquet under `{base_dir}/{exchange}/{pair}/mark_{resolution}/data.parquet` and registered in the DataCatalog with resolution `mark_{timeframe}`.

#### Scenario: Download BTC-USDT mark candles
- **WHEN** `download_mark_candles("BTC/USDT:USDT", "1m", since_ms, until_ms)` is called
- **THEN** the method returns a list of `CandleRow` objects with mark prices and persists them to `mark_1m/data.parquet`

#### Scenario: Mark candle catalog registration
- **WHEN** mark candles are downloaded and saved
- **THEN** the DataCatalog contains an entry with `resolution="mark_1m"` and correct `start_ms`, `end_ms`, `row_count`

### Requirement: Download index price candles
The DataDownloader SHALL support downloading index-price OHLCV candles by passing `params={"price": "index"}` to `fetch_ohlcv`. Persistence path SHALL be `index_{resolution}/data.parquet`.

#### Scenario: Download BTC-USDT index candles
- **WHEN** `download_index_candles("BTC/USDT:USDT", "1m", since_ms, until_ms)` is called
- **THEN** the method returns a list of `CandleRow` objects with index prices and persists them to `index_1m/data.parquet`

### Requirement: Download long/short ratio history
The DataDownloader SHALL support downloading historical long/short ratio data via `fetch_long_short_ratio_history()`. A new `LongShortRatioRow` type SHALL hold `timestamp_ms`, `long_account_ratio`, `short_account_ratio`, `long_short_ratio`. Data SHALL be persisted as Parquet under `ls_ratio/data.parquet`.

#### Scenario: Download BTC-USDT LS ratio
- **WHEN** `download_long_short_ratio("BTC/USDT:USDT", "5m", since_ms, until_ms)` is called
- **THEN** the method returns a list of `LongShortRatioRow` objects sorted by timestamp

#### Scenario: Exchange does not support LS ratio
- **WHEN** the exchange does not advertise `fetchLongShortRatioHistory` capability
- **THEN** the method raises `NotImplementedError` with a descriptive message

### Requirement: Multi-resolution download
The CLI SHALL accept a comma-separated `--resolution` argument (e.g., `--resolution 1m,5m,15m,1h`) and download candles at each resolution in sequence for the same pair and date range.

#### Scenario: Download multiple resolutions
- **WHEN** `--resolution 1m,5m,15m,1h` is passed to the CLI
- **THEN** candles are downloaded and registered separately for each resolution, producing 4 Parquet files

### Requirement: Multi-type download
The CLI SHALL accept a comma-separated `--types` argument supporting `candles,mark,index,trades,funding,ls_ratio`. Each type is downloaded independently.

#### Scenario: Download all types
- **WHEN** `--types candles,mark,index,trades,funding,ls_ratio` is passed
- **THEN** all 6 data types are downloaded, persisted, and registered in the catalog

### Requirement: Download orchestration with resume
Each download method SHALL support `resume_from_ms` for interrupted downloads, consistent with the existing `download_candles` pattern. The `download_and_register_*` convenience methods SHALL merge existing and new data, deduplicate, and update the catalog entry.

#### Scenario: Resume interrupted mark candle download
- **WHEN** a mark candle download is interrupted and restarted with `resume=True`
- **THEN** only data after the last downloaded timestamp is fetched, merged with existing data, and the catalog entry is updated

### Requirement: Data store persistence for new types
`data_store.py` SHALL provide `save_long_short_ratio()` and `load_long_short_ratio()` functions that serialize `LongShortRatioRow` lists to/from Parquet. Mark and index candles SHALL reuse existing `save_candles()` / `load_candles()` with different file paths.

#### Scenario: Round-trip LS ratio data
- **WHEN** a list of `LongShortRatioRow` is saved with `save_long_short_ratio()` and loaded with `load_long_short_ratio()`
- **THEN** the loaded data matches the saved data exactly (field values and order)

### Requirement: Direct DataFrame loading for ML pipeline
`data_store.py` SHALL provide a `load_candles_df()` function that reads a candle Parquet file directly into a pandas DataFrame with float64 columns (`timestamp_ms`, `open`, `high`, `low`, `close`, `volume`), bypassing the CandleRow / Decimal conversion. This avoids the performance overhead of Decimal round-trips on large datasets used by the ML pipeline.

#### Scenario: Load candles as DataFrame
- **WHEN** `load_candles_df(path)` is called on a Parquet file saved by `save_candles()`
- **THEN** the returned DataFrame has float64 columns and the same row count as `load_candles()` would return

#### Scenario: Values match within float precision
- **WHEN** `load_candles_df()` and `load_candles()` are called on the same file
- **THEN** the float64 values from the DataFrame match the Decimal values from CandleRow within float64 precision
