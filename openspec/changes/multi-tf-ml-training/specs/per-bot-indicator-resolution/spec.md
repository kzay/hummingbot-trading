## ADDED Requirements

### Requirement: Bot config includes indicator_resolution field

`SharedMmV24Config` and `DirectionalRuntimeConfig` SHALL include an `indicator_resolution` field of type `str` with default `"1m"`. Valid values SHALL be `"1m"`, `"5m"`, `"15m"`, and `"1h"`. Invalid values SHALL raise a `ValidationError`.

#### Scenario: Default resolution is 1m

- **WHEN** a config is created without specifying `indicator_resolution`
- **THEN** `indicator_resolution` is `"1m"`

#### Scenario: Bot7 config sets 15m resolution

- **WHEN** a config is created with `indicator_resolution: "15m"`
- **THEN** the field stores `"15m"` and validation passes

#### Scenario: Invalid resolution rejected

- **WHEN** a config is created with `indicator_resolution: "3m"`
- **THEN** pydantic raises a `ValidationError`

### Requirement: price_buffer_bars auto-adjusts for resolution

When `indicator_resolution` requires more 1m bars than the configured `price_buffer_bars`, the runtime SHALL log a warning and auto-adjust `price_buffer_bars` upward to ensure sufficient bars. The minimum is `max_indicator_period * resolution_minutes * 2`.

#### Scenario: Buffer auto-adjusted for 15m with BB(20)

- **WHEN** `indicator_resolution: "15m"` and `price_buffer_bars: 200` and indicators require period 20
- **THEN** runtime logs a warning and increases internal buffer to at least 600 bars (20 × 15 × 2)

#### Scenario: Buffer sufficient for 1m

- **WHEN** `indicator_resolution: "1m"` and `price_buffer_bars: 200`
- **THEN** no adjustment is needed

### Requirement: Regime detection uses bot indicator_resolution

The regime detection path in `regime_mixin.py` SHALL use the bot's `indicator_resolution` when fetching OHLCV data and computing EMA/ATR/band_pct inputs to the RegimeDetector, instead of the hardcoded `"1m"`.

#### Scenario: Regime computed on 15m OHLCV for bot7

- **WHEN** bot7 has `indicator_resolution: "15m"` and `candles_connector` is configured
- **THEN** `_get_ohlcv_ema_and_atr` fetches `"15m"` candles and computes EMA/band_pct on 15m bars

#### Scenario: Regime computed on 1m OHLCV for bot1

- **WHEN** bot1 has `indicator_resolution: "1m"` (default)
- **THEN** `_get_ohlcv_ema_and_atr` fetches `"1m"` candles (unchanged behavior)

#### Scenario: Regime from price_buffer uses indicator_resolution

- **WHEN** no `candles_connector` is set and `indicator_resolution` is `"15m"`
- **THEN** regime inputs (band_pct, ema) are read from `_price_buffer` which was constructed with `resolution_minutes=15`; no per-call resolution parameter needed — the buffer's `ema()`, `atr()`, `band_pct()` automatically operate on 15m bars

### Requirement: SharedRuntimeKernel passes resolution to PriceBuffer

`SharedRuntimeKernel` SHALL parse `_resolution_minutes` from `config.indicator_resolution` and pass `resolution_minutes=self._resolution_minutes` to the `PriceBuffer()` constructor. This is the ONLY place resolution is threaded — all downstream code uses the buffer's built-in resolution.

#### Scenario: Kernel constructs 15m PriceBuffer

- **WHEN** config has `indicator_resolution: "15m"`
- **THEN** `self._price_buffer = PriceBuffer(resolution_minutes=15, max_minutes=config.price_buffer_bars)`
- **THEN** `self._price_buffer.resolution_minutes == 15`
- **THEN** `self._price_buffer.bars` returns 15m bars
- **THEN** all strategy code using `self._price_buffer.bollinger_bands(20)` etc. operates on 15m with ZERO code changes
