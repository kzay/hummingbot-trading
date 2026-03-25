"""SMC-enhanced ATR MM adapter.

Extends the proven ATR MM v1 with two tactical filters inspired by:
  - Smart Money Concepts (ICT): Fair Value Gap detection biases spreads
    toward the imbalance side — we narrow spreads where FVG predicts
    reversion and widen where FVG predicts continuation.
  - Bollinger Bands regime: BB bandwidth detects contraction (favorable
    for MM) vs band-walk (trending, adverse for MM). During band-walk
    we reduce size; during contraction we increase it.

All filters are incremental O(1) per tick — no pandas dependency.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from controllers.backtesting.types import CandleRow
from controllers.common.ict._atr import IncrementalATR as _IncrementalATR
from controllers.common.ict.state import ICTConfig, ICTState
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
class SmcMMConfig:
    atr_period: int = 14
    min_warmup_bars: int = 30

    spread_atr_mult: Decimal = Decimal("0.22")
    min_spread_pct: Decimal = Decimal("0.0008")
    max_spread_pct: Decimal = Decimal("0.0100")

    levels: int = 3
    level_spacing: Decimal = Decimal("0.5")

    base_size_pct: Decimal = Decimal("0.030")

    max_inventory_pct: Decimal = Decimal("0.15")
    inventory_skew_mult: Decimal = Decimal("3.0")
    inventory_size_penalty: Decimal = Decimal("0.5")

    inventory_age_decay_minutes: int = 45
    urgency_spread_reduction: Decimal = Decimal("0.4")

    max_daily_loss_pct: Decimal = Decimal("0.025")
    max_drawdown_pct: Decimal = Decimal("0.05")

    # --- FVG parameters ---
    fvg_enabled: bool = True
    fvg_spread_bias: Decimal = Decimal("0.3")
    fvg_decay_bars: int = 10

    # --- Bollinger regime parameters ---
    bb_enabled: bool = True
    bb_period: int = 20
    bb_band_walk_threshold: Decimal = Decimal("0.8")
    bb_contraction_percentile: Decimal = Decimal("0.3")
    bb_walk_size_mult: Decimal = Decimal("0.5")
    bb_contract_size_mult: Decimal = Decimal("1.3")
    bb_width_lookback: int = 60

    # --- ICT shadow mode ---
    ict_shadow_enabled: bool = False


class _FVGTracker:
    """Detects Fair Value Gaps on 1m candles incrementally.

    A bullish FVG occurs when candle[i-2].high < candle[i].low (gap up).
    A bearish FVG occurs when candle[i-2].low > candle[i].high (gap down).

    Tracks the most recent FVG with a decay timer so it only influences
    quoting for a limited number of bars after detection.
    """

    def __init__(self, decay_bars: int = 10) -> None:
        self._decay_bars = decay_bars
        self._prev2_high: Decimal = _ZERO
        self._prev2_low: Decimal = _ZERO
        self._prev1_high: Decimal = _ZERO
        self._prev1_low: Decimal = _ZERO
        self._prev1_open: Decimal = _ZERO
        self._prev1_close: Decimal = _ZERO
        self._count: int = 0

        self._fvg_direction: int = 0  # +1 bullish, -1 bearish, 0 none
        self._fvg_age: int = 0

    def add_bar(self, high: Decimal, low: Decimal, open_: Decimal, close: Decimal) -> None:
        if self._count >= 2:
            is_bullish_candle = close > open_
            is_bearish_candle = close < open_

            if self._prev2_high < low and is_bullish_candle:
                self._fvg_direction = 1
                self._fvg_age = 0
            elif self._prev2_low > high and is_bearish_candle:
                self._fvg_direction = -1
                self._fvg_age = 0
            else:
                if self._fvg_direction != 0:
                    self._fvg_age += 1
                    if self._fvg_age >= self._decay_bars:
                        self._fvg_direction = 0
                        self._fvg_age = 0

        self._prev2_high = self._prev1_high
        self._prev2_low = self._prev1_low
        self._prev1_high = high
        self._prev1_low = low
        self._prev1_open = open_
        self._prev1_close = close
        self._count += 1

    @property
    def direction(self) -> int:
        return self._fvg_direction

    @property
    def strength(self) -> Decimal:
        if self._fvg_direction == 0 or self._decay_bars <= 0:
            return _ZERO
        return max(_ZERO, _ONE - Decimal(str(self._fvg_age / self._decay_bars)))


class _BBRegime:
    """Incremental Bollinger Bands regime detector.

    Tracks:
      - Band-walk: price consistently near upper/lower band (trending)
      - Bandwidth percentile: contraction vs expansion
    """

    def __init__(self, period: int = 20, width_lookback: int = 60) -> None:
        self._period = period
        self._prices: deque[Decimal] = deque(maxlen=period)
        self._widths: deque[Decimal] = deque(maxlen=width_lookback)
        self._band_walk_count: int = 0
        self._band_walk_lookback: int = 5
        self._band_touches: deque[int] = deque(maxlen=5)

    def add_bar(self, close: Decimal, high: Decimal, low: Decimal) -> None:
        self._prices.append(close)

        if len(self._prices) < self._period:
            return

        mean = sum(self._prices) / Decimal(len(self._prices))
        variance = sum((p - mean) ** 2 for p in self._prices) / Decimal(len(self._prices))
        std = variance.sqrt() if variance > _ZERO else _ZERO

        upper = mean + _TWO * std
        lower = mean - _TWO * std
        width = (upper - lower) / mean if mean > _ZERO else _ZERO
        self._widths.append(width)

        if high >= upper or low <= lower:
            self._band_touches.append(1)
        else:
            self._band_touches.append(0)

    @property
    def is_band_walking(self) -> bool:
        if len(self._band_touches) < 3:
            return False
        return sum(self._band_touches) >= 3

    @property
    def width_percentile(self) -> Decimal:
        if len(self._widths) < 10:
            return Decimal("0.5")
        sorted_w = sorted(self._widths)
        current = self._widths[-1]
        rank = sum(1 for w in sorted_w if w <= current)
        return Decimal(str(rank / len(sorted_w)))

    @property
    def ready(self) -> bool:
        return len(self._prices) >= self._period


class SmcMMAdapter:
    """SMC-enhanced ATR MM — FVG spread bias + BB regime sizing."""

    def __init__(
        self,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: SmcMMConfig | None = None,
    ) -> None:
        self._desk = desk
        self._instrument_id = instrument_id
        self._instrument_spec = instrument_spec
        self._cfg = config or SmcMMConfig()

        self._atr = _IncrementalATR(self._cfg.atr_period)
        self._fvg = _FVGTracker(decay_bars=self._cfg.fvg_decay_bars)
        self._bb = _BBRegime(period=self._cfg.bb_period, width_lookback=self._cfg.bb_width_lookback)

        self._ict: ICTState | None = None
        if self._cfg.ict_shadow_enabled:
            self._ict = ICTState(ICTConfig(atr_period=self._cfg.atr_period))

        self._regime_name: str = "smc_adaptive"
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
            self._atr.add_bar(c.high, c.low, c.close)
            self._fvg.add_bar(c.high, c.low, c.open, c.close)
            self._bb.add_bar(c.close, c.high, c.low)
            if self._ict is not None:
                self._ict.add_bar(c.open, c.high, c.low, c.close, c.volume)
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
            self._bb.add_bar(candle.close, candle.high, candle.low)
            if self._ict is not None:
                self._ict.add_bar(candle.open, candle.high, candle.low, candle.close, candle.volume)
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

        # --- Inventory management (same as v1) ---
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

        # --- FVG spread bias ---
        fvg_bias_buy = _ONE
        fvg_bias_sell = _ONE
        if cfg.fvg_enabled and self._fvg.direction != 0:
            strength = self._fvg.strength * cfg.fvg_spread_bias
            if self._fvg.direction == 1:
                # Bullish FVG: price likely to rise — narrow buy spread (catch reversion),
                # widen sell spread (protect against continuation)
                fvg_bias_buy = _ONE - strength
                fvg_bias_sell = _ONE + strength
            else:
                fvg_bias_buy = _ONE + strength
                fvg_bias_sell = _ONE - strength

        buy_spread *= fvg_bias_buy
        sell_spread *= fvg_bias_sell
        buy_spread = max(cfg.min_spread_pct, buy_spread)
        sell_spread = max(cfg.min_spread_pct, sell_spread)

        # --- BB regime sizing ---
        bb_size_mult = _ONE
        regime_suffix = "neutral"
        if cfg.bb_enabled and self._bb.ready:
            if self._bb.is_band_walking:
                bb_size_mult = cfg.bb_walk_size_mult
                regime_suffix = "walk"
            elif self._bb.width_percentile < cfg.bb_contraction_percentile:
                bb_size_mult = cfg.bb_contract_size_mult
                regime_suffix = "squeeze"
            else:
                regime_suffix = "normal"

        base_quote = equity_quote * cfg.base_size_pct * bb_size_mult
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
                        source_bot="smc_mm",
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
                        source_bot="smc_mm",
                    )
                    submitted += 1

        fvg_label = ("fvg_bull" if self._fvg.direction == 1 else "fvg_bear") if self._fvg.direction != 0 else "no_fvg"
        self._regime_name = f"smc_{regime_suffix}_{fvg_label}"
        self._last_submitted_count = submitted

        result = {
            "side": self._regime_name,
            "atr_pct": float(atr_pct),
            "base_spread": float(base_spread),
            "buy_spread": float(buy_spread),
            "sell_spread": float(sell_spread),
            "inventory_pct": float(inventory_pct),
            "urgency": float(urgency),
            "fvg_dir": self._fvg.direction,
            "fvg_strength": float(self._fvg.strength),
            "bb_walk": self._bb.is_band_walking,
            "bb_width_pct": float(self._bb.width_percentile),
            "bb_size_mult": float(bb_size_mult),
        }

        if self._ict is not None:
            result["ict_trend"] = self._ict.trend
            result["ict_active_fvgs"] = len(self._ict.active_fvgs)
            result["ict_active_obs"] = len(self._ict.active_obs)
            result["ict_active_breakers"] = len(self._ict.all_breakers)
            result["ict_pd_zone"] = self._ict.zone_for_price(mid)

        return result

    def record_fill_notional(self, notional: Decimal) -> None:
        pass

    def _cancel_all(self) -> None:
        try:
            self._desk.cancel_all(self._instrument_id)
        except Exception:
            pass  # Justification: best-effort teardown during simulation — desk may already be closed
