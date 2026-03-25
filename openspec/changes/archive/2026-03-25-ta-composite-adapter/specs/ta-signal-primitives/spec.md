## ADDED Requirements

### Requirement: Signal primitives SHALL be stateless functions
Each signal primitive SHALL be a pure function with signature:
`(buf: PriceBuffer, **params) → SignalResult`

`SignalResult` SHALL be a frozen dataclass with fields:
- `direction`: `Literal["long", "short", "neutral"]`
- `strength`: `float` in range [0.0, 1.0] (0 = no signal, 1 = strongest)

Signal primitives SHALL NOT maintain any mutable state between calls.

#### Scenario: SignalResult immutability
- **WHEN** a SignalResult is returned from any signal primitive
- **THEN** attempting to modify its fields raises `FrozenInstanceError`

#### Scenario: Signal returns neutral when indicator is unavailable
- **WHEN** PriceBuffer does not have enough bars for the requested indicator
- **THEN** the signal primitive returns `SignalResult("neutral", 0.0)`

### Requirement: EMA cross signal
The `ema_cross` signal SHALL detect when a fast EMA crosses above or below
a slow EMA. Parameters: `fast: int`, `slow: int`.

#### Scenario: Bullish EMA crossover
- **WHEN** `EMA(fast) > EMA(slow)` on the current bar AND `EMA(fast) <= EMA(slow)` on the previous bar
- **THEN** returns `SignalResult("long", strength)` where strength is proportional to the cross magnitude

#### Scenario: Bearish EMA crossover
- **WHEN** `EMA(fast) < EMA(slow)` on the current bar AND `EMA(fast) >= EMA(slow)` on the previous bar
- **THEN** returns `SignalResult("short", strength)`

#### Scenario: No crossover
- **WHEN** the EMA relationship has not changed since the previous bar
- **THEN** returns `SignalResult("neutral", 0.0)`

### Requirement: RSI zone signal
The `rsi_zone` signal SHALL classify RSI into zones. Parameters:
`period: int`, `overbought: float`, `oversold: float`.

#### Scenario: RSI in oversold zone
- **WHEN** `RSI(period) < oversold`
- **THEN** returns `SignalResult("long", strength)` with strength inversely proportional to RSI value

#### Scenario: RSI in overbought zone
- **WHEN** `RSI(period) > overbought`
- **THEN** returns `SignalResult("short", strength)`

#### Scenario: RSI in neutral zone
- **WHEN** `oversold <= RSI(period) <= overbought`
- **THEN** returns `SignalResult("neutral", 0.0)`

### Requirement: MACD cross signal
The `macd_cross` signal SHALL detect MACD line crossing the signal line.
Parameters: `fast: int`, `slow: int`, `signal: int`.

#### Scenario: Bullish MACD cross
- **WHEN** MACD histogram transitions from negative to positive
- **THEN** returns `SignalResult("long", strength)`

#### Scenario: Bearish MACD cross
- **WHEN** MACD histogram transitions from positive to negative
- **THEN** returns `SignalResult("short", strength)`

### Requirement: MACD histogram momentum signal
The `macd_histogram` signal SHALL detect histogram momentum. Parameters:
`fast: int`, `slow: int`, `signal: int`, `threshold: float`.

#### Scenario: Strong bullish momentum
- **WHEN** histogram is positive and increasing above `threshold`
- **THEN** returns `SignalResult("long", strength)`

#### Scenario: Strong bearish momentum
- **WHEN** histogram is negative and decreasing below `-threshold`
- **THEN** returns `SignalResult("short", strength)`

### Requirement: Bollinger breakout signal
The `bb_breakout` signal SHALL detect price breaking out of Bollinger Bands.
Parameters: `period: int`, `stddev_mult: float`.

#### Scenario: Upper band breakout
- **WHEN** close price exceeds upper Bollinger Band
- **THEN** returns `SignalResult("long", strength)` reflecting breakout magnitude

#### Scenario: Lower band breakout
- **WHEN** close price falls below lower Bollinger Band
- **THEN** returns `SignalResult("short", strength)`

#### Scenario: Price inside bands
- **WHEN** close price is between lower and upper bands
- **THEN** returns `SignalResult("neutral", 0.0)`

### Requirement: Bollinger squeeze signal
The `bb_squeeze` signal SHALL detect Bollinger Band contraction indicating
imminent volatility expansion. Parameters: `period: int`, `stddev_mult: float`,
`squeeze_threshold: float`.

#### Scenario: Squeeze detected
- **WHEN** Bollinger bandwidth (upper - lower) / basis is below `squeeze_threshold`
- **THEN** returns `SignalResult("neutral", strength)` with high strength indicating tight squeeze

#### Scenario: No squeeze
- **WHEN** bandwidth is above `squeeze_threshold`
- **THEN** returns `SignalResult("neutral", 0.0)`

### Requirement: Stochastic RSI cross signal
The `stoch_rsi_cross` signal SHALL detect K/D crossovers. Parameters:
`rsi_period: int`, `stoch_period: int`, `k_smooth: int`, `d_smooth: int`,
`overbought: float`, `oversold: float`.

#### Scenario: Bullish StochRSI cross in oversold
- **WHEN** K crosses above D AND both are below `oversold`
- **THEN** returns `SignalResult("long", strength)`

#### Scenario: Bearish StochRSI cross in overbought
- **WHEN** K crosses below D AND both are above `overbought`
- **THEN** returns `SignalResult("short", strength)`

### Requirement: ICT structure signal
The `ict_structure` signal SHALL expose break-of-structure from the existing
ICT library. Parameters: `lookback: int`.

#### Scenario: Bullish break of structure
- **WHEN** ICT state detects a bullish structure break (higher high above previous swing high)
- **THEN** returns `SignalResult("long", strength)`

#### Scenario: Bearish break of structure
- **WHEN** ICT state detects a bearish structure break (lower low below previous swing low)
- **THEN** returns `SignalResult("short", strength)`

### Requirement: Signal primitives SHALL be registered in a SIGNAL_REGISTRY
A `SIGNAL_REGISTRY: dict[str, Callable]` SHALL map signal type names
(e.g. `"ema_cross"`, `"rsi_zone"`, `"stoch_rsi_cross"`) to their corresponding functions.
The adapter SHALL look up signals by name from this registry.

#### Scenario: Unknown signal type
- **WHEN** a YAML config references a signal type not in `SIGNAL_REGISTRY`
- **THEN** the adapter raises `ValueError` with the unknown type name and list of available types
