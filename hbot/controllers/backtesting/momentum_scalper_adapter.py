"""Momentum scalper adapter for bot7 backtesting.

High-frequency directional strategy that trades EMA crossovers with MARKET
orders for guaranteed fills.  Designed to generate many closed round-trips
(dozens to hundreds per quarter) rather than waiting for rare composite
pullback signals.

Signal logic:
  - Fast EMA crosses above slow EMA → buy
  - Fast EMA crosses below slow EMA → sell
  - RSI used as a filter (no entries in overbought/oversold extremes)
  - ADX used as trend-strength filter (skip when ADX < threshold)
  - ATR-scaled stop-loss and take-profit

Exit management:
  - Hard stop-loss at entry ± sl_atr_mult × ATR
  - Take-profit at entry ± tp_atr_mult × ATR
  - Trailing stop after trail_activate_r × risk distance
  - Max hold time cutoff
  - All exits via MARKET orders for guaranteed closure
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
class MomentumScalperConfig:
    ema_fast: int = 8
    ema_slow: int = 21
    rsi_period: int = 14
    atr_period: int = 14
    adx_period: int = 14

    rsi_overbought: Decimal = Decimal("72")
    rsi_oversold: Decimal = Decimal("28")
    adx_min: Decimal = Decimal("15")

    # Position sizing as fraction of equity
    risk_pct: Decimal = Decimal("0.10")

    # ATR-based stops
    sl_atr_mult: Decimal = Decimal("1.5")
    tp_atr_mult: Decimal = Decimal("2.0")

    # Trailing stop
    trail_activate_r: Decimal = Decimal("1.0")
    trail_offset_atr: Decimal = Decimal("0.8")

    # Max hold time
    max_hold_minutes: int = 120

    # Cooldown between trades (seconds)
    cooldown_s: int = 300

    # Risk limits
    max_daily_loss_pct: Decimal = Decimal("0.03")

    min_warmup_bars: int = 30

    # Entry order type: "market" or "limit"
    entry_order_type: str = "market"
    # For limit entries: offset from mid in ATR fractions (negative = aggressive)
    limit_entry_offset_atr: Decimal = Decimal("0.1")


@dataclass
class _PositionState:
    side: str = "off"
    entry_price: Decimal = _ZERO
    entry_ts: float = 0.0
    sl_price: Decimal = _ZERO
    tp_price: Decimal = _ZERO
    risk_dist: Decimal = _ZERO
    trail_active: bool = False
    trail_hwm: Decimal = _ZERO
    trail_lwm: Decimal = Decimal("999999999")


class _IndicatorBuffer:
    """Incremental indicator computation — O(1) per tick."""

    def __init__(self, max_bars: int = 2000) -> None:
        self._closes: deque[Decimal] = deque(maxlen=max_bars)
        self._highs: deque[Decimal] = deque(maxlen=max_bars)
        self._lows: deque[Decimal] = deque(maxlen=max_bars)
        self._ema_state: dict[int, Decimal] = {}
        self._rsi_avg_gain: dict[int, Decimal] = {}
        self._rsi_avg_loss: dict[int, Decimal] = {}
        self._atr_state: dict[int, Decimal] = {}
        self._adx_atr: Decimal = _ZERO
        self._adx_plus_di: Decimal = _ZERO
        self._adx_minus_di: Decimal = _ZERO
        self._adx_val: Decimal = _ZERO
        self._adx_initialized: bool = False
        self._bar_count: int = 0

    def add_bar(self, high: Decimal, low: Decimal, close: Decimal) -> None:
        prev_close = self._closes[-1] if self._closes else close
        prev_high = self._highs[-1] if self._highs else high
        prev_low = self._lows[-1] if self._lows else low

        self._closes.append(close)
        self._highs.append(high)
        self._lows.append(low)
        self._bar_count += 1

        for period, prev_ema in list(self._ema_state.items()):
            alpha = _TWO / Decimal(period + 1)
            self._ema_state[period] = alpha * close + (_ONE - alpha) * prev_ema

        if self._bar_count > 1:
            delta = close - prev_close
            gain = delta if delta > _ZERO else _ZERO
            loss = -delta if delta < _ZERO else _ZERO
            for period in list(self._rsi_avg_gain.keys()):
                p = Decimal(period)
                self._rsi_avg_gain[period] = (self._rsi_avg_gain[period] * (p - _ONE) + gain) / p
                self._rsi_avg_loss[period] = (self._rsi_avg_loss[period] * (p - _ONE) + loss) / p

            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            for period in list(self._atr_state.keys()):
                alpha = _TWO / Decimal(period + 1)
                self._atr_state[period] = alpha * tr + (_ONE - alpha) * self._atr_state[period]

            high_diff = high - prev_high
            low_diff = prev_low - low
            plus_dm = high_diff if high_diff > low_diff and high_diff > _ZERO else _ZERO
            minus_dm = low_diff if low_diff > high_diff and low_diff > _ZERO else _ZERO
            if self._adx_initialized:
                alpha14 = _TWO / Decimal(15)
                self._adx_atr = alpha14 * tr + (_ONE - alpha14) * self._adx_atr
                self._adx_plus_di = alpha14 * plus_dm + (_ONE - alpha14) * self._adx_plus_di
                self._adx_minus_di = alpha14 * minus_dm + (_ONE - alpha14) * self._adx_minus_di
                if self._adx_atr > _ZERO:
                    pdi = self._adx_plus_di / self._adx_atr * _HUNDRED
                    mdi = self._adx_minus_di / self._adx_atr * _HUNDRED
                    di_sum = pdi + mdi
                    dx = abs(pdi - mdi) / di_sum * _HUNDRED if di_sum > _ZERO else _ZERO
                    self._adx_val = alpha14 * dx + (_ONE - alpha14) * self._adx_val

    @property
    def count(self) -> int:
        return self._bar_count

    def ema(self, period: int) -> Decimal:
        if period not in self._ema_state:
            if not self._closes:
                return _ZERO
            alpha = _TWO / Decimal(period + 1)
            val = self._closes[0]
            for c in list(self._closes)[1:]:
                val = alpha * c + (_ONE - alpha) * val
            self._ema_state[period] = val
        return self._ema_state[period]

    def rsi(self, period: int) -> Decimal:
        if period not in self._rsi_avg_gain:
            if len(self._closes) < period + 1:
                return Decimal("50")
            closes = list(self._closes)
            gains = _ZERO
            losses = _ZERO
            for i in range(1, period + 1):
                delta = closes[i] - closes[i - 1]
                if delta > _ZERO:
                    gains += delta
                else:
                    losses += abs(delta)
            avg_g = gains / Decimal(period)
            avg_l = losses / Decimal(period)
            for i in range(period + 1, len(closes)):
                delta = closes[i] - closes[i - 1]
                gain = delta if delta > _ZERO else _ZERO
                loss = -delta if delta < _ZERO else _ZERO
                avg_g = (avg_g * (Decimal(period) - _ONE) + gain) / Decimal(period)
                avg_l = (avg_l * (Decimal(period) - _ONE) + loss) / Decimal(period)
            self._rsi_avg_gain[period] = avg_g
            self._rsi_avg_loss[period] = avg_l

        avg_g = self._rsi_avg_gain[period]
        avg_l = self._rsi_avg_loss[period]
        if avg_g + avg_l == _ZERO:
            return Decimal("50")
        rs = avg_g / avg_l if avg_l > _ZERO else Decimal("100")
        return _HUNDRED - _HUNDRED / (_ONE + rs)

    def atr(self, period: int) -> Decimal:
        if period not in self._atr_state:
            if len(self._highs) < 2:
                return _ZERO
            highs = list(self._highs)
            lows = list(self._lows)
            closes = list(self._closes)
            alpha = _TWO / Decimal(period + 1)
            tr0 = max(highs[1] - lows[1], abs(highs[1] - closes[0]), abs(lows[1] - closes[0]))
            val = tr0
            for i in range(2, len(highs)):
                tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
                val = alpha * tr + (_ONE - alpha) * val
            self._atr_state[period] = val
        return self._atr_state[period]

    def adx(self, period: int = 14) -> Decimal:
        if not self._adx_initialized and len(self._highs) >= period + 1:
            highs = list(self._highs)
            lows = list(self._lows)
            closes = list(self._closes)
            alpha = _TWO / Decimal(period + 1)
            trs = []
            pdms = []
            mdms = []
            for i in range(1, len(highs)):
                tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
                hd = highs[i] - highs[i - 1]
                ld = lows[i - 1] - lows[i]
                trs.append(tr)
                pdms.append(hd if hd > ld and hd > _ZERO else _ZERO)
                mdms.append(ld if ld > hd and ld > _ZERO else _ZERO)
            self._adx_atr = sum(trs[:period], _ZERO) / Decimal(period)
            self._adx_plus_di = sum(pdms[:period], _ZERO) / Decimal(period)
            self._adx_minus_di = sum(mdms[:period], _ZERO) / Decimal(period)
            self._adx_val = Decimal("25")
            for i in range(period, len(trs)):
                self._adx_atr = alpha * trs[i] + (_ONE - alpha) * self._adx_atr
                self._adx_plus_di = alpha * pdms[i] + (_ONE - alpha) * self._adx_plus_di
                self._adx_minus_di = alpha * mdms[i] + (_ONE - alpha) * self._adx_minus_di
                if self._adx_atr > _ZERO:
                    pdi = self._adx_plus_di / self._adx_atr * _HUNDRED
                    mdi = self._adx_minus_di / self._adx_atr * _HUNDRED
                    di_sum = pdi + mdi
                    dx = abs(pdi - mdi) / di_sum * _HUNDRED if di_sum > _ZERO else _ZERO
                    self._adx_val = alpha * dx + (_ONE - alpha) * self._adx_val
            self._adx_initialized = True
        return self._adx_val


class MomentumScalperAdapter:
    """Fast-cycling momentum strategy using EMA crossovers."""

    def __init__(
        self,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: MomentumScalperConfig | None = None,
    ) -> None:
        self._desk = desk
        self._instrument_id = instrument_id
        self._instrument_spec = instrument_spec
        self._cfg = config or MomentumScalperConfig()
        self._buf = _IndicatorBuffer()
        self._pos = _PositionState()
        self._last_exit_ts: float = 0.0
        self._prev_ema_fast: Decimal = _ZERO
        self._prev_ema_slow: Decimal = _ZERO
        self._regime_name: str = "neutral"
        self._last_submitted_count: int = 0
        self._tick_count: int = 0
        self._daily_equity_open: Decimal = _ZERO
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
        if self._buf.count >= 2:
            self._prev_ema_fast = self._buf.ema(self._cfg.ema_fast)
            self._prev_ema_slow = self._buf.ema(self._cfg.ema_slow)
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

        if self._buf.count < cfg.min_warmup_bars:
            return None
        if mid <= _ZERO or equity_quote <= _ZERO:
            return None

        ema_fast = self._buf.ema(cfg.ema_fast)
        ema_slow = self._buf.ema(cfg.ema_slow)
        rsi = self._buf.rsi(cfg.rsi_period)
        atr = self._buf.atr(cfg.atr_period)
        adx = self._buf.adx(cfg.adx_period)

        has_position = abs(position_base) > Decimal("1e-8")

        # Manage existing position first
        if has_position and self._pos.side != "off":
            action = self._manage_position(mid, position_base, atr, now_s)
            if action:
                self._prev_ema_fast = ema_fast
                self._prev_ema_slow = ema_slow
                return action

        # Daily risk gate
        if self._daily_equity_open > _ZERO:
            daily_loss = (self._daily_equity_open - equity_quote) / self._daily_equity_open
            if daily_loss > cfg.max_daily_loss_pct:
                self._prev_ema_fast = ema_fast
                self._prev_ema_slow = ema_slow
                return {"side": "off", "reason": "daily_risk_limit"}

        if has_position:
            self._prev_ema_fast = ema_fast
            self._prev_ema_slow = ema_slow
            return {"side": self._pos.side, "holding": True}

        # Cooldown
        if self._last_exit_ts > 0 and (now_s - self._last_exit_ts) < cfg.cooldown_s:
            self._prev_ema_fast = ema_fast
            self._prev_ema_slow = ema_slow
            return {"side": "off", "cooldown": True}

        # Detect EMA crossover
        cross_up = (
            self._prev_ema_fast <= self._prev_ema_slow
            and ema_fast > ema_slow
            and self._prev_ema_fast > _ZERO
        )
        cross_down = (
            self._prev_ema_fast >= self._prev_ema_slow
            and ema_fast < ema_slow
            and self._prev_ema_fast > _ZERO
        )

        self._prev_ema_fast = ema_fast
        self._prev_ema_slow = ema_slow

        if not cross_up and not cross_down:
            return {"side": "off", "reason": "no_cross"}

        # ADX filter
        if adx < cfg.adx_min:
            return {"side": "off", "reason": "adx_too_low", "adx": float(adx)}

        # RSI filter: don't buy overbought, don't sell oversold
        if cross_up and rsi > cfg.rsi_overbought:
            return {"side": "off", "reason": "rsi_overbought", "rsi": float(rsi)}
        if cross_down and rsi < cfg.rsi_oversold:
            return {"side": "off", "reason": "rsi_oversold", "rsi": float(rsi)}

        if atr <= _ZERO:
            return {"side": "off", "reason": "zero_atr"}

        # Determine side
        side_str = "buy" if cross_up else "sell"
        order_side = OrderSide.BUY if cross_up else OrderSide.SELL

        # Size: risk_pct of equity
        quote_amount = equity_quote * cfg.risk_pct
        base_qty = quote_amount / mid
        quantity = self._instrument_spec.quantize_size(base_qty)

        if quantity <= _ZERO:
            return {"side": "off", "reason": "qty_zero"}

        # Submit entry order
        if cfg.entry_order_type == "limit":
            offset = atr * cfg.limit_entry_offset_atr
            if cross_up:
                entry_price = self._instrument_spec.quantize_price(mid - offset, "buy")
            else:
                entry_price = self._instrument_spec.quantize_price(mid + offset, "sell")
            order_type = PaperOrderType.LIMIT
        else:
            entry_price = mid
            order_type = PaperOrderType.MARKET

        self._desk.submit_order(
            instrument_id=self._instrument_id,
            side=order_side,
            order_type=order_type,
            price=entry_price,
            quantity=quantity,
            source_bot="momentum_scalper",
        )
        self._last_submitted_count = 1

        # Set up position tracking
        sl_dist = atr * cfg.sl_atr_mult
        tp_dist = atr * cfg.tp_atr_mult
        if cross_up:
            sl_price = mid - sl_dist
            tp_price = mid + tp_dist
        else:
            sl_price = mid + sl_dist
            tp_price = mid - tp_dist

        self._pos = _PositionState(
            side=side_str,
            entry_price=mid,
            entry_ts=now_s,
            sl_price=sl_price,
            tp_price=tp_price,
            risk_dist=sl_dist,
        )

        return {
            "side": side_str, "reason": "ema_cross",
            "ema_fast": float(ema_fast), "ema_slow": float(ema_slow),
            "rsi": float(rsi), "adx": float(adx), "atr": float(atr),
        }

    def record_fill_notional(self, notional: Decimal) -> None:
        pass

    def _manage_position(
        self,
        mid: Decimal,
        position_base: Decimal,
        atr: Decimal,
        now_s: float,
    ) -> dict | None:
        pos = self._pos
        cfg = self._cfg

        if pos.entry_price <= _ZERO:
            return None

        # Check stop-loss
        hit_sl = (
            (pos.side == "buy" and mid <= pos.sl_price)
            or (pos.side == "sell" and mid >= pos.sl_price)
        )
        if hit_sl:
            self._close_position(mid, position_base, now_s)
            return {"side": "exit", "reason": "stop_loss"}

        # Check take-profit
        hit_tp = (
            (pos.side == "buy" and mid >= pos.tp_price)
            or (pos.side == "sell" and mid <= pos.tp_price)
        )
        if hit_tp:
            self._close_position(mid, position_base, now_s)
            return {"side": "exit", "reason": "take_profit"}

        # Max hold
        hold_min = (now_s - pos.entry_ts) / 60
        if hold_min > cfg.max_hold_minutes:
            self._close_position(mid, position_base, now_s)
            return {"side": "exit", "reason": "max_hold"}

        # Trailing stop
        if pos.risk_dist > _ZERO:
            if pos.side == "buy":
                r_mult = (mid - pos.entry_price) / pos.risk_dist
            else:
                r_mult = (pos.entry_price - mid) / pos.risk_dist
        else:
            r_mult = _ZERO

        if not pos.trail_active and r_mult >= cfg.trail_activate_r:
            pos.trail_active = True
            if pos.side == "buy":
                pos.trail_hwm = mid
            else:
                pos.trail_lwm = mid

        if pos.trail_active:
            trail_dist = atr * cfg.trail_offset_atr
            if pos.side == "buy":
                if mid > pos.trail_hwm:
                    pos.trail_hwm = mid
                trail_stop = pos.trail_hwm - trail_dist
                if mid <= trail_stop:
                    self._close_position(mid, position_base, now_s)
                    return {"side": "exit", "reason": "trail_stop"}
            else:
                if mid < pos.trail_lwm:
                    pos.trail_lwm = mid
                trail_stop = pos.trail_lwm + trail_dist
                if mid >= trail_stop:
                    self._close_position(mid, position_base, now_s)
                    return {"side": "exit", "reason": "trail_stop"}

        return None

    def _close_position(self, mid: Decimal, position_base: Decimal, now_s: float) -> None:
        close_qty = abs(position_base)
        if close_qty <= _ZERO:
            self._pos = _PositionState()
            return

        self._cancel_all()
        close_side = OrderSide.SELL if position_base > _ZERO else OrderSide.BUY
        qty = self._instrument_spec.quantize_size(close_qty)
        if qty > _ZERO:
            self._desk.submit_order(
                instrument_id=self._instrument_id,
                side=close_side,
                order_type=PaperOrderType.MARKET,
                price=mid,
                quantity=qty,
                source_bot="momentum_scalper_exit",
            )
        self._last_exit_ts = now_s
        self._pos = _PositionState()

    def _cancel_all(self) -> None:
        try:
            self._desk.cancel_all(self._instrument_id)
        except Exception:
            pass  # Justification: best-effort teardown during simulation — desk may already be closed
