## ADDED Requirements

### Requirement: Trailing stop state machine
The controller SHALL maintain a trailing stop state machine with three states: `inactive`, `tracking`, and `triggered`. The state machine SHALL be updated each tick via `_manage_trailing_stop()` called from `_resolve_regime_and_targets()`.

#### Scenario: Activation on sufficient profit
- **WHEN** position is long at entry price 100000, current mid is 100350, and `pb_trail_activate_atr_mult * ATR / mid` equals 0.003 (300 USDT on 100000)
- **THEN** unrealized profit (350/100000 = 0.0035) exceeds activation threshold (0.003), state SHALL transition from `inactive` to `tracking`, and high-water mark SHALL be set to 100350

#### Scenario: High-water mark tracking
- **WHEN** trailing stop is in `tracking` state with HWM at 100500, and mid rises to 100700
- **THEN** HWM SHALL be updated to 100700

#### Scenario: Trailing stop triggered on retrace
- **WHEN** trailing stop is in `tracking` state with HWM at 100700, `pb_trail_offset_atr_mult * ATR` is 200 USDT, and mid drops to 100480
- **THEN** retrace from HWM is 220 USDT > trail offset 200 USDT, state SHALL transition to `triggered`, and a market close action SHALL be emitted for the full remaining position

#### Scenario: Short position trailing stop (symmetric)
- **WHEN** position is short at entry 100000, current mid is 99600, activation threshold met
- **THEN** low-water mark SHALL track the lowest mid, and trailing stop triggers when mid rises by `pb_trail_offset_atr_mult * ATR` above the low-water mark

#### Scenario: No position — state inactive
- **WHEN** `_position_base` is zero or within epsilon of zero
- **THEN** trailing stop state SHALL be `inactive` and all tracking state SHALL be reset

### Requirement: Trailing stop close action emission
When the trailing stop triggers, the controller SHALL emit a `CreateExecutorAction` with a `PositionExecutorConfig` configured as a MARKET close order for the remaining position size, with no SL/TP/time_limit barriers.

#### Scenario: Close action structure
- **WHEN** trailing stop triggers for a long position of 0.005 BTC
- **THEN** the close action SHALL have `side=SELL`, `amount=0.005`, `open_order_type=MARKET`, `stop_loss=None`, `take_profit=None`, `time_limit=None`, `level_id="pb_trail_close"`

#### Scenario: Cancel existing executors before close
- **WHEN** trailing stop triggers and there are active executors for this position
- **THEN** the controller SHALL cancel active quote executors via `_cancel_active_quote_executors()` before emitting the close action

#### Scenario: Close amount capped at actual position
- **WHEN** trailing stop triggers but `_position_base` is smaller than expected (partial fills elsewhere)
- **THEN** the close amount SHALL be `min(expected_remaining, abs(_position_base))`

### Requirement: Trailing stop interaction with partial take
The trailing stop SHALL track the remaining position after partial profit-taking. The activation threshold and trail offset SHALL be recomputed against the remaining position.

#### Scenario: Partial take reduces position before trail activates
- **WHEN** position was 0.01 BTC, partial take closes 0.0033 BTC at 1R, remaining is 0.0067 BTC
- **THEN** trailing stop SHALL track HWM for the remaining 0.0067 BTC, and close action SHALL be for 0.0067 BTC when triggered

#### Scenario: Partial take already done, trail tracks remainder
- **WHEN** `_pb_partial_taken` is True and trailing stop enters `tracking` state
- **THEN** the position size used for close action SHALL be `abs(_position_base)` (actual current position)

### Requirement: Trailing stop state reset on position flat
When the position goes flat (abs(_position_base) < epsilon), ALL trailing stop state SHALL be reset: state → `inactive`, HWM → None, entry_price → None, `_pb_partial_taken` → False.

#### Scenario: Position closed externally
- **WHEN** a stop-loss or external close brings position to zero
- **THEN** trailing stop state SHALL reset to `inactive` on the next tick

### Requirement: Trailing stop config parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `pb_trail_activate_atr_mult` | Decimal | 1.0 | ATR multiple of profit to activate trailing |
| `pb_trail_offset_atr_mult` | Decimal | 0.5 | ATR multiple of retrace from HWM to trigger close |
| `pb_trailing_stop_enabled` | bool | True | Enable/disable trailing stop manager |

#### Scenario: Trailing stop disabled
- **WHEN** `pb_trailing_stop_enabled` is False
- **THEN** the trailing stop state machine SHALL remain `inactive` permanently and no close actions SHALL be emitted from the trailing stop
