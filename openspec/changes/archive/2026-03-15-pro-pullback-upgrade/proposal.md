## Why

The pullback_v1 strategy has correct signal infrastructure (regime gates, ATR-adaptive zones, absorption/delta-trap detectors, contra-funding gate) but lacks the position management and entry quality that separates a prototype from a pro-desk strategy. Fixed 45/90bps SL/TP gets noise-hunted in high vol, no trailing stop means winners are capped at 90bps while losers run the full 45bps, and market-order entries donate 5-10bps to adverse selection. These gaps compound to negative expected value despite correct signal logic.

## What Changes

- **Dynamic ATR-scaled SL/TP at executor creation**: Replace fixed config `stop_loss`/`take_profit` with ATR-derived values computed each tick and injected into the `triple_barrier_config` before executor creation. SL = `pb_sl_atr_mult * ATR / mid`, TP = `pb_tp_atr_mult * ATR / mid`, clamped to configurable floor/cap.
- **BB basis slope trend quality gate**: New signal gate that checks the 20-SMA (BB basis) is actually moving in the expected direction over the last N bars. Computed from raw `PriceBuffer.bars` OHLC data. Blocks entry when ADX says "trending" but the SMA is flat or counter-trending.
- **Code-side trailing stop state machine**: Post-entry position monitor that tracks high-water mark (for longs) and emits a MARKET close action when price retraces by `pb_trail_offset_atr_mult * ATR` from peak. Activates only after position is in profit by `pb_trail_activate_atr_mult * ATR`. Runs in the tick loop via `_manage_pb_position()`.
- **Partial profit-taking at 1R**: When unrealized PnL reaches 1x the initial risk distance (SL), close `pb_partial_take_pct` (default 33%) via a partial close executor. Remaining position rides with the trailing stop.
- **Limit entry at zone boundary**: Replace MARKET entry with LIMIT orders at `bb_basis * (1 - pb_entry_offset_pct)` for longs. Cancel after `pb_entry_timeout_s` if not filled. Improves average fill by 5-10bps.
- **Multi-timeframe trend confirmation via long-period SMA**: Add `pb_trend_sma_period` (default 50) gate. Long only when `mid > SMA(50)`. Short only when `mid < SMA(50)`. Computed from existing `PriceBuffer.sma()`.
- **Adverse selection entry filter**: Check spread width and book depth before entry. Block when `spread > pb_max_entry_spread_pct` or depth imbalance is extreme (opposing the trade direction).
- **Signal frequency diagnostics**: Counter tracking signals/24h with warning log when below configurable threshold. Observability only — no behavioral change.

## Capabilities

### New Capabilities
- `atr-dynamic-barriers`: ATR-scaled SL/TP computation, floor/cap clamping, and injection into executor triple_barrier_config at creation time
- `trend-quality-gate`: BB basis slope filter and long-period SMA trend confirmation gate
- `trailing-stop-manager`: Code-side trailing stop state machine with high-water mark tracking and partial profit-taking at 1R
- `entry-quality`: Limit-order entry at zone boundary, adverse selection spread/depth filter, entry timeout cancellation
- `signal-diagnostics`: Signal frequency counter, 24h rolling window, warning threshold logging

### Modified Capabilities
<!-- No existing specs to modify — all changes are additions to pullback_v1.py -->

## Impact

- **Files modified**: `hbot/controllers/bots/bot7/pullback_v1.py` (controller + config), `hbot/data/bot7/conf/controllers/epp_v2_4_bot7_pullback_paper.yml` (YAML config), `hbot/tests/controllers/test_epp_v2_4_bot7_pullback.py` (tests)
- **Architectural constraint**: Hummingbot PositionExecutor barriers are immutable after creation — SL/TP must be set at executor creation time, not updated dynamically. Trailing stop MUST be code-side (emit close actions), not executor-side.
- **PriceBuffer dependency**: Slope computation uses raw `self._price_buffer.bars` (MinuteBar OHLC). No PriceBuffer modifications needed — existing `bars` property and `sma()` method suffice.
- **No base class modifications**: All changes confined to pullback_v1.py controller layer. No changes to shared runtime kernel, base classes, or executor framework.
- **New config params**: ~20 new `pb_*` fields in PullbackV1Config, all with sensible defaults matching current behavior when not explicitly set.
