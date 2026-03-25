## ADDED Requirements

### Requirement: PriceBuffer SHALL compute MACD indicator
PriceBuffer SHALL provide a `macd(fast, slow, signal)` method that returns
a tuple `(macd_line, signal_line, histogram)` where:
- `macd_line = EMA(fast) - EMA(slow)`
- `signal_line = EMA(signal) applied to the MACD line series`
- `histogram = macd_line - signal_line`

All values SHALL be `Decimal`. The method SHALL return `None` when fewer
than `max(fast, slow) + signal` completed bars are available.

#### Scenario: MACD with default parameters
- **WHEN** PriceBuffer has sufficient completed bars for `macd(12, 26, 9)`
- **THEN** a tuple of three Decimal values `(macd_line, signal_line, histogram)` is returned
- **AND** `histogram` equals `macd_line - signal_line`

#### Scenario: MACD returns None during warmup
- **WHEN** PriceBuffer has fewer than `max(fast, slow) + signal` completed bars
- **THEN** `macd()` returns `None`

#### Scenario: MACD is cached per bar count
- **WHEN** `macd(12, 26, 9)` is called twice without a new bar
- **THEN** the second call returns the cached result without recomputation

### Requirement: PriceBuffer SHALL compute Stochastic RSI
PriceBuffer SHALL provide a `stoch_rsi(rsi_period, stoch_period, k_smooth,
d_smooth)` method that returns a tuple `(k_line, d_line)` where:
- RSI is computed over `rsi_period` using the existing `rsi()` method
- K = `(RSI - lowest_RSI) / (highest_RSI - lowest_RSI)` over `stoch_period`, scaled 0-100
- K is smoothed with SMA of `k_smooth`
- D = SMA of K over `d_smooth`

All values SHALL be `Decimal`. The method SHALL return `None` when
insufficient bars are available.

#### Scenario: Stochastic RSI with default parameters
- **WHEN** PriceBuffer has sufficient completed bars for `stoch_rsi(14, 14, 3, 3)`
- **THEN** a tuple `(k_line, d_line)` is returned with both values in range [0, 100]

#### Scenario: Stochastic RSI returns None during warmup
- **WHEN** PriceBuffer has fewer than the bars required to compute the RSI series, rolling stochastic window, and both smoothing stages
- **THEN** `stoch_rsi()` returns `None`

#### Scenario: Stochastic RSI handles flat price
- **WHEN** all close prices are identical (highest_RSI == lowest_RSI)
- **THEN** `stoch_rsi()` returns `(Decimal("50"), Decimal("50"))` instead of division by zero

### Requirement: New indicators SHALL follow PriceBuffer conventions
Both `macd()` and `stoch_rsi()` SHALL:
- Accept indicator periods as positional `int` arguments
- Return `Decimal` values (or tuples of `Decimal`)
- Return `None` when warmup bars are insufficient
- Be cached per `_bar_count` to avoid recomputation within the same bar
- Work correctly at all supported resolutions (1, 5, 15, 60 minutes)

#### Scenario: MACD works at 15m resolution
- **WHEN** PriceBuffer is initialized with `resolution_minutes=15` and has enough resampled bars
- **THEN** `macd()` returns values computed from 15m resampled bars

#### Scenario: Stochastic RSI works at 15m resolution
- **WHEN** PriceBuffer is initialized with `resolution_minutes=15`
- **THEN** `stoch_rsi()` returns values computed from 15m resampled bars
