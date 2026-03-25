"""ATR-adaptive market-making adapter for backtesting.

Professional-grade MM that uses ATR to dynamically set spreads and position
limits, with inventory mean-reversion and time-based urgency for flat positions.

Key design principles:
  - Spreads scale linearly with recent ATR (wider in volatile markets)
  - Inventory drives spread skew (wider on the side that would increase exposure)
  - Time-based position decay: if inventory lingers, gradually reduce quotes
    on the adding side and tighten quotes on the reducing side
  - No regime buckets — continuous adaptation via ATR

The strategy quotes both sides every tick with LIMIT orders (100% maker fills).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from controllers.backtesting.types import CandleRow
from simulation.desk import PaperDesk
from simulation.types import (
    InstrumentId,
    InstrumentSpec,
    OrderSide,
    PaperOrderType,
)

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")
_HUNDRED = Decimal("100")


@dataclass
class AtrMMConfig:
    atr_period: int = 14
    min_warmup_bars: int = 30

    spread_atr_mult: Decimal = Decimal("0.5")
    min_spread_pct: Decimal = Decimal("0.0008")
    max_spread_pct: Decimal = Decimal("0.0100")

    levels: int = 3
    level_spacing: Decimal = Decimal("0.5")

    base_size_pct: Decimal = Decimal("0.02")

    max_inventory_pct: Decimal = Decimal("0.15")
    inventory_skew_mult: Decimal = Decimal("3.0")
    inventory_size_penalty: Decimal = Decimal("0.5")

    inventory_age_decay_minutes: int = 60
    urgency_spread_reduction: Decimal = Decimal("0.3")

    max_daily_loss_pct: Decimal = Decimal("0.03")
    max_drawdown_pct: Decimal = Decimal("0.06")


class _IncrementalATR:
    """O(1) per-tick ATR using exponential smoothing."""

    def __init__(self, period: int = 14) -> None:
        self._period = period
        self._alpha = _TWO / Decimal(period + 1)
        self._atr: Decimal = _ZERO
        self._prev_close: Decimal = _ZERO
        self._bar_count: int = 0

    def add_bar(self, high: Decimal, low: Decimal, close: Decimal) -> None:
        if self._bar_count == 0:
            self._atr = high - low
            self._prev_close = close
            self._bar_count += 1
            return

        tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._atr = self._alpha * tr + (_ONE - self._alpha) * self._atr
        self._prev_close = close
        self._bar_count += 1

    @property
    def value(self) -> Decimal:
        return self._atr

    @property
    def count(self) -> int:
        return self._bar_count


class AtrMMAdapter:
    """ATR-adaptive market maker — continuous volatility-driven quoting."""

    def __init__(
        self,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: AtrMMConfig | None = None,
    ) -> None:
        self._desk = desk
        self._instrument_id = instrument_id
        self._instrument_spec = instrument_spec
        self._cfg = config or AtrMMConfig()
        self._atr = _IncrementalATR(self._cfg.atr_period)
        self._regime_name: str = "adaptive"
        self._last_submitted_count: int = 0
        self._tick_count: int = 0
        self._daily_equity_open: Decimal = _ZERO
        self._daily_equity_peak: Decimal = _ZERO
        self._current_day: int = -1
        self._last_candle_ts: int = 0
        self._position_entry_ts: float = 0.0
        self._last_flat_ts: float = 0.0

    @property
    def regime_name(self) -> str:
        return self._regime_name

    @property
    def last_submitted_count(self) -> int:
        return self._last_submitted_count

    def warmup(self, candles: list[CandleRow]) -> int:
        for c in candles:
            self._atr.add_bar(c.high, c.low, c.close)
        return len(candles)

    def tick(
        self,
        now_s: float,
        mid: Decimal,
        book: Any,
        equity_quote: Decimal,
        position_base: Decimal,
        candle: Any = None,
    ) -> Any:
        self._tick_count += 1
        self._last_submitted_count = 0
        cfg = self._cfg

        if candle is not None and candle.timestamp_ms != self._last_candle_ts:
            self._atr.add_bar(candle.high, candle.low, candle.close)
            self._last_candle_ts = candle.timestamp_ms

        day = int(now_s // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_equity_open = equity_quote
            self._daily_equity_peak = equity_quote
        self._daily_equity_peak = max(self._daily_equity_peak, equity_quote)

        if self._atr.count < cfg.min_warmup_bars:
            return None
        if mid <= _ZERO or equity_quote <= _ZERO:
            return None

        if self._daily_equity_open > _ZERO:
            daily_loss = (self._daily_equity_open - equity_quote) / self._daily_equity_open
            if daily_loss > cfg.max_daily_loss_pct:
                self._cancel_all()
                return {"side": "off", "reason": "daily_risk"}
        if self._daily_equity_peak > _ZERO:
            dd = (self._daily_equity_peak - equity_quote) / self._daily_equity_peak
            if dd > cfg.max_drawdown_pct:
                self._cancel_all()
                return {"side": "off", "reason": "drawdown"}

        atr = self._atr.value
        if atr <= _ZERO:
            return None

        atr_pct = atr / mid
        base_spread = atr_pct * cfg.spread_atr_mult
        base_spread = max(cfg.min_spread_pct, min(cfg.max_spread_pct, base_spread))

        inventory_pct = _ZERO
        if mid > _ZERO and equity_quote > _ZERO:
            inventory_pct = (position_base * mid) / equity_quote

        has_position = abs(inventory_pct) > Decimal("0.001")

        if has_position:
            if self._position_entry_ts <= 0:
                self._position_entry_ts = now_s
        else:
            self._position_entry_ts = 0.0
            self._last_flat_ts = now_s

        inv_ratio = abs(inventory_pct) / cfg.max_inventory_pct if cfg.max_inventory_pct > _ZERO else _ZERO
        inv_ratio = min(inv_ratio, _ONE)

        skew = inventory_pct * cfg.inventory_skew_mult

        buy_spread = base_spread * (_ONE + max(_ZERO, skew))
        sell_spread = base_spread * (_ONE + max(_ZERO, -skew))

        buy_spread = max(cfg.min_spread_pct, buy_spread)
        sell_spread = max(cfg.min_spread_pct, sell_spread)

        age_minutes = (now_s - self._position_entry_ts) / 60 if self._position_entry_ts > 0 else 0
        urgency = _ZERO
        if age_minutes > 0 and cfg.inventory_age_decay_minutes > 0:
            urgency = min(_ONE, Decimal(str(age_minutes)) / Decimal(cfg.inventory_age_decay_minutes))

        if inventory_pct > Decimal("0.001"):
            sell_spread *= (_ONE - urgency * cfg.urgency_spread_reduction)
            sell_spread = max(cfg.min_spread_pct, sell_spread)
        elif inventory_pct < Decimal("-0.001"):
            buy_spread *= (_ONE - urgency * cfg.urgency_spread_reduction)
            buy_spread = max(cfg.min_spread_pct, buy_spread)

        base_quote = equity_quote * cfg.base_size_pct
        size_penalty = _ONE - inv_ratio * cfg.inventory_size_penalty

        at_max_long = inventory_pct >= cfg.max_inventory_pct
        at_max_short = inventory_pct <= -cfg.max_inventory_pct

        self._cancel_all()
        submitted = 0

        for level in range(cfg.levels):
            level_mult = _ONE + cfg.level_spacing * Decimal(level)

            if not at_max_long:
                buy_size = base_quote * size_penalty / mid
                buy_qty = self._instrument_spec.quantize_size(buy_size)
                buy_price = self._instrument_spec.quantize_price(
                    mid * (_ONE - buy_spread * level_mult), "buy"
                )
                if buy_qty > _ZERO and buy_price > _ZERO:
                    self._desk.submit_order(
                        instrument_id=self._instrument_id,
                        side=OrderSide.BUY,
                        order_type=PaperOrderType.LIMIT,
                        price=buy_price,
                        quantity=buy_qty,
                        source_bot="atr_mm",
                    )
                    submitted += 1

            if not at_max_short:
                sell_size = base_quote * size_penalty / mid
                sell_qty = self._instrument_spec.quantize_size(sell_size)
                sell_price = self._instrument_spec.quantize_price(
                    mid * (_ONE + sell_spread * level_mult), "sell"
                )
                if sell_qty > _ZERO and sell_price > _ZERO:
                    self._desk.submit_order(
                        instrument_id=self._instrument_id,
                        side=OrderSide.SELL,
                        order_type=PaperOrderType.LIMIT,
                        price=sell_price,
                        quantity=sell_qty,
                        source_bot="atr_mm",
                    )
                    submitted += 1

        vol_label = "high" if atr_pct > Decimal("0.003") else ("mid" if atr_pct > Decimal("0.001") else "low")
        self._regime_name = f"adaptive_{vol_label}"
        self._last_submitted_count = submitted

        return {
            "side": self._regime_name,
            "atr_pct": float(atr_pct),
            "base_spread": float(base_spread),
            "buy_spread": float(buy_spread),
            "sell_spread": float(sell_spread),
            "inventory_pct": float(inventory_pct),
            "urgency": float(urgency),
        }

    def record_fill_notional(self, notional: Decimal) -> None:
        pass

    def _cancel_all(self) -> None:
        try:
            self._desk.cancel_all(self._instrument_id)
        except Exception:
            pass  # Justification: best-effort teardown during simulation — desk may already be closed
