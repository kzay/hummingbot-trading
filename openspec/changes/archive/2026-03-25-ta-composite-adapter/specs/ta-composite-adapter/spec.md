## ADDED Requirements

### Requirement: ta_composite adapter SHALL be registered in ADAPTER_REGISTRY
The `ta_composite` adapter SHALL be registered in `ADAPTER_REGISTRY` with
module path `controllers.backtesting.ta_composite_adapter`, class
`TaCompositeAdapter`, and config class `TaCompositeConfig`.

#### Scenario: Adapter mode lookup
- **WHEN** `build_adapter()` is called with `adapter_mode: "ta_composite"`
- **THEN** the registry resolves to `TaCompositeAdapter` and constructs it

#### Scenario: Unknown adapter mode unchanged
- **WHEN** `build_adapter()` is called with an unknown mode
- **THEN** behavior is unchanged (ValueError raised with available modes including `ta_composite`)

### Requirement: ta_composite adapter SHALL evaluate entry rules per bar
On each tick where a new candle is available and no position is held, the adapter SHALL evaluate all signals listed in `entry_rules.signals` against the current `PriceBuffer` state.

The adapter SHALL NOT evaluate entries or exits until the warmup requirement
derived from the configured indicators and ATR dependencies has been satisfied.
`min_warmup_bars`, when present, SHALL act only as an additional floor above the
derived minimum.

When `entry_rules.mode` is `"all"`, ALL signals MUST return a non-neutral
direction agreeing on the same side (all long or all short) for an entry.

When `entry_rules.mode` is `"any"`, at least ONE signal returning a
non-neutral direction triggers an entry in that direction.

#### Scenario: AND mode entry — all signals agree
- **WHEN** entry mode is `"all"` and ema_cross returns "long" and rsi_zone returns "long"
- **THEN** the adapter enters a long position

#### Scenario: AND mode entry — signals disagree
- **WHEN** entry mode is `"all"` and ema_cross returns "long" but rsi_zone returns "neutral"
- **THEN** no entry is taken

#### Scenario: OR mode entry — one signal fires
- **WHEN** entry mode is `"any"` and bb_breakout returns "long" but macd_cross returns "neutral"
- **THEN** the adapter enters a long position

#### Scenario: Conflicting directions in OR mode
- **WHEN** entry mode is `"any"` and one signal returns "long" and another returns "short"
- **THEN** no entry is taken (conflicting signals cancel out)

#### Scenario: Warmup gate blocks early trading
- **WHEN** the configured signals require 200 completed bars but only 120 are available
- **THEN** the adapter does not submit entry or exit orders

### Requirement: ta_composite SHALL evaluate exit rules when in position
When a position is held, the adapter SHALL evaluate `exit_rules.signals`
each tick. Exit rules support `invert: true` to reverse a signal's direction
(e.g. an inverted ema_cross exits on the opposite cross).

#### Scenario: Exit on inverted EMA cross
- **WHEN** holding a long position and exit_rules contains ema_cross with `invert: true`
- **AND** EMA fast crosses below slow
- **THEN** the adapter closes the position

#### Scenario: Exit on RSI extreme
- **WHEN** holding a long position and exit_rules contains rsi_zone with `trigger: extreme`
- **AND** RSI enters the overbought zone
- **THEN** the adapter closes the position

### Requirement: ta_composite SHALL manage positions with ATR-based stops
The adapter SHALL support configurable position management:
- `sl_atr_mult`: stop-loss distance as ATR multiple
- `tp_atr_mult`: take-profit distance as ATR multiple
- `trail_activate_r`: R-multiple at which trailing stop activates
- `trail_offset_atr`: trailing stop distance as ATR multiple
- `max_hold_minutes`: maximum position hold time before forced exit
- `cooldown_s`: minimum seconds between closing and opening a new position

#### Scenario: Stop-loss hit
- **WHEN** a long position is held and price falls to `entry - sl_atr_mult * ATR`
- **THEN** the adapter submits a MARKET sell order to close the position

#### Scenario: Take-profit hit
- **WHEN** a long position is held and price rises to `entry + tp_atr_mult * ATR`
- **THEN** the adapter submits a MARKET sell order to close the position

#### Scenario: Trailing stop activation and trigger
- **WHEN** unrealized profit reaches `trail_activate_r` R-multiples
- **AND** price then retraces by `trail_offset_atr * ATR` from the high-water mark
- **THEN** the adapter closes the position

#### Scenario: Max hold time exit
- **WHEN** position has been held for longer than `max_hold_minutes`
- **THEN** the adapter closes the position regardless of P&L

#### Scenario: Cooldown enforced
- **WHEN** a position was closed less than `cooldown_s` seconds ago
- **THEN** no new entry is taken even if entry signals fire

### Requirement: ta_composite SHALL enforce daily risk limits
The adapter SHALL track daily P&L and halt trading when
`max_daily_loss_pct` of equity is breached.

#### Scenario: Daily loss limit
- **WHEN** equity drops more than `max_daily_loss_pct` below the day's opening equity
- **THEN** no new entries are taken for the remainder of the day

### Requirement: ta_composite SHALL size positions as fraction of equity
The adapter SHALL compute position size as `equity * risk_pct / mid_price`,
quantized by `InstrumentSpec`.

#### Scenario: Position sizing
- **WHEN** equity is 1000 USDT, risk_pct is 0.10, and mid is 50000
- **THEN** the adapter computes base quantity as `(1000 * 0.10) / 50000 = 0.002 BTC`

### Requirement: ta_composite config SHALL validate at construction
`TaCompositeConfig` SHALL validate that:
- `entry_rules.signals` is non-empty
- All signal types exist in `SIGNAL_REGISTRY`
- Each configured signal only provides parameters accepted by its registered signal function
- `entry_rules.mode` is `"all"` or `"any"`
- `exit_rules.mode`, when provided, is `"all"` or `"any"`
- `sl_atr_mult > 0` and `tp_atr_mult > 0`
- `entry_order_type` is `"market"` or `"limit"`
- `limit_entry_offset_atr >= 0` when `entry_order_type == "limit"`

#### Scenario: Empty entry signals
- **WHEN** `entry_rules.signals` is an empty list
- **THEN** `TaCompositeConfig` raises `ValueError`

#### Scenario: Invalid signal type
- **WHEN** a signal references type `"nonexistent_signal"`
- **THEN** construction raises `ValueError` listing available signal types

#### Scenario: Invalid signal parameter
- **WHEN** a signal config includes a parameter not accepted by its registered signal function
- **THEN** construction raises `ValueError` naming the signal type and invalid parameter

### Requirement: ta_composite SHALL support both MARKET and LIMIT entries
The adapter SHALL support `entry_order_type` config: `"market"` (default)
or `"limit"` with an ATR-based offset.

#### Scenario: Market entry
- **WHEN** `entry_order_type` is `"market"`
- **THEN** entry orders are submitted as `PaperOrderType.MARKET`

#### Scenario: Limit entry
- **WHEN** `entry_order_type` is `"limit"` and `limit_entry_offset_atr` is `0.1`
- **THEN** buy entries are placed at `mid - 0.1 * ATR` as `PaperOrderType.LIMIT`
