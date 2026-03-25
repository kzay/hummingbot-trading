## ADDED Requirements

### Requirement: Bot7 operates on 15m indicator resolution

Bot7's YAML config SHALL set `indicator_resolution: "15m"`. The kernel constructs `PriceBuffer(resolution_minutes=15)`. All pullback indicator calls in `pullback_v1.py` (BB, RSI, ADX, ATR) automatically operate on 15m resampled bars with ZERO code changes to pullback_v1.py.

#### Scenario: Bot7 indicators computed on 15m bars

- **WHEN** bot7 starts with `indicator_resolution: "15m"` and the price buffer has 400+ 1m bars
- **THEN** `self._price_buffer.bollinger_bands(20, 2)` computes on 15m bars; `self._price_buffer.rsi(14)` computes on 15m bars — no code changes in pullback_v1.py

#### Scenario: Bot7 warmup requires sufficient 15m bars

- **WHEN** bot7 starts and the price buffer has fewer than 300 1m bars (< 20 fifteen-minute bars)
- **THEN** bot7 reports indicators as not ready and does not generate entry signals

### Requirement: Bot7 executor parameters recalibrated for 15m scale

Bot7's executor parameters SHALL be adjusted to match 15m bar scale:
- `time_limit` SHALL be increased to allow trades to develop over multiple 15m bars
- `executor_refresh_time` SHALL be increased proportionally
- ATR-scaled stop-loss and take-profit floors/caps SHALL be widened to reflect 15m ATR magnitude
- Grid spacing parameters SHALL be recalibrated for 15m ATR scale

#### Scenario: Time limit matches 15m trade horizon

- **WHEN** bot7 config has `indicator_resolution: "15m"`
- **THEN** `time_limit` is set to at least 7200 seconds (2 hours = 8 fifteen-minute bars)

#### Scenario: ATR barriers scale with 15m volatility

- **WHEN** 15m ATR is ~0.35% (typical BTC)
- **THEN** stop-loss floor (pb_sl_floor_pct) and cap (pb_sl_cap_pct) encompass the 15m ATR range

### Requirement: Bot7 price_buffer_bars sufficient for 15m indicators

Bot7's config SHALL set `price_buffer_bars` to at least 600 (sufficient for BB(20) on 15m = 300 bars, with 2x buffer for trend SMA and other lookbacks).

#### Scenario: Buffer size configured

- **WHEN** bot7 config has `indicator_resolution: "15m"`
- **THEN** `price_buffer_bars` is >= 600

### Requirement: Bot7 consumes ML features at 15m resolution

Bot7's config SHALL enable `ml_features_enabled: true` and `ml_regime_override_enabled: true` and `ml_sizing_hint_enabled: true`. The signal consumer SHALL only process events with `resolution: "15m"` for bot7.

#### Scenario: Bot7 receives ML regime override

- **WHEN** ML Feature Service publishes a regime prediction with `resolution="15m"` and confidence above threshold
- **THEN** bot7's regime is overridden to the ML-predicted regime

#### Scenario: Bot7 receives ML sizing hint

- **WHEN** ML Feature Service publishes a sizing prediction with `resolution="15m"`
- **THEN** bot7's grid sizing is adjusted by the sizing hint multiplier

#### Scenario: Bot7 ignores 1m ML features

- **WHEN** an ML feature event with `resolution="1m"` arrives
- **THEN** bot7 does not process it

### Requirement: Bot7 startup seeding provides sufficient bars for 15m indicators

The startup seeding policy SHALL request at least `max_indicator_period * resolution_minutes` bars when `indicator_resolution` is configured. For BB(20) at 15m, this is at least 300 1m bars. If the exchange API cannot provide enough bars, the system SHALL fall back to parquet seeding from `data/historical`.

#### Scenario: Seeding requests enough bars for 15m

- **WHEN** bot7 starts with `indicator_resolution: "15m"` and max indicator period is 20
- **THEN** the seeding policy requests at least 300 1m bars from the exchange or parquet

#### Scenario: Indicators ready immediately after successful seeding

- **WHEN** seeding provides 300+ 1m bars
- **THEN** BB(20), RSI(14), and ADX(14) at 15m resolution are all non-None on the first tick after seeding

### Requirement: Backtest adapters support configurable indicator resolution

`BacktestPullbackAdapter` and `BacktestPullbackAdapterV2` SHALL accept an `indicator_resolution` config parameter. When set to a resolution > 1m, the adapter constructs `PriceBuffer(resolution_minutes=...)`. All indicator calls automatically use resampled bars — no per-call parameter changes in the adapter code. Backtest results at 15m SHALL match live bot7 behavior at 15m.

#### Scenario: Backtest adapter at 15m matches live indicators

- **WHEN** backtest runs with `indicator_resolution: "15m"` on 1m historical candles
- **THEN** BB/RSI/ADX/ATR values match what live bot7 would compute with the same data (PriceBuffer handles resolution internally)

#### Scenario: Backtest adapter default unchanged

- **WHEN** backtest runs without `indicator_resolution` config
- **THEN** adapter uses 1m bars (unchanged behavior)
