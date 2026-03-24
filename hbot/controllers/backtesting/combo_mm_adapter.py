"""Combo MM adapter — kitchen-sink with all features as toggleable flags.

Combines every proven and experimental edge source into one adapter:

  1. ATR-based dynamic spreads (proven v1 core)
  2. Inventory skew + urgency (proven)
  3. FVG spread bias (promising signal, PF 7.80)
  4. Candle micro-structure: body ratio, upper/lower wick ratios as
     directional pressure signals
  5. Fill-ratio feedback: track recent fill asymmetry and bias quoting
  6. Adaptive inventory limits: tighten during high vol, loosen in calm
  7. Level-distance sizing: deeper levels get progressively larger size
     (farther from mid = less adverse selection risk = safer to size up)
  8. Consecutive candle momentum: detect runs of same-direction candles
     and widen the contra-trend spread

All signals are incremental O(1) per tick.
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


@dataclass
class ComboMMConfig:
    # --- Core ATR (proven) ---
    atr_period: int = 14
    min_warmup_bars: int = 30
    spread_atr_mult: Decimal = Decimal("0.22")
    min_spread_pct: Decimal = Decimal("0.0008")
    max_spread_pct: Decimal = Decimal("0.0100")
    levels: int = 3
    level_spacing: Decimal = Decimal("0.5")
    base_size_pct: Decimal = Decimal("0.030")

    # --- Inventory management (proven) ---
    max_inventory_pct: Decimal = Decimal("0.15")
    inventory_skew_mult: Decimal = Decimal("3.0")
    inventory_size_penalty: Decimal = Decimal("0.5")
    inventory_age_decay_minutes: int = 45
    urgency_spread_reduction: Decimal = Decimal("0.4")

    # --- Risk limits ---
    max_daily_loss_pct: Decimal = Decimal("0.025")
    max_drawdown_pct: Decimal = Decimal("0.05")

    # --- Feature 1: FVG spread bias ---
    fvg_enabled: bool = False
    fvg_spread_bias: Decimal = Decimal("0.2")
    fvg_decay_bars: int = 8

    # --- Feature 2: Candle micro-structure ---
    micro_enabled: bool = False
    micro_body_threshold: Decimal = Decimal("0.6")
    micro_spread_bias: Decimal = Decimal("0.15")
    micro_lookback: int = 3

    # --- Feature 3: Fill-ratio feedback ---
    fill_feedback_enabled: bool = False
    fill_feedback_lookback: int = 20
    fill_feedback_spread_bias: Decimal = Decimal("0.2")

    # --- Feature 4: Adaptive inventory limits ---
    adaptive_inventory_enabled: bool = False
    adaptive_inv_vol_low_mult: Decimal = Decimal("1.5")
    adaptive_inv_vol_high_mult: Decimal = Decimal("0.6")

    # --- Feature 5: Level-distance sizing ---
    level_sizing_enabled: bool = False
    level_size_growth: Decimal = Decimal("0.3")

    # --- Feature 6: Consecutive candle momentum ---
    momentum_guard_enabled: bool = False
    momentum_lookback: int = 4
    momentum_spread_widen: Decimal = Decimal("0.3")


class _IncrementalATR:
    __slots__ = ("_alpha", "_atr", "_count", "_prev_close")

    def __init__(self, period: int = 14) -> None:
        self._alpha = _TWO / Decimal(period + 1)
        self._atr: Decimal = _ZERO
        self._prev_close: Decimal = _ZERO
        self._count: int = 0

    def add_bar(self, high: Decimal, low: Decimal, close: Decimal) -> None:
        if self._count == 0:
            self._atr = high - low
            self._prev_close = close
            self._count += 1
            return
        tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._atr = self._alpha * tr + (_ONE - self._alpha) * self._atr
        self._prev_close = close
        self._count += 1

    @property
    def value(self) -> Decimal:
        return self._atr

    @property
    def count(self) -> int:
        return self._count


class _FVGTracker:
    __slots__ = (
        "_count",
        "_decay_bars",
        "_fvg_age",
        "_fvg_dir",
        "_prev1_high",
        "_prev1_low",
        "_prev2_high",
        "_prev2_low",
    )

    def __init__(self, decay_bars: int = 8) -> None:
        self._decay_bars = decay_bars
        self._prev2_high = self._prev2_low = _ZERO
        self._prev1_high = self._prev1_low = _ZERO
        self._count = 0
        self._fvg_dir = 0
        self._fvg_age = 0

    def add_bar(self, high: Decimal, low: Decimal, open_: Decimal, close: Decimal) -> None:
        if self._count >= 2:
            bullish = close > open_ and self._prev2_high < low
            bearish = close < open_ and self._prev2_low > high
            if bullish:
                self._fvg_dir = 1
                self._fvg_age = 0
            elif bearish:
                self._fvg_dir = -1
                self._fvg_age = 0
            elif self._fvg_dir != 0:
                self._fvg_age += 1
                if self._fvg_age >= self._decay_bars:
                    self._fvg_dir = 0
        self._prev2_high = self._prev1_high
        self._prev2_low = self._prev1_low
        self._prev1_high = high
        self._prev1_low = low
        self._count += 1

    @property
    def direction(self) -> int:
        return self._fvg_dir

    @property
    def strength(self) -> Decimal:
        if self._fvg_dir == 0 or self._decay_bars <= 0:
            return _ZERO
        return max(_ZERO, _ONE - Decimal(str(self._fvg_age / self._decay_bars)))


class _MicroStructure:
    """Track candle body/wick ratios for directional pressure."""

    def __init__(self, lookback: int = 3) -> None:
        self._signals: deque[int] = deque(maxlen=lookback)

    def add_bar(self, open_: Decimal, high: Decimal, low: Decimal, close: Decimal) -> None:
        bar_range = high - low
        if bar_range <= _ZERO:
            self._signals.append(0)
            return
        body = abs(close - open_)
        body_ratio = body / bar_range
        upper_wick = high - max(open_, close)
        lower_wick = min(open_, close) - low

        if close > open_:
            if lower_wick > body:
                self._signals.append(1)
            elif upper_wick > body:
                self._signals.append(-1)
            else:
                self._signals.append(1 if body_ratio > Decimal("0.6") else 0)
        elif close < open_:
            if upper_wick > body:
                self._signals.append(-1)
            elif lower_wick > body:
                self._signals.append(1)
            else:
                self._signals.append(-1 if body_ratio > Decimal("0.6") else 0)
        else:
            self._signals.append(0)

    @property
    def pressure(self) -> int:
        if not self._signals:
            return 0
        total = sum(self._signals)
        if total >= 2:
            return 1
        if total <= -2:
            return -1
        return 0


class _FillTracker:
    """Track recent fill asymmetry."""

    def __init__(self, lookback: int = 20) -> None:
        self._fills: deque[int] = deque(maxlen=lookback)

    def record_fill(self, side: int) -> None:
        self._fills.append(side)

    @property
    def bias(self) -> Decimal:
        if len(self._fills) < 5:
            return _ZERO
        buys = sum(1 for f in self._fills if f == 1)
        sells = sum(1 for f in self._fills if f == -1)
        total = buys + sells
        if total == 0:
            return _ZERO
        return Decimal(str((buys - sells) / total))


class _MomentumTracker:
    """Track consecutive same-direction candles."""

    def __init__(self, lookback: int = 4) -> None:
        self._directions: deque[int] = deque(maxlen=lookback)

    def add_bar(self, open_: Decimal, close: Decimal) -> None:
        if close > open_:
            self._directions.append(1)
        elif close < open_:
            self._directions.append(-1)
        else:
            self._directions.append(0)

    @property
    def run_direction(self) -> int:
        if len(self._directions) < 3:
            return 0
        recent = list(self._directions)[-3:]
        if all(d == 1 for d in recent):
            return 1
        if all(d == -1 for d in recent):
            return -1
        return 0

    @property
    def run_length(self) -> int:
        if not self._directions:
            return 0
        d = self._directions[-1]
        if d == 0:
            return 0
        count = 0
        for v in reversed(self._directions):
            if v == d:
                count += 1
            else:
                break
        return count


class ComboMMAdapter:
    """Kitchen-sink MM — all features toggleable."""

    def __init__(
        self,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: ComboMMConfig | None = None,
    ) -> None:
        self._desk = desk
        self._instrument_id = instrument_id
        self._instrument_spec = instrument_spec
        self._cfg = config or ComboMMConfig()

        self._atr = _IncrementalATR(self._cfg.atr_period)
        self._fvg = _FVGTracker(self._cfg.fvg_decay_bars)
        self._micro = _MicroStructure(self._cfg.micro_lookback)
        self._fill_tracker = _FillTracker(self._cfg.fill_feedback_lookback)
        self._momentum = _MomentumTracker(self._cfg.momentum_lookback)

        self._atr_ring: deque[Decimal] = deque(maxlen=60)

        self._regime_name = "combo"
        self._last_submitted_count = 0
        self._tick_count = 0
        self._daily_equity_open = _ZERO
        self._daily_equity_peak = _ZERO
        self._current_day = -1
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
            self._atr.add_bar(c.high, c.low, c.close)
            self._fvg.add_bar(c.high, c.low, c.open, c.close)
            self._micro.add_bar(c.open, c.high, c.low, c.close)
            self._momentum.add_bar(c.open, c.close)
            if c.close > _ZERO:
                self._atr_ring.append(self._atr.value / c.close)
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
            self._fvg.add_bar(candle.high, candle.low, candle.open, candle.close)
            self._micro.add_bar(candle.open, candle.high, candle.low, candle.close)
            self._momentum.add_bar(candle.open, candle.close)
            self._last_candle_ts = candle.timestamp_ms
            if mid > _ZERO:
                self._atr_ring.append(self._atr.value / mid)

        day = int(now_s // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_equity_open = equity_quote
            self._daily_equity_peak = equity_quote
        self._daily_equity_peak = max(self._daily_equity_peak, equity_quote)

        if self._atr.count < cfg.min_warmup_bars or mid <= _ZERO or equity_quote <= _ZERO:
            return None

        if self._daily_equity_open > _ZERO:
            if (self._daily_equity_open - equity_quote) / self._daily_equity_open > cfg.max_daily_loss_pct:
                self._cancel_all()
                return {"side": "off", "reason": "daily_risk"}
        if self._daily_equity_peak > _ZERO:
            if (self._daily_equity_peak - equity_quote) / self._daily_equity_peak > cfg.max_drawdown_pct:
                self._cancel_all()
                return {"side": "off", "reason": "drawdown"}

        atr = self._atr.value
        if atr <= _ZERO:
            return None
        atr_pct = atr / mid

        base_spread = max(cfg.min_spread_pct, min(cfg.max_spread_pct, atr_pct * cfg.spread_atr_mult))

        # --- Inventory (proven core) ---
        inventory_pct = (position_base * mid) / equity_quote if equity_quote > _ZERO else _ZERO

        effective_max_inv = cfg.max_inventory_pct
        if cfg.adaptive_inventory_enabled and len(self._atr_ring) >= 10:
            sorted_atr = sorted(self._atr_ring)
            rank = sum(1 for v in sorted_atr if v <= atr_pct)
            vol_percentile = Decimal(str(rank / len(sorted_atr)))
            if vol_percentile < Decimal("0.3"):
                effective_max_inv = cfg.max_inventory_pct * cfg.adaptive_inv_vol_low_mult
            elif vol_percentile > Decimal("0.7"):
                effective_max_inv = cfg.max_inventory_pct * cfg.adaptive_inv_vol_high_mult

        has_position = abs(inventory_pct) > Decimal("0.001")
        if has_position:
            if self._position_entry_ts <= 0:
                self._position_entry_ts = now_s
        else:
            self._position_entry_ts = 0.0

        inv_ratio = min(_ONE, abs(inventory_pct) / effective_max_inv) if effective_max_inv > _ZERO else _ZERO
        skew = inventory_pct * cfg.inventory_skew_mult

        buy_spread = max(cfg.min_spread_pct, base_spread * (_ONE + max(_ZERO, skew)))
        sell_spread = max(cfg.min_spread_pct, base_spread * (_ONE + max(_ZERO, -skew)))

        age_minutes = (now_s - self._position_entry_ts) / 60 if self._position_entry_ts > 0 else 0
        urgency = _ZERO
        if age_minutes > 0 and cfg.inventory_age_decay_minutes > 0:
            urgency = min(_ONE, Decimal(str(age_minutes)) / Decimal(cfg.inventory_age_decay_minutes))
        if inventory_pct > Decimal("0.001"):
            sell_spread = max(cfg.min_spread_pct, sell_spread * (_ONE - urgency * cfg.urgency_spread_reduction))
        elif inventory_pct < Decimal("-0.001"):
            buy_spread = max(cfg.min_spread_pct, buy_spread * (_ONE - urgency * cfg.urgency_spread_reduction))

        # --- Feature 1: FVG bias ---
        if cfg.fvg_enabled and self._fvg.direction != 0:
            s = self._fvg.strength * cfg.fvg_spread_bias
            if self._fvg.direction == 1:
                buy_spread *= (_ONE - s)
                sell_spread *= (_ONE + s)
            else:
                buy_spread *= (_ONE + s)
                sell_spread *= (_ONE - s)
            buy_spread = max(cfg.min_spread_pct, buy_spread)
            sell_spread = max(cfg.min_spread_pct, sell_spread)

        # --- Feature 2: Micro-structure ---
        if cfg.micro_enabled:
            pressure = self._micro.pressure
            if pressure != 0:
                mb = cfg.micro_spread_bias
                if pressure == 1:
                    buy_spread *= (_ONE - mb)
                    sell_spread *= (_ONE + mb)
                else:
                    buy_spread *= (_ONE + mb)
                    sell_spread *= (_ONE - mb)
                buy_spread = max(cfg.min_spread_pct, buy_spread)
                sell_spread = max(cfg.min_spread_pct, sell_spread)

        # --- Feature 3: Fill feedback ---
        if cfg.fill_feedback_enabled:
            fb = self._fill_tracker.bias
            if abs(fb) > Decimal("0.2"):
                ffb = fb * cfg.fill_feedback_spread_bias
                buy_spread *= (_ONE + ffb)
                sell_spread *= (_ONE - ffb)
                buy_spread = max(cfg.min_spread_pct, buy_spread)
                sell_spread = max(cfg.min_spread_pct, sell_spread)

        # --- Feature 6: Momentum guard ---
        if cfg.momentum_guard_enabled:
            run_dir = self._momentum.run_direction
            run_len = self._momentum.run_length
            if run_dir != 0 and run_len >= 3:
                widen = cfg.momentum_spread_widen * Decimal(str(min(run_len, 6) / 3))
                if run_dir == 1:
                    sell_spread *= (_ONE + widen)
                else:
                    buy_spread *= (_ONE + widen)
                buy_spread = max(cfg.min_spread_pct, buy_spread)
                sell_spread = max(cfg.min_spread_pct, sell_spread)

        # --- Submit orders ---
        base_quote = equity_quote * cfg.base_size_pct
        size_penalty = _ONE - inv_ratio * cfg.inventory_size_penalty

        at_max_long = inventory_pct >= effective_max_inv
        at_max_short = inventory_pct <= -effective_max_inv

        self._cancel_all()
        submitted = 0

        for level in range(cfg.levels):
            level_mult = _ONE + cfg.level_spacing * Decimal(level)

            # Feature 5: Level-distance sizing
            level_size_mult = _ONE
            if cfg.level_sizing_enabled and level > 0:
                level_size_mult = _ONE + cfg.level_size_growth * Decimal(level)

            if not at_max_long:
                buy_size = base_quote * size_penalty * level_size_mult / mid
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
                        source_bot="combo_mm",
                    )
                    submitted += 1

            if not at_max_short:
                sell_size = base_quote * size_penalty * level_size_mult / mid
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
                        source_bot="combo_mm",
                    )
                    submitted += 1

        self._last_submitted_count = submitted
        features = []
        if cfg.fvg_enabled and self._fvg.direction != 0:
            features.append(f"fvg{'↑' if self._fvg.direction == 1 else '↓'}")
        if cfg.micro_enabled and self._micro.pressure != 0:
            features.append(f"mic{'↑' if self._micro.pressure == 1 else '↓'}")
        if cfg.momentum_guard_enabled and self._momentum.run_direction != 0:
            features.append(f"mom{self._momentum.run_length}")
        self._regime_name = "combo_" + ("_".join(features) if features else "base")

        return {
            "side": self._regime_name,
            "atr_pct": float(atr_pct),
            "buy_spread": float(buy_spread),
            "sell_spread": float(sell_spread),
            "inventory_pct": float(inventory_pct),
            "eff_max_inv": float(effective_max_inv),
        }

    def record_fill(self, side: int) -> None:
        self._fill_tracker.record_fill(side)

    def record_fill_notional(self, notional: Decimal) -> None:
        pass

    def _cancel_all(self) -> None:
        try:
            self._desk.cancel_all(self._instrument_id)
        except Exception:
            pass
