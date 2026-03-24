## ADDED Requirements

### Requirement: ONEWAY netting regression tests
The test suite SHALL include tests for every ONEWAY netting path in `_apply_position_fill`: buy closing short, sell closing long, buy with no opposing position, sell with no opposing position, exact close to flat.

#### Scenario: All netting paths covered
- **WHEN** the regression test suite runs
- **THEN** it SHALL exercise and assert correct behavior for: buy-closes-short, sell-closes-long, buy-opens-long-from-flat, sell-opens-short-from-flat, buy-exact-close-short, sell-exact-close-long

### Requirement: Flip-through-zero regression tests
The test suite SHALL include tests for flip-through-zero in both directions (long→short, short→long), verifying correct realized PnL on the close leg and correct position state on the open leg.

#### Scenario: Long to short flip
- **WHEN** position is long 0.01 at entry 70000 and a sell of 0.015 at 71000 arrives
- **THEN** the test SHALL assert: realized PnL = 0.01 * (71000 - 70000) = 10.0, `long_base=0.0`, `short_base=0.005`, `short_avg_entry_price=71000`

#### Scenario: Short to long flip
- **WHEN** position is short 0.01 at entry 71000 and a buy of 0.015 at 70000 arrives
- **THEN** the test SHALL assert: realized PnL = 0.01 * (71000 - 70000) = 10.0, `short_base=0.0`, `long_base=0.005`, `long_avg_entry_price=70000`

### Requirement: Explicit action normalization regression tests
The test suite SHALL include tests verifying that `open_long`, `open_short`, `close_long`, `close_short` are normalized to `auto` in ONEWAY mode, ensuring netting occurs.

#### Scenario: open_long normalized to auto
- **WHEN** a buy fill with `position_action=open_long` is applied in ONEWAY mode against a position with `short_base > 0`
- **THEN** the short leg SHALL be closed (PnL generated) before any long is opened, identical to `auto` behavior

#### Scenario: open_short normalized to auto
- **WHEN** a sell fill with `position_action=open_short` is applied in ONEWAY mode against a position with `long_base > 0`
- **THEN** the long leg SHALL be closed (PnL generated) before any short is opened, identical to `auto` behavior

### Requirement: Preview PnL regression tests
The test suite SHALL include tests for `_preview_fill_realized_pnl` covering ONEWAY close, ONEWAY open (no PnL), ONEWAY flip, and ONEWAY with explicit action normalization.

#### Scenario: Preview close PnL
- **WHEN** previewing a sell of 0.01 against long 0.01 at entry 70000, fill price 71000, ONEWAY mode
- **THEN** the preview SHALL return realized PnL ≈ 10.0

#### Scenario: Preview open PnL
- **WHEN** previewing a buy of 0.01 against flat position, ONEWAY mode
- **THEN** the preview SHALL return realized PnL = 0.0

#### Scenario: Preview with explicit action normalized
- **WHEN** previewing a sell of 0.01 with `position_action=open_short` against long 0.01 at entry 70000, fill price 71000, ONEWAY mode
- **THEN** the preview SHALL return realized PnL ≈ 10.0 (not 0.0, because action is normalized to auto)

### Requirement: Sanitize startup regression tests
The test suite SHALL include tests for `_sanitize_oneway_positions` covering dual-leg collapse, single-leg no-op, flat position no-op, and HEDGE position skip.

#### Scenario: Dual-leg ONEWAY collapsed
- **WHEN** a position dict contains a ONEWAY position with `long_base=0.278`, `short_base=0.216`
- **THEN** `_sanitize_oneway_positions` SHALL return 1 (repaired) and the position SHALL have `long_base≈0.062`, `short_base=0.0`

#### Scenario: Single-leg ONEWAY untouched
- **WHEN** a position dict contains a ONEWAY position with `long_base=0.05`, `short_base=0.0`
- **THEN** `_sanitize_oneway_positions` SHALL return 0

#### Scenario: HEDGE position skipped
- **WHEN** a position dict contains a HEDGE position with `long_base=0.01`, `short_base=0.02`
- **THEN** `_sanitize_oneway_positions` SHALL return 0 and both legs SHALL be unchanged

### Requirement: Multi-fill sequence regression tests
The test suite SHALL include multi-fill sequence tests that simulate realistic trading patterns (pyramid entry + partial exit, alternating buys/sells) and assert correct position state and cumulative PnL after each fill.

#### Scenario: Pyramid and unwind
- **WHEN** 3 buy fills at increasing prices, then 3 sell fills at higher prices are applied
- **THEN** the position SHALL be flat after all fills and cumulative realized PnL SHALL be positive and correct

#### Scenario: Alternating direction fills
- **WHEN** 10 alternating buy/sell fills of the same size at the same price are applied
- **THEN** the position SHALL be flat after all fills and cumulative realized PnL SHALL be approximately 0.0

### Requirement: Dust handling regression tests
The test suite SHALL include tests for near-zero quantities at the `_MIN_FILL_EPSILON` boundary.

#### Scenario: Close leaves dust below epsilon
- **WHEN** a sell of 0.009999999999 closes a long of 0.01 (remainder below epsilon)
- **THEN** the position SHALL be treated as flat (both legs zero)

#### Scenario: Fill quantity below epsilon is no-op
- **WHEN** a fill of quantity `1e-15` (below `_MIN_FILL_EPSILON`) is applied
- **THEN** the position SHALL remain unchanged
