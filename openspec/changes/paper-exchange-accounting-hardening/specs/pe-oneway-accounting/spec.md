## ADDED Requirements

### Requirement: ONEWAY position action normalization
The Paper Exchange Service SHALL normalize all explicit `position_action` values (`open_long`, `open_short`, `close_long`, `close_short`) to `auto` when `position_mode` is not `HEDGE`, before applying any fill logic.

#### Scenario: Buy with open_long in ONEWAY mode
- **WHEN** a fill arrives with `side=buy`, `position_action=open_long`, `position_mode=ONEWAY` and the position has `short_base=0.01`
- **THEN** the action SHALL be normalized to `auto`, closing 0.01 short before opening any long remainder

#### Scenario: Sell with open_short in ONEWAY mode
- **WHEN** a fill arrives with `side=sell`, `position_action=open_short`, `position_mode=ONEWAY` and the position has `long_base=0.01`
- **THEN** the action SHALL be normalized to `auto`, closing 0.01 long before opening any short remainder

#### Scenario: HEDGE mode preserves explicit action
- **WHEN** a fill arrives with `position_action=open_long`, `position_mode=HEDGE`
- **THEN** the action SHALL NOT be normalized; `open_long` is honored directly

### Requirement: ONEWAY auto-netting on fill
In ONEWAY mode with `action=auto`, a buy fill SHALL first close any existing short position (up to fill quantity), then open a long position with any remaining quantity. A sell fill SHALL first close any existing long position, then open a short position with any remainder.

#### Scenario: Buy closes short then opens long
- **WHEN** position has `short_base=0.005`, a buy fill of `0.008` arrives in ONEWAY auto mode
- **THEN** `short_base` SHALL become `0.0`, realized PnL SHALL be computed for the 0.005 close, and `long_base` SHALL become `0.003` at the fill price

#### Scenario: Sell closes long then opens short
- **WHEN** position has `long_base=0.01`, a sell fill of `0.015` arrives in ONEWAY auto mode
- **THEN** `long_base` SHALL become `0.0`, realized PnL SHALL be computed for the 0.01 close, and `short_base` SHALL become `0.005` at the fill price

#### Scenario: Buy with no opposing position
- **WHEN** position has `short_base=0.0`, a buy fill of `0.002` arrives in ONEWAY auto mode
- **THEN** `long_base` SHALL increase by 0.002 and no realized PnL SHALL be generated

#### Scenario: Exact close to flat
- **WHEN** position has `long_base=0.01`, a sell fill of exactly `0.01` arrives in ONEWAY auto mode
- **THEN** `long_base` SHALL become `0.0`, `short_base` SHALL remain `0.0`, and realized PnL SHALL be computed

### Requirement: Post-fill ONEWAY invariant enforcement
After every call to `_apply_position_fill` for a ONEWAY position, the system SHALL verify that at most one of `long_base` or `short_base` is greater than `_MIN_FILL_EPSILON`. If both are non-zero, the system SHALL auto-collapse to net, log a `POSITION_INVARIANT_VIOLATION` warning with position key and pre/post quantities, and increment a heartbeat counter.

#### Scenario: Clean fill passes invariant
- **WHEN** a fill is applied and the resulting position has `long_base=0.01`, `short_base=0.0`
- **THEN** no invariant violation SHALL be logged

#### Scenario: Corrupted state detected and repaired
- **WHEN** due to a code bug a fill results in `long_base=0.01`, `short_base=0.003` in ONEWAY mode
- **THEN** the system SHALL auto-collapse to `long_base=0.007`, `short_base=0.0`, log a `POSITION_INVARIANT_VIOLATION` warning, and increment the heartbeat violation counter

### Requirement: Mode string normalization consistency
All ONEWAY/HEDGE mode checks in the Paper Exchange Service SHALL use exact string comparison (`mode != "HEDGE"`) after uppercasing and stripping. Substring matching (`"HEDGE" in mode`) SHALL NOT be used.

#### Scenario: POSITIONMODE.ONEWAY treated as ONEWAY
- **WHEN** `position_mode` is `"POSITIONMODE.ONEWAY"`
- **THEN** the system SHALL treat it as non-HEDGE (ONEWAY netting applies)

#### Scenario: HEDGE treated as HEDGE
- **WHEN** `position_mode` is `"HEDGE"`
- **THEN** the system SHALL treat it as HEDGE (explicit leg actions honored)

### Requirement: Startup ONEWAY position sanitization
On startup, the Paper Exchange Service SHALL scan all loaded positions and collapse any ONEWAY position where both `long_base > 0` and `short_base > 0` into a single net leg, logging each repair.

#### Scenario: Dual-leg ONEWAY collapsed on load
- **WHEN** a persisted ONEWAY position has `long_base=0.278`, `short_base=0.216`
- **THEN** on load it SHALL be collapsed to `long_base=0.062`, `short_base=0.0`

#### Scenario: Single-leg ONEWAY untouched
- **WHEN** a persisted ONEWAY position has `long_base=0.05`, `short_base=0.0`
- **THEN** it SHALL remain unchanged

### Requirement: Preview PnL respects ONEWAY normalization
`_preview_fill_realized_pnl` SHALL normalize explicit `position_action` to `auto` for ONEWAY positions, ensuring the preview correctly predicts PnL from closing the opposite leg.

#### Scenario: Preview PnL for buy closing short in ONEWAY
- **WHEN** previewing PnL for a buy fill of 0.01 with `position_action=open_long` against a position with `short_base=0.01` at entry 70000, fill price 69500
- **THEN** the preview SHALL return positive realized PnL of `0.01 * (70000 - 69500) = 5.0` (short close profit), not `0.0`
