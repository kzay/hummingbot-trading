## ADDED Requirements

### Requirement: PriceBuffer is resolution-aware at construction

PriceBuffer SHALL accept `resolution_minutes: int = 1` in its constructor. Supported values: 1, 5, 15, 60. Any other value SHALL raise `ValueError`. PriceBuffer SHALL expose `resolution_minutes` as a read-only property.

Internally, PriceBuffer SHALL always store 1-minute bars in `_1m_store`. When `resolution_minutes == 1`, ALL behavior is identical to today (zero performance overhead, zero regression risk). When `resolution_minutes > 1`, indicator methods operate on cached resampled bars automatically.

#### Scenario: Construction with default resolution

- **WHEN** `PriceBuffer()` is created without specifying resolution
- **THEN** `resolution_minutes == 1` and ALL behavior is identical to current implementation

#### Scenario: Construction with 15m resolution

- **WHEN** `PriceBuffer(resolution_minutes=15)` is created
- **THEN** `resolution_minutes == 15`; `bars` returns 15m resampled bars; `bars_1m` returns raw 1m bars

#### Scenario: Construction with unsupported resolution

- **WHEN** `PriceBuffer(resolution_minutes=3)` is created
- **THEN** `ValueError` is raised

### Requirement: `_indicator_bars` returns resolution-appropriate bars

PriceBuffer SHALL expose an internal `_indicator_bars` property used by ALL indicator methods. When `resolution_minutes == 1`, it SHALL return `_1m_store` directly (no copy, no overhead). When `resolution_minutes > 1`, it SHALL return a cached list of resampled bars, invalidated when `_1m_bar_count` changes.

ALL read paths in indicator methods (`ema`, `atr`, `sma`, `stddev`, `bollinger_bands`, `rsi`, `adx`, `ready`, `latest_close`, `closes`, `bars`) SHALL use `_indicator_bars` instead of the raw 1m store. NO indicator method signature changes.

#### Scenario: Indicator reads at resolution=1

- **WHEN** `PriceBuffer(resolution_minutes=1)` has 400 bars
- **THEN** `len(_indicator_bars) == 400`; `bollinger_bands(20)` computes on 400 one-minute bars
- **THEN** behavior is identical to current implementation

#### Scenario: Indicator reads at resolution=15

- **WHEN** `PriceBuffer(resolution_minutes=15)` has 400 one-minute bars stored
- **THEN** `len(_indicator_bars) == 26` (400 / 15 complete bars); `bollinger_bands(20)` computes on 26 fifteen-minute bars

### Requirement: Resampling aggregation correctness

The resampling method SHALL aggregate 1m bars into higher-TF bars aligned to wall-clock boundaries. For 15m: timestamps aligned to minutes 0, 15, 30, 45. Each resampled bar: first open, max high, min low, last close of constituent 1m bars. The current forming (incomplete) resolution bar SHALL be included as the final bar (so indicators always have access to the latest price).

#### Scenario: OHLCV aggregation

- **WHEN** 15 consecutive 1m bars (opens: 100..114, highs: 101..115, lows: 99..113, closes: 100.5..114.5) are resampled at 15m
- **THEN** one bar with open=100, high=max(highs), low=min(lows), close=114.5

#### Scenario: Incomplete trailing bar included

- **WHEN** PriceBuffer has 37 one-minute bars and resolution is 15m
- **THEN** `_indicator_bars` returns 2 complete fifteen-minute bars + 1 forming bar (7 minutes)

### Requirement: `bars` returns resolution bars; `bars_1m` returns raw 1m bars

- `bars` property SHALL return `_indicator_bars` (resolution-appropriate bars)
- `bars_1m` property SHALL return `list(_1m_store)` always (raw 1m regardless of resolution)
- When `resolution_minutes == 1`, `bars` and `bars_1m` return identical data

### Requirement: EMA/ATR cache management at resolution level

When `resolution_minutes > 1`, `_bar_count` SHALL increment per resolution bar boundary (not per 1m bar). On each resolution bar boundary, `_ema_values` and `_atr_values` SHALL be cleared, causing the next `ema()`/`atr()` call to trigger lazy cold-start recomputation from the resampled bars.

When `resolution_minutes == 1`, `_bar_count` increments per 1m bar and EMA/ATR are updated incrementally — identical to current behavior.

### Requirement: adverse_drift_30s unaffected

`adverse_drift_30s` and `adverse_drift_smooth` SHALL continue to use `_samples` only. They SHALL NOT reference bar resolution. This is verified by test.

### Requirement: PriceBuffer minimum bars helper

PriceBuffer SHALL expose a `min_bars_for_resolution(period: int, resolution_minutes: int) -> int` class method returning `period * resolution_minutes` — the minimum number of 1m bars needed.

#### Scenario: Minimum bars for BB(20) at 15m

- **WHEN** `PriceBuffer.min_bars_for_resolution(20, 15)` is called
- **THEN** result is 300
