## ADDED Requirements

### Requirement: BB basis slope trend quality gate
The controller SHALL compute the BB basis (20-SMA) slope over the last `pb_basis_slope_bars` bars and block entry when the slope direction conflicts with the trade side.

#### Scenario: Long entry with positive slope passes
- **WHEN** signal side is "buy" and `slope = (bars[-1].close_sma - bars[-N].close_sma) / bars[-N].close_sma` is 0.0004 and `pb_min_basis_slope_pct` is 0.0002
- **THEN** the trend quality gate SHALL pass and entry SHALL be allowed

#### Scenario: Long entry with flat/negative slope blocked
- **WHEN** signal side is "buy" and slope is 0.0001 (below `pb_min_basis_slope_pct` of 0.0002)
- **THEN** the trend quality gate SHALL block entry with reason "basis_slope_flat"

#### Scenario: Short entry with negative slope passes
- **WHEN** signal side is "sell" and slope is -0.0003 and `pb_min_basis_slope_pct` is 0.0002
- **THEN** the trend quality gate SHALL pass (abs(slope) > threshold and slope is negative for short)

#### Scenario: Insufficient bars for slope computation
- **WHEN** PriceBuffer has fewer bars than `pb_basis_slope_bars`
- **THEN** the trend quality gate SHALL pass (permissive during warmup)

### Requirement: Long-period SMA trend confirmation gate
The controller SHALL compute a long-period SMA using `PriceBuffer.sma(pb_trend_sma_period)` and block entries that conflict with the macro trend direction.

#### Scenario: Long entry above SMA passes
- **WHEN** signal side is "buy" and mid price (100500) is above SMA(50) (100200)
- **THEN** the SMA trend gate SHALL pass

#### Scenario: Long entry below SMA blocked
- **WHEN** signal side is "buy" and mid price (99800) is below SMA(50) (100200)
- **THEN** the SMA trend gate SHALL block entry with reason "trend_sma_against"

#### Scenario: Short entry below SMA passes
- **WHEN** signal side is "sell" and mid price (99800) is below SMA(50) (100200)
- **THEN** the SMA trend gate SHALL pass

#### Scenario: SMA unavailable during warmup
- **WHEN** PriceBuffer has fewer bars than `pb_trend_sma_period`
- **THEN** the SMA trend gate SHALL pass (permissive during warmup)

### Requirement: Trend quality gate config parameters
The following config fields SHALL be added:

| Param | Type | Default | Description |
|---|---|---|---|
| `pb_basis_slope_bars` | int | 5 | Bars lookback for BB basis slope |
| `pb_min_basis_slope_pct` | Decimal | 0.0002 | Minimum absolute slope to confirm trend |
| `pb_trend_sma_period` | int | 50 | Period for long-period SMA trend filter |
| `pb_trend_quality_enabled` | bool | True | Enable/disable both trend quality gates |

#### Scenario: Trend quality gates disabled
- **WHEN** `pb_trend_quality_enabled` is False
- **THEN** both the basis slope gate and SMA trend gate SHALL pass unconditionally

### Requirement: Gate ordering in signal conjunction
The trend quality gates SHALL be evaluated in `_update_pb_state()` after the regime gate and ADX range gate, and before the RSI gate. The gate evaluation order SHALL be: regime → ADX → trend quality (slope + SMA) → pullback zone → RSI → absorption/delta-trap → contra-funding → adverse selection → cooldown.

#### Scenario: Gate blocks before RSI evaluation
- **WHEN** regime is "up", ADX is 25, but basis slope is flat
- **THEN** the entry SHALL be blocked with reason "basis_slope_flat" and RSI, absorption, and subsequent gates SHALL NOT be evaluated for this tick
