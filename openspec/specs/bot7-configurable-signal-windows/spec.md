## ADDED Requirements

### Requirement: Absorption detection window is config-driven

The system SHALL use `bot7_absorption_window` (default=20) to determine the number of recent trades examined in `_detect_absorption`, replacing the hardcoded value of 12. The window MUST be applied to both the trades slice used for average-size computation and the max-trade and total-delta computations.

#### Scenario: Absorption uses configured window size

- **WHEN** `bot7_absorption_window = 20` and 30 recent trades are available
- **THEN** `_detect_absorption` examines only the last 20 trades for avg_size, max_trade, total_delta, and price_drift calculations

#### Scenario: Absorption uses default window when config field absent

- **WHEN** a config object does not include `bot7_absorption_window`
- **THEN** `_detect_absorption` defaults to a window of 20 trades

#### Scenario: Absorption returns False when fewer trades than minimum threshold

- **WHEN** fewer than 6 trades are available (existing guard)
- **THEN** `_detect_absorption` returns `(False, False)` regardless of window size

### Requirement: Recent-delta window is config-driven

The system SHALL use `bot7_recent_delta_window` (default=20) to determine the number of recent trades used to compute `recent_delta` in `_update_bot7_state`, replacing the hardcoded value of 12.

#### Scenario: Recent delta computed over configured window

- **WHEN** `bot7_recent_delta_window = 20` and 50 trades are loaded
- **THEN** `recent_delta` is the sum of `trade.delta` for the last 20 trades only

#### Scenario: Recent delta uses default window when config field absent

- **WHEN** a config object does not include `bot7_recent_delta_window`
- **THEN** `recent_delta` is computed over the last 20 trades

#### Scenario: Recent delta is zero when no trades available

- **WHEN** the trades list is empty
- **THEN** `recent_delta = Decimal("0")`

### Requirement: New config fields have valid range constraints

Both `bot7_absorption_window` and `bot7_recent_delta_window` SHALL be declared as `int` fields in `Bot7AdaptiveGridV1Config` with `ge=6` and `le=100` to prevent misconfiguration.

#### Scenario: Config validation rejects window below minimum

- **WHEN** a config is constructed with `bot7_absorption_window = 3`
- **THEN** pydantic raises a `ValidationError`

#### Scenario: Config validation accepts window within valid range

- **WHEN** a config is constructed with `bot7_absorption_window = 20`
- **THEN** the config is valid and the field stores the value `20`
