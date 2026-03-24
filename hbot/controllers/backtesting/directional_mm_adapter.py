"""Directional market-making adapter for bot7 backtesting.

Combines the high fill rate of MM (limit orders, maker fees) with directional
bias from trend indicators.  Generates many closed round-trips by:
  - Always quoting both sides (like an MM)
  - Skewing spreads in the trend direction (tighter on the favored side)
  - Adjusting size: larger on the trend side, smaller contra-trend
  - Tight inventory management: shrink contra-trend quotes when inventory builds

Key insight from prior research:
  - Pure directional (MARKET orders) bleeds on fees (100% taker)
  - Pure MM (symmetric spreads) has 39% win rate but bad R:R
  - Combining both: maker fills + trend bias should improve win rate AND R:R
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
class DirectionalMMConfig:
    # Trend detection
    ema_fast: int = 12
    ema_slow: int = 34
    atr_period: int = 14

    # Spread configuration (as fraction of price, not bps)
    base_spread: Decimal = Decimal("0.0020")
    max_spread: Decimal = Decimal("0.0060")
    trend_skew: Decimal = Decimal("0.50")

    # Size configuration
    base_size_pct: Decimal = Decimal("0.03")
    trend_size_mult: Decimal = Decimal("1.5")
    contra_size_mult: Decimal = Decimal("0.5")

    # Inventory management
    max_inventory_pct: Decimal = Decimal("0.30")
    inventory_skew_factor: Decimal = Decimal("2.0")

    # Number of levels per side
    levels: int = 2
    level_spacing: Decimal = Decimal("0.50")

    # Risk limits
    max_daily_loss_pct: Decimal = Decimal("0.03")
    max_drawdown_pct: Decimal = Decimal("0.05")

    # Volatility scaling
    vol_spread_mult: Decimal = Decimal("1.5")

    min_warmup_bars: int = 40


class _IncrementalBuffer:
    """O(1) per-tick EMA and ATR."""

    def __init__(self) -> None:
        self._bar_count: int = 0
        self._ema: dict[int, Decimal] = {}
        self._atr: Decimal = _ZERO
        self._prev_close: Decimal = _ZERO

    def add_bar(self, high: Decimal, low: Decimal, close: Decimal) -> None:
        if self._bar_count > 0:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
            alpha_atr = _TWO / Decimal(15)
            self._atr = alpha_atr * tr + (_ONE - alpha_atr) * self._atr
        else:
            self._atr = high - low

        for period in list(self._ema.keys()):
            alpha = _TWO / Decimal(period + 1)
            self._ema[period] = alpha * close + (_ONE - alpha) * self._ema[period]

        self._prev_close = close
        self._bar_count += 1

    @property
    def count(self) -> int:
        return self._bar_count

    def ema(self, period: int) -> Decimal:
        if period not in self._ema:
            self._ema[period] = self._prev_close if self._prev_close > _ZERO else _ZERO
        return self._ema[period]

    @property
    def atr(self) -> Decimal:
        return self._atr


class DirectionalMMAdapter:
    """Trend-biased market-making strategy."""

    def __init__(
        self,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: DirectionalMMConfig | None = None,
    ) -> None:
        self._desk = desk
        self._instrument_id = instrument_id
        self._instrument_spec = instrument_spec
        self._cfg = config or DirectionalMMConfig()
        self._buf = _IncrementalBuffer()
        self._regime_name: str = "neutral"
        self._last_submitted_count: int = 0
        self._tick_count: int = 0
        self._daily_equity_open: Decimal = _ZERO
        self._daily_equity_peak: Decimal = _ZERO
        self._current_day: int = -1
        self._last_candle_ts: int = 0

    @property
    def regime_name(self) -> str:
        return self._regime_name

    @property
    def last_submitted_count(self) -> int:
        return self._last_submitted_count

    def warmup(self, candles: list[CandleRow]) -> int:
        for c in candles:
            self._buf.add_bar(c.high, c.low, c.close)
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
            self._buf.add_bar(candle.high, candle.low, candle.close)
            self._last_candle_ts = candle.timestamp_ms
        elif mid > _ZERO:
            self._buf.add_bar(mid, mid, mid)

        day = int(now_s // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_equity_open = equity_quote
            self._daily_equity_peak = equity_quote
        self._daily_equity_peak = max(self._daily_equity_peak, equity_quote)

        if self._buf.count < cfg.min_warmup_bars:
            return None
        if mid <= _ZERO or equity_quote <= _ZERO:
            return None

        # Risk gates
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

        ema_fast = self._buf.ema(cfg.ema_fast)
        ema_slow = self._buf.ema(cfg.ema_slow)
        atr = self._buf.atr

        # Determine trend direction
        trend_strength = _ZERO
        if ema_slow > _ZERO:
            trend_strength = (ema_fast - ema_slow) / ema_slow
        is_uptrend = trend_strength > Decimal("0.0001")
        is_downtrend = trend_strength < Decimal("-0.0001")

        if is_uptrend:
            self._regime_name = "up"
        elif is_downtrend:
            self._regime_name = "down"
        else:
            self._regime_name = "neutral"

        # Volatility-scaled base spread
        vol_spread = _ZERO
        if mid > _ZERO and atr > _ZERO:
            vol_spread = (atr / mid) * cfg.vol_spread_mult
        effective_spread = max(cfg.base_spread, min(cfg.max_spread, cfg.base_spread + vol_spread))

        # Trend skew: tighten spread on favored side, widen on contra side
        skew = abs(trend_strength) * cfg.trend_skew * Decimal("100")
        skew = min(skew, Decimal("0.80"))

        if is_uptrend:
            buy_spread = effective_spread * (_ONE - skew)
            sell_spread = effective_spread * (_ONE + skew)
        elif is_downtrend:
            buy_spread = effective_spread * (_ONE + skew)
            sell_spread = effective_spread * (_ONE - skew)
        else:
            buy_spread = effective_spread
            sell_spread = effective_spread

        buy_spread = max(Decimal("0.0005"), buy_spread)
        sell_spread = max(Decimal("0.0005"), sell_spread)

        # Inventory skew: pull quotes away when inventory builds
        inventory_pct = _ZERO
        if equity_quote > _ZERO and mid > _ZERO:
            inventory_pct = (position_base * mid) / equity_quote
        inv_skew = inventory_pct * cfg.inventory_skew_factor

        buy_spread += max(_ZERO, inv_skew * Decimal("0.01"))
        sell_spread -= max(_ZERO, inv_skew * Decimal("0.01"))
        sell_spread = max(Decimal("0.0005"), sell_spread)

        # Size: trend side gets more, contra side gets less
        base_quote = equity_quote * cfg.base_size_pct
        if is_uptrend:
            buy_quote = base_quote * cfg.trend_size_mult
            sell_quote = base_quote * cfg.contra_size_mult
        elif is_downtrend:
            buy_quote = base_quote * cfg.contra_size_mult
            sell_quote = base_quote * cfg.trend_size_mult
        else:
            buy_quote = base_quote
            sell_quote = base_quote

        # Inventory cap: reduce or skip quotes when at max inventory
        if abs(inventory_pct) > cfg.max_inventory_pct:
            if inventory_pct > _ZERO:
                buy_quote = _ZERO
            else:
                sell_quote = _ZERO

        # Cancel old orders and submit new ones
        self._cancel_all()
        submitted = 0

        for level in range(cfg.levels):
            level_mult = _ONE + cfg.level_spacing * Decimal(level)

            # Buy side
            if buy_quote > _ZERO:
                buy_price = self._instrument_spec.quantize_price(
                    mid * (_ONE - buy_spread * level_mult), "buy"
                )
                buy_qty = self._instrument_spec.quantize_size(buy_quote / mid)
                if buy_qty > _ZERO and buy_price > _ZERO:
                    self._desk.submit_order(
                        instrument_id=self._instrument_id,
                        side=OrderSide.BUY,
                        order_type=PaperOrderType.LIMIT,
                        price=buy_price,
                        quantity=buy_qty,
                        source_bot="directional_mm",
                    )
                    submitted += 1

            # Sell side
            if sell_quote > _ZERO:
                sell_price = self._instrument_spec.quantize_price(
                    mid * (_ONE + sell_spread * level_mult), "sell"
                )
                sell_qty = self._instrument_spec.quantize_size(sell_quote / mid)
                if sell_qty > _ZERO and sell_price > _ZERO:
                    self._desk.submit_order(
                        instrument_id=self._instrument_id,
                        side=OrderSide.SELL,
                        order_type=PaperOrderType.LIMIT,
                        price=sell_price,
                        quantity=sell_qty,
                        source_bot="directional_mm",
                    )
                    submitted += 1

        self._last_submitted_count = submitted
        return {
            "side": self._regime_name,
            "buy_spread": float(buy_spread),
            "sell_spread": float(sell_spread),
            "trend_strength": float(trend_strength),
            "inventory_pct": float(inventory_pct),
        }

    def record_fill_notional(self, notional: Decimal) -> None:
        pass

    def _cancel_all(self) -> None:
        try:
            self._desk.cancel_all(self._instrument_id)
        except Exception:
            pass
