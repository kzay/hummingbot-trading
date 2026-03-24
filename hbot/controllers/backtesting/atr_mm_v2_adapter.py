"""ATR-adaptive MM v2: multi-timeframe + volatility-inverse sizing.

Improvements over v1:
  - HTF trend filter: aggregates 1m candles into 15m bars, uses 15m EMA
    to determine trend direction. Only quotes aggressively on the trend side.
  - Volatility-inverse sizing: scales position size down when ATR is elevated,
    up when ATR is compressed — more size during mean-reversion, less during trends.
  - Spread floor from fill model awareness: ensures spreads are wide enough
    to survive the 40% fill probability + partial fill dynamics.
  - Inventory half-life tracking: measures time to flatten, adjusts urgency.
"""
from __future__ import annotations

import logging
from collections import deque
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
class AtrMMv2Config:
    atr_period: int = 14
    min_warmup_bars: int = 30

    spread_atr_mult: Decimal = Decimal("0.3")
    min_spread_pct: Decimal = Decimal("0.0008")
    max_spread_pct: Decimal = Decimal("0.0100")

    levels: int = 3
    level_spacing: Decimal = Decimal("0.5")

    base_size_pct: Decimal = Decimal("0.025")

    vol_sizing_enabled: bool = True
    vol_sizing_lookback: int = 60
    vol_sizing_min_mult: Decimal = Decimal("0.3")
    vol_sizing_max_mult: Decimal = Decimal("2.0")

    htf_enabled: bool = True
    htf_bars: int = 15
    htf_ema_period: int = 20
    htf_trend_filter: Decimal = Decimal("0.0003")
    htf_contra_size_mult: Decimal = Decimal("0.3")

    max_inventory_pct: Decimal = Decimal("0.15")
    inventory_skew_mult: Decimal = Decimal("3.0")
    inventory_size_penalty: Decimal = Decimal("0.5")

    inventory_age_decay_minutes: int = 45
    urgency_spread_reduction: Decimal = Decimal("0.4")

    max_daily_loss_pct: Decimal = Decimal("0.025")
    max_drawdown_pct: Decimal = Decimal("0.05")


class _IncrementalEmaAtr:
    """O(1) per-tick EMA and ATR."""

    def __init__(self, ema_period: int = 20, atr_period: int = 14) -> None:
        self._ema_alpha = _TWO / Decimal(ema_period + 1)
        self._atr_alpha = _TWO / Decimal(atr_period + 1)
        self._ema: Decimal = _ZERO
        self._atr: Decimal = _ZERO
        self._prev_close: Decimal = _ZERO
        self._count: int = 0

    def add_bar(self, high: Decimal, low: Decimal, close: Decimal) -> None:
        if self._count == 0:
            self._ema = close
            self._atr = high - low
            self._prev_close = close
            self._count += 1
            return

        tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._atr = self._atr_alpha * tr + (_ONE - self._atr_alpha) * self._atr
        self._ema = self._ema_alpha * close + (_ONE - self._ema_alpha) * self._ema
        self._prev_close = close
        self._count += 1

    @property
    def ema(self) -> Decimal:
        return self._ema

    @property
    def atr(self) -> Decimal:
        return self._atr

    @property
    def count(self) -> int:
        return self._count


class _HTFAggregator:
    """Aggregates 1m candles into N-minute bars and tracks EMA on the HTF."""

    def __init__(self, bar_minutes: int = 15, ema_period: int = 20) -> None:
        self._bar_minutes = bar_minutes
        self._ema_alpha = _TWO / Decimal(ema_period + 1)
        self._ema: Decimal = _ZERO
        self._count: int = 0

        self._current_high: Decimal = _ZERO
        self._current_low: Decimal = Decimal("999999999")
        self._current_open: Decimal = _ZERO
        self._current_close: Decimal = _ZERO
        self._bars_in_current: int = 0

    def add_1m_bar(self, high: Decimal, low: Decimal, close: Decimal) -> bool:
        if self._bars_in_current == 0:
            self._current_open = close
            self._current_high = high
            self._current_low = low
        else:
            self._current_high = max(self._current_high, high)
            self._current_low = min(self._current_low, low)
        self._current_close = close
        self._bars_in_current += 1

        if self._bars_in_current >= self._bar_minutes:
            if self._count == 0:
                self._ema = self._current_close
            else:
                self._ema = self._ema_alpha * self._current_close + (_ONE - self._ema_alpha) * self._ema
            self._count += 1
            self._bars_in_current = 0
            self._current_high = _ZERO
            self._current_low = Decimal("999999999")
            return True
        return False

    @property
    def ema(self) -> Decimal:
        return self._ema

    @property
    def ready(self) -> bool:
        return self._count >= 2

    def trend_strength(self, mid: Decimal) -> Decimal:
        if self._ema <= _ZERO or mid <= _ZERO:
            return _ZERO
        return (mid - self._ema) / self._ema


class _VolTracker:
    """Tracks rolling ATR percentile for volatility-inverse sizing."""

    def __init__(self, lookback: int = 60) -> None:
        self._ring: deque[Decimal] = deque(maxlen=lookback)

    def add(self, atr_pct: Decimal) -> None:
        self._ring.append(atr_pct)

    @property
    def percentile(self) -> Decimal:
        if len(self._ring) < 10:
            return Decimal("0.5")
        sorted_vals = sorted(self._ring)
        current = self._ring[-1]
        rank = sum(1 for v in sorted_vals if v <= current)
        return Decimal(str(rank / len(sorted_vals)))


class AtrMMv2Adapter:
    """ATR-adaptive MM v2 — multi-timeframe + volatility sizing."""

    def __init__(
        self,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: AtrMMv2Config | None = None,
    ) -> None:
        self._desk = desk
        self._instrument_id = instrument_id
        self._instrument_spec = instrument_spec
        self._cfg = config or AtrMMv2Config()

        self._ltf = _IncrementalEmaAtr(ema_period=20, atr_period=self._cfg.atr_period)
        self._htf = _HTFAggregator(
            bar_minutes=self._cfg.htf_bars,
            ema_period=self._cfg.htf_ema_period,
        )
        self._vol_tracker = _VolTracker(lookback=self._cfg.vol_sizing_lookback)

        self._regime_name: str = "adaptive"
        self._last_submitted_count: int = 0
        self._tick_count: int = 0
        self._daily_equity_open: Decimal = _ZERO
        self._daily_equity_peak: Decimal = _ZERO
        self._current_day: int = -1
        self._last_candle_ts: int = 0
        self._position_entry_ts: float = 0.0

    @property
    def regime_name(self) -> str:
        return self._regime_name

    @property
    def last_submitted_count(self) -> int:
        return self._last_submitted_count

    def warmup(self, candles: list[CandleRow]) -> int:
        for c in candles:
            self._ltf.add_bar(c.high, c.low, c.close)
            self._htf.add_1m_bar(c.high, c.low, c.close)
            if self._ltf.count > 1 and c.close > _ZERO:
                self._vol_tracker.add(self._ltf.atr / c.close)
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
            self._ltf.add_bar(candle.high, candle.low, candle.close)
            self._htf.add_1m_bar(candle.high, candle.low, candle.close)
            self._last_candle_ts = candle.timestamp_ms
            if mid > _ZERO:
                self._vol_tracker.add(self._ltf.atr / mid)

        day = int(now_s // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_equity_open = equity_quote
            self._daily_equity_peak = equity_quote
        self._daily_equity_peak = max(self._daily_equity_peak, equity_quote)

        if self._ltf.count < cfg.min_warmup_bars:
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

        atr = self._ltf.atr
        if atr <= _ZERO:
            return None

        atr_pct = atr / mid
        base_spread = atr_pct * cfg.spread_atr_mult
        base_spread = max(cfg.min_spread_pct, min(cfg.max_spread_pct, base_spread))

        # --- Inventory state ---
        inventory_pct = _ZERO
        if mid > _ZERO and equity_quote > _ZERO:
            inventory_pct = (position_base * mid) / equity_quote

        has_position = abs(inventory_pct) > Decimal("0.001")
        if has_position:
            if self._position_entry_ts <= 0:
                self._position_entry_ts = now_s
        else:
            self._position_entry_ts = 0.0

        inv_ratio = min(_ONE, abs(inventory_pct) / cfg.max_inventory_pct) if cfg.max_inventory_pct > _ZERO else _ZERO

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

        # --- Volatility-inverse sizing ---
        vol_size_mult = _ONE
        if cfg.vol_sizing_enabled:
            vol_pct = self._vol_tracker.percentile
            vol_size_mult = cfg.vol_sizing_max_mult - (cfg.vol_sizing_max_mult - cfg.vol_sizing_min_mult) * vol_pct
            vol_size_mult = max(cfg.vol_sizing_min_mult, min(cfg.vol_sizing_max_mult, vol_size_mult))

        base_quote = equity_quote * cfg.base_size_pct * vol_size_mult
        size_penalty = _ONE - inv_ratio * cfg.inventory_size_penalty

        # --- HTF trend filter ---
        htf_trend = _ZERO
        buy_trend_mult = _ONE
        sell_trend_mult = _ONE
        if cfg.htf_enabled and self._htf.ready:
            htf_trend = self._htf.trend_strength(mid)
            if htf_trend > cfg.htf_trend_filter:
                sell_trend_mult = cfg.htf_contra_size_mult
                self._regime_name = "adaptive_up"
            elif htf_trend < -cfg.htf_trend_filter:
                buy_trend_mult = cfg.htf_contra_size_mult
                self._regime_name = "adaptive_down"
            else:
                self._regime_name = "adaptive_neutral"
        else:
            vol_label = "high" if atr_pct > Decimal("0.003") else ("mid" if atr_pct > Decimal("0.001") else "low")
            self._regime_name = f"adaptive_{vol_label}"

        at_max_long = inventory_pct >= cfg.max_inventory_pct
        at_max_short = inventory_pct <= -cfg.max_inventory_pct

        self._cancel_all()
        submitted = 0

        for level in range(cfg.levels):
            level_mult = _ONE + cfg.level_spacing * Decimal(level)

            if not at_max_long:
                buy_size = base_quote * size_penalty * buy_trend_mult / mid
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
                        source_bot="atr_mm_v2",
                    )
                    submitted += 1

            if not at_max_short:
                sell_size = base_quote * size_penalty * sell_trend_mult / mid
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
                        source_bot="atr_mm_v2",
                    )
                    submitted += 1

        self._last_submitted_count = submitted
        return {
            "side": self._regime_name,
            "atr_pct": float(atr_pct),
            "base_spread": float(base_spread),
            "buy_spread": float(buy_spread),
            "sell_spread": float(sell_spread),
            "inventory_pct": float(inventory_pct),
            "vol_size_mult": float(vol_size_mult),
            "htf_trend": float(htf_trend),
            "urgency": float(urgency),
        }

    def record_fill_notional(self, notional: Decimal) -> None:
        pass

    def _cancel_all(self) -> None:
        try:
            self._desk.cancel_all(self._instrument_id)
        except Exception:
            pass
