## ADDED Requirements

### Requirement: BB width gate blocks entries when bands are too tight

The system SHALL compute Bollinger Band width as `(bb_upper - bb_lower) / mid` and block all entry signals (both full signals and probes) when this width is below `bot7_min_bb_width_pct`. A squeeze condition means the expected mean-reversion distance cannot cover round-trip maker fees; entries in this state have negative expected value.

#### Scenario: Entry blocked when band width below minimum

- **WHEN** `(bb_upper - bb_lower) / mid < bot7_min_bb_width_pct`
- **THEN** `_update_bot7_state` sets `side = "off"`, `reason = "bb_squeeze"`, and `active = False` regardless of absorption, delta-trap, or depth-imbalance signals

#### Scenario: Entry permitted when band width meets minimum

- **WHEN** `(bb_upper - bb_lower) / mid >= bot7_min_bb_width_pct` and all other signal conditions are satisfied
- **THEN** entry signal proceeds normally and is not blocked by the squeeze gate

#### Scenario: Squeeze gate evaluated after indicator warmup

- **WHEN** indicators are not yet ready (BB, RSI, or ADX returning None)
- **THEN** squeeze gate is not evaluated; state reason remains `"indicator_warmup"`

### Requirement: BB squeeze detection is encapsulated in a dedicated method

The system SHALL expose a `_detect_bb_squeeze(bb_lower, bb_upper, mid) -> bool` method on `Bot7AdaptiveGridV1Controller` that returns `True` when a squeeze is active. This method MUST be called within `_update_bot7_state` before signal scoring.

#### Scenario: Method returns True for tight bands

- **WHEN** `_detect_bb_squeeze` is called with bands where `(upper - lower) / mid < bot7_min_bb_width_pct`
- **THEN** it returns `True`

#### Scenario: Method returns False for wide bands

- **WHEN** `_detect_bb_squeeze` is called with bands where `(upper - lower) / mid >= bot7_min_bb_width_pct`
- **THEN** it returns `False`

#### Scenario: Method returns False when mid is zero or negative

- **WHEN** `mid <= 0`
- **THEN** `_detect_bb_squeeze` returns `False` (safe no-op; mid=0 guard handled upstream)

### Requirement: BB width gate supersedes the flat reversion-distance gate

The flat `bot7_min_reversion_pct` distance check SHALL no longer be used in the signal path. The `bot7_min_reversion_pct` config field MUST remain loadable without error (for backward compatibility with existing YAMLs) but MUST NOT influence signal generation.

#### Scenario: Old config field loads without error

- **WHEN** a YAML config includes `bot7_min_reversion_pct: 0.0016`
- **THEN** the config loads without validation error and the value is stored but unused in signal logic
