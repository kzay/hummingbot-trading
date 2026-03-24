## ADDED Requirements

### Requirement: Limit entry at zone boundary
When a pullback signal fires, the controller SHALL place the first grid level as a limit order at the BB basis zone boundary instead of using the default grid spacing. For longs, entry price = `bb_basis * (1 - pb_entry_offset_pct)`. For shorts, entry price = `bb_basis * (1 + pb_entry_offset_pct)`.

#### Scenario: Long entry limit price computation
- **WHEN** signal is "buy", bb_basis is 100200, `pb_entry_offset_pct` is 0.001, mid is 100400
- **THEN** target entry price = 100200 * (1 - 0.001) = 100099.8, first spread = (100400 - 100099.8) / 100400 = 0.00299, which is used as `buy_spreads[0]`

#### Scenario: Short entry limit price computation
- **WHEN** signal is "sell", bb_basis is 99800, `pb_entry_offset_pct` is 0.001, mid is 99600
- **THEN** target entry price = 99800 * (1 + 0.001) = 99899.8, first spread = (99899.8 - 99600) / 99600 = 0.00301, which is used as `sell_spreads[0]`

#### Scenario: Computed spread below floor
- **WHEN** the computed limit spread is below `pb_grid_spacing_floor_pct`
- **THEN** the spread SHALL be clamped to `pb_grid_spacing_floor_pct`

#### Scenario: Entry offset disabled
- **WHEN** `pb_limit_entry_enabled` is False
- **THEN** entry spreads SHALL use the existing grid spacing logic (current behavior)

### Requirement: Entry timeout via executor refresh
Entry limit orders that are not filled SHALL be cancelled and re-evaluated when the executor refresh timer fires (controlled by `executor_refresh_time`). The `pb_entry_timeout_s` config parameter SHALL set the executor refresh time for pullback entries.

#### Scenario: Unfilled limit order refreshed
- **WHEN** a limit entry order is placed and `pb_entry_timeout_s` (30s) elapses without fill
- **THEN** the executor SHALL be refreshed (cancelled), and if the signal still holds, a new limit order SHALL be placed at the updated zone boundary

#### Scenario: Signal disappears during timeout
- **WHEN** a limit entry order is pending and the signal flips to "off" on the next tick
- **THEN** the executor SHALL be cancelled during the normal `_resolve_quote_side_mode()` transition to "off"

### Requirement: Adverse selection entry filter
The controller SHALL block entry when spread conditions or book depth indicate high adverse selection risk.

#### Scenario: Wide spread blocks entry
- **WHEN** all signal gates pass but current spread > `pb_max_entry_spread_pct` (0.0008)
- **THEN** entry SHALL be blocked with reason "adverse_selection_spread"

#### Scenario: Extreme opposing depth imbalance blocks entry
- **WHEN** signal is "buy" but `depth_imbalance < -pb_max_entry_imbalance` (e.g., -0.6 indicating heavy sell pressure)
- **THEN** entry SHALL be blocked with reason "adverse_selection_depth"

#### Scenario: Signal is "sell" with heavy buy imbalance
- **WHEN** signal is "sell" but `depth_imbalance > pb_max_entry_imbalance` (e.g., 0.6 indicating heavy buy pressure opposing the short)
- **THEN** entry SHALL be blocked with reason "adverse_selection_depth"

#### Scenario: Normal spread and balanced book allows entry
- **WHEN** spread is 0.0004 (below threshold) and depth imbalance is 0.15 (within threshold)
- **THEN** the adverse selection filter SHALL pass and entry SHALL proceed

### Requirement: Entry quality config parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `pb_limit_entry_enabled` | bool | True | Enable limit entry at zone boundary |
| `pb_entry_offset_pct` | Decimal | 0.001 | Offset from BB basis for limit entry (10bps) |
| `pb_entry_timeout_s` | int | 30 | Timeout for unfilled limit entries |
| `pb_max_entry_spread_pct` | Decimal | 0.0008 | Max spread for entry (80bps) |
| `pb_max_entry_imbalance` | Decimal | 0.5 | Max opposing depth imbalance for entry |
| `pb_adverse_selection_enabled` | bool | True | Enable adverse selection filter |

#### Scenario: Adverse selection filter disabled
- **WHEN** `pb_adverse_selection_enabled` is False
- **THEN** both spread and depth imbalance checks SHALL pass unconditionally
