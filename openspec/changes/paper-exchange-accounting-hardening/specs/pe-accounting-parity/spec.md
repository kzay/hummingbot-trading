## ADDED Requirements

### Requirement: Position quantity parity after fill sequence
For any deterministic fill sequence applied to both the Paper Exchange Service (`_apply_position_fill`) and the pure accounting core (`accounting.apply_fill`), the resulting net position quantity SHALL match within float64 tolerance (`rel_tol=1e-8`).

#### Scenario: Simple open-add-close sequence
- **WHEN** the sequence [buy 0.01 @ 70000, buy 0.005 @ 70500, sell 0.015 @ 71000] is applied to both systems starting from flat
- **THEN** both systems SHALL report flat (quantity ≈ 0) with matching realized PnL

#### Scenario: Flip-through-zero sequence
- **WHEN** the sequence [buy 0.01 @ 70000, sell 0.02 @ 71000] is applied to both systems starting from flat
- **THEN** both systems SHALL report short 0.01 with matching realized PnL from the 0.01 close leg

#### Scenario: Multi-fill pyramid and unwind
- **WHEN** a 10-fill pyramid entry (5 buys at increasing prices) followed by 5 sells (partial closes) is applied to both systems
- **THEN** position quantity and cumulative realized PnL SHALL match within tolerance after each fill

#### Scenario: Alternating direction fills
- **WHEN** 20 alternating buy/sell fills of varying sizes are applied to both systems
- **THEN** position quantity and cumulative realized PnL SHALL match within tolerance after every fill

### Requirement: Realized PnL parity after fill sequence
For any fill that closes or partially closes a position, the realized PnL computed by the Paper Exchange Service SHALL match the realized PnL computed by `accounting.apply_fill` within float64 tolerance.

#### Scenario: Single close fill PnL match
- **WHEN** a sell fill closes a long position of 0.01 at entry 70000, fill price 71000
- **THEN** both systems SHALL compute realized PnL ≈ 10.0 (0.01 * 1000)

#### Scenario: Flip fill PnL match
- **WHEN** a sell fill of 0.02 flips a long position of 0.01 at entry 70000, fill price 69000
- **THEN** both systems SHALL compute the close-leg realized PnL ≈ -10.0 (0.01 * -1000) for the closing portion

### Requirement: VWAP entry price parity
For same-direction accumulation fills, the average entry price computed by both systems SHALL match within float64 tolerance.

#### Scenario: Two-fill VWAP
- **WHEN** two buys [0.01 @ 70000, 0.02 @ 71000] are applied to both systems
- **THEN** both systems SHALL report avg_entry_price ≈ 70666.67

#### Scenario: Three-fill VWAP
- **WHEN** three buys [0.01 @ 70000, 0.01 @ 71000, 0.01 @ 72000] are applied to both systems
- **THEN** both systems SHALL report avg_entry_price ≈ 71000.0
