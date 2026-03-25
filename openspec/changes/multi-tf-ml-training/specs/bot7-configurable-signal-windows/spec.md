## MODIFIED Requirements

### Requirement: Absorption detection window is config-driven

The system SHALL use `pb_absorption_window` (default=20) to determine the number of recent trades examined in `_detect_absorption`, replacing the hardcoded value of 12. The window MUST be applied to both the trades slice used for average-size computation and the max-trade and total-delta computations. When `indicator_resolution` is `"15m"`, the default window SHOULD be scaled to match the higher timeframe trade density.

#### Scenario: Absorption uses configured window size

- **WHEN** `pb_absorption_window = 20` and 30 recent trades are available
- **THEN** `_detect_absorption` examines only the last 20 trades for avg_size, max_trade, total_delta, and price_drift calculations

#### Scenario: Absorption uses default window when config field absent

- **WHEN** a config object does not include `pb_absorption_window`
- **THEN** `_detect_absorption` defaults to a window of 20 trades

#### Scenario: Absorption returns False when fewer trades than minimum threshold

- **WHEN** fewer than 6 trades are available (existing guard)
- **THEN** `_detect_absorption` returns `(False, False)` regardless of window size

### Requirement: Signal window parameters recalibrated for 15m

When bot7 operates at 15m resolution, signal window parameters (absorption window, delta trap window, recent delta window, stale timeout) SHALL be adjusted to account for the higher timeframe. Trade counts and price drift thresholds accumulate over 15 minutes rather than 1 minute, requiring wider windows and looser drift tolerances.

#### Scenario: Trade stale timeout scaled for 15m

- **WHEN** `indicator_resolution: "15m"` and `pb_trade_stale_after_ms` is configured
- **THEN** the stale timeout allows trades from the full 15m bar window (at least 15000ms)

#### Scenario: Price drift thresholds widened for 15m

- **WHEN** `indicator_resolution: "15m"`
- **THEN** `pb_absorption_max_price_drift_pct` and `pb_delta_trap_max_price_drift_pct` are set wider than the 1m defaults to accommodate 15m price movement
