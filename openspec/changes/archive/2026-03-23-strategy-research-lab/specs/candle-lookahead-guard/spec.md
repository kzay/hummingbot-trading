## ADDED Requirements

### Requirement: VisibleCandleRow wrapper

The system SHALL define a `VisibleCandleRow` class in `hbot/controllers/backtesting/types.py` that wraps a `CandleRow` and a `step_index` / `max_step` pair. When `step_index < max_step`, accessing `.high`, `.low`, or `.close` SHALL return `math.nan`. When `step_index == max_step`, all fields delegate to the underlying `CandleRow`. The `.open`, `.volume`, `.timestamp_ms`, and any other non-OHLC fields SHALL always delegate.

#### Scenario: Early step masks future values
- **WHEN** `VisibleCandleRow(candle, step_index=0, max_step=3)` is created
- **THEN** `.high` returns `math.nan`, `.low` returns `math.nan`, `.close` returns `math.nan`, `.open` returns the real open

#### Scenario: Final step exposes all values
- **WHEN** `VisibleCandleRow(candle, step_index=3, max_step=3)` is created
- **THEN** `.high`, `.low`, `.close` all return the real values

#### Scenario: NaN propagation catches misuse
- **WHEN** an adapter computes `spread = candle.high - candle.low` at step 0
- **THEN** the result is `math.nan`, making the error detectable in metrics

### Requirement: Harness integration

`BacktestHarness._run_impl` SHALL pass `VisibleCandleRow` (not raw `CandleRow`) to `adapter.tick()`. The `step_index` and `max_step` SHALL be derived from `HistoricalDataFeed.get_step_info()`.

#### Scenario: Adapter receives guarded candle
- **WHEN** the harness calls `adapter.tick(...)` during the time loop
- **THEN** the `candle` argument is a `VisibleCandleRow` instance

### Requirement: Backward compatibility flag

The system SHALL support an `allow_full_candle: bool` field on `BacktestConfig` (default `False`). When `True`, the harness passes the raw `CandleRow` instead of `VisibleCandleRow`, preserving existing adapter behavior during migration.

#### Scenario: Legacy mode
- **WHEN** `allow_full_candle=True` is set in the config
- **THEN** adapters receive the raw `CandleRow` as before
