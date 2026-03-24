## ADDED Requirements

### Requirement: Grid spacing blends BB geometry with ATR

The system SHALL compute grid spacing as the minimum of two signals, floored and capped:

```
bb_spacing  = bb_width * bot7_grid_spacing_bb_fraction
atr_spacing = (atr * bot7_grid_spacing_atr_mult) / mid   (if atr available)
spacing_pct = clip(min(bb_spacing, atr_spacing), floor, cap)
```

When ATR is unavailable, only `bb_spacing` is used before clip. When BB bands are unavailable, the existing ATR-only path is retained.

#### Scenario: BB geometry produces tighter spacing than ATR

- **WHEN** `bb_width = 0.010` (1%), `bot7_grid_spacing_bb_fraction = 0.12`, `atr/mid = 0.008` (80bps)
- **THEN** `bb_spacing = 0.0012`, `atr_spacing = 0.004`, `spacing = clip(min(0.0012, 0.004), floor, cap) = max(floor, 0.0012)`

#### Scenario: ATR produces tighter spacing than BB geometry

- **WHEN** `bb_width = 0.030` (3%), `bot7_grid_spacing_bb_fraction = 0.12`, `atr/mid = 0.002` (20bps)
- **THEN** `bb_spacing = 0.0036`, `atr_spacing = 0.001`, `spacing = clip(min(0.0036, 0.001), floor, cap) = max(floor, 0.001)`

#### Scenario: Spacing is floored when computed value is below minimum

- **WHEN** both `bb_spacing` and `atr_spacing` compute below `bot7_grid_spacing_floor_pct`
- **THEN** `spacing_pct = bot7_grid_spacing_floor_pct`

#### Scenario: Spacing is capped when computed value exceeds maximum

- **WHEN** both signals compute above `bot7_grid_spacing_cap_pct`
- **THEN** `spacing_pct = bot7_grid_spacing_cap_pct`

#### Scenario: ATR-only path when BB unavailable

- **WHEN** `_price_buffer.bollinger_bands(...)` returns `None` but ATR is available
- **THEN** spacing falls back to ATR-only computation as before this change

### Requirement: BB fraction config field has valid range

`bot7_grid_spacing_bb_fraction` SHALL be declared as a `Decimal` field in `Bot7AdaptiveGridV1Config` with `default=Decimal("0.12")`, `ge=0.01`, `le=0.50`.

#### Scenario: Config validation accepts valid fraction

- **WHEN** `bot7_grid_spacing_bb_fraction = 0.12` is provided
- **THEN** the config is valid

#### Scenario: Config validation rejects fraction above maximum

- **WHEN** `bot7_grid_spacing_bb_fraction = 0.75` is provided
- **THEN** pydantic raises a `ValidationError`
