"""Self-contained backtest adapter — zero production-runtime imports.

Provides the same harness-facing interface as ``BacktestRuntimeAdapter``
(see ``BacktestTickAdapter`` protocol) but implements regime detection,
spread computation, price buffering, and risk checks entirely within
the backtesting package.

Dependencies are limited to:
  - Python stdlib
  - ``controllers.paper_engine_v2`` (simulation engine — expected)
  - ``controllers.backtesting.types`` (own package)
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# Regime spec (backtesting-native, no controllers.core import)
# ---------------------------------------------------------------------------

@dataclass
class SimpleRegimeSpec:
    """Lightweight regime spec used only within the standalone adapter."""

    spread_min: Decimal = Decimal("0.0020")
    spread_max: Decimal = Decimal("0.0040")
    levels_min: int = 2
    levels_max: int = 4
    quote_size_pct: Decimal = Decimal("0.03")
    target_base_pct: Decimal = Decimal("0.50")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SimpleAdapterConfig:
    """Configuration for SimpleBacktestAdapter.

    All values have safe defaults for a BTC-like perp MM backtest.
    """

    regime_specs: dict[str, SimpleRegimeSpec] = field(default_factory=lambda: {
        "neutral_low_vol": SimpleRegimeSpec(
            spread_min=Decimal("0.0020"), spread_max=Decimal("0.0040"),
            levels_min=2, levels_max=4,
            quote_size_pct=Decimal("0.03"), target_base_pct=Decimal("0.50"),
        ),
        "neutral_high_vol": SimpleRegimeSpec(
            spread_min=Decimal("0.0040"), spread_max=Decimal("0.0080"),
            levels_min=1, levels_max=3,
            quote_size_pct=Decimal("0.02"), target_base_pct=Decimal("0.50"),
        ),
        "high_vol_shock": SimpleRegimeSpec(
            spread_min=Decimal("0.0100"), spread_max=Decimal("0.0200"),
            levels_min=1, levels_max=2,
            quote_size_pct=Decimal("0.01"), target_base_pct=Decimal("0.50"),
        ),
    })
    high_vol_band_pct: Decimal = Decimal("0.0080")
    shock_drift_pct: Decimal = Decimal("0.0050")

    ema_period: int = 20
    atr_period: int = 14
    min_warmup_bars: int = 30

    spread_mult: Decimal = Decimal("1.0")
    size_mult: Decimal = Decimal("1.0")

    max_base_pct: Decimal = Decimal("1.50")
    max_daily_loss_pct: Decimal = Decimal("0.05")
    max_drawdown_pct: Decimal = Decimal("0.10")


# ---------------------------------------------------------------------------
# Lightweight price buffer (replaces controllers.price_buffer.PriceBuffer)
# ---------------------------------------------------------------------------

class _PriceBuffer:
    """Incremental O(1)-per-tick EMA / ATR tracker."""

    _TWO = Decimal("2")

    def __init__(self, max_bars: int = 2880) -> None:
        self._bar_count: int = 0
        self._ema_vals: dict[int, Decimal] = {}
        self._atr_vals: dict[int, Decimal] = {}
        self._prev_close: Decimal = _ZERO
        self._drift_ring: deque[Decimal] = deque(maxlen=30)

    def add_bar(self, high: Decimal, low: Decimal, close: Decimal) -> None:
        self._drift_ring.append(close)

        if self._bar_count == 0:
            for period in list(self._ema_vals.keys()):
                self._ema_vals[period] = close
            self._prev_close = close
            self._bar_count += 1
            return

        for period in list(self._ema_vals.keys()):
            alpha = self._TWO / Decimal(period + 1)
            self._ema_vals[period] = alpha * close + (_ONE - alpha) * self._ema_vals[period]

        tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        for period in list(self._atr_vals.keys()):
            alpha = self._TWO / Decimal(period + 1)
            self._atr_vals[period] = alpha * tr + (_ONE - alpha) * self._atr_vals[period]

        self._prev_close = close
        self._bar_count += 1

    def ready(self, min_bars: int) -> bool:
        return self._bar_count >= min_bars

    def ema(self, period: int) -> Decimal:
        if period not in self._ema_vals:
            self._ema_vals[period] = self._prev_close if self._bar_count > 0 else _ZERO
        return self._ema_vals[period]

    def atr(self, period: int) -> Decimal:
        if period not in self._atr_vals:
            self._atr_vals[period] = _ZERO
        return self._atr_vals[period]

    def band_pct(self, atr_period: int) -> Decimal:
        mid = self.ema(atr_period)
        if mid <= _ZERO:
            return _ZERO
        return self.atr(atr_period) / mid

    def drift_30s(self) -> Decimal:
        if len(self._drift_ring) < 2:
            return _ZERO
        ref = self._drift_ring[0]
        if ref <= _ZERO:
            return _ZERO
        return abs(self._drift_ring[-1] - ref) / ref


# ---------------------------------------------------------------------------
# SimpleBacktestAdapter
# ---------------------------------------------------------------------------

class SimpleBacktestAdapter:
    """Standalone adapter satisfying ``BacktestTickAdapter`` with no production imports.

    Implements simplified versions of regime detection, spread computation, and
    risk checks.  Good for validating the engine itself, running baseline tests,
    or operating in environments where the production runtime stack is unavailable.
    """

    def __init__(
        self,
        desk: PaperDesk,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        config: SimpleAdapterConfig | None = None,
    ) -> None:
        self._desk = desk
        self._instrument_id = instrument_id
        self._instrument_spec = instrument_spec
        self._config = config or SimpleAdapterConfig()

        self._buf = _PriceBuffer()
        self._buf.ema(self._config.ema_period)
        self._buf.ema(self._config.atr_period)
        self._buf.atr(self._config.atr_period)
        self._regime_name: str = "neutral_low_vol"

        self._daily_equity_open: Decimal = _ZERO
        self._daily_equity_peak: Decimal = _ZERO
        self._traded_notional_today: Decimal = _ZERO
        self._current_day: int = -1
        self._tick_count: int = 0
        self._last_submitted_count: int = 0
        self._last_candle_ts: int = 0

    # ------------------------------------------------------------------
    # BacktestTickAdapter protocol
    # ------------------------------------------------------------------

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
        cfg = self._config

        if candle is not None and candle.timestamp_ms != self._last_candle_ts:
            self._buf.add_bar(candle.high, candle.low, candle.close)
            self._last_candle_ts = candle.timestamp_ms
        else:
            self._buf.add_bar(mid, mid, mid)

        # Daily reset
        day = int(now_s // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_equity_open = equity_quote
            self._daily_equity_peak = equity_quote
            self._traded_notional_today = _ZERO
        self._daily_equity_peak = max(self._daily_equity_peak, equity_quote)

        if not self._buf.ready(cfg.min_warmup_bars):
            return None

        # --- Regime detection ---
        band = self._buf.band_pct(cfg.atr_period)
        drift = self._buf.drift_30s()

        if drift > cfg.shock_drift_pct:
            regime_name = "high_vol_shock"
        elif band > cfg.high_vol_band_pct:
            regime_name = "neutral_high_vol"
        else:
            regime_name = "neutral_low_vol"
        self._regime_name = regime_name

        spec = cfg.regime_specs.get(regime_name)
        if spec is None:
            spec = SimpleRegimeSpec()

        # --- Risk checks ---
        if equity_quote > _ZERO:
            base_pct = (position_base * mid) / equity_quote if mid > _ZERO else _ZERO
            daily_loss = (self._daily_equity_open - equity_quote) / self._daily_equity_open if self._daily_equity_open > _ZERO else _ZERO
            drawdown = (self._daily_equity_peak - equity_quote) / self._daily_equity_peak if self._daily_equity_peak > _ZERO else _ZERO

            if abs(base_pct) > cfg.max_base_pct or daily_loss > cfg.max_daily_loss_pct or drawdown > cfg.max_drawdown_pct:
                self._cancel_all()
                return None

        # --- Compute spreads (scaled by spread_mult) ---
        sm = cfg.spread_mult
        n_levels = max(1, (spec.levels_min + spec.levels_max) // 2)
        if n_levels == 1:
            spreads = [spec.spread_min * sm]
        else:
            step = (spec.spread_max - spec.spread_min) / Decimal(n_levels - 1)
            spreads = [(spec.spread_min + step * Decimal(i)) * sm for i in range(n_levels)]

        # --- Submit orders ---
        self._cancel_all()
        self._last_submitted_count = 0

        if mid <= _ZERO or equity_quote <= _ZERO:
            return None

        quote_per_level = equity_quote * spec.quote_size_pct * cfg.size_mult
        base_per_level = quote_per_level / mid
        quantity = self._instrument_spec.quantize_size(base_per_level)
        submitted = 0

        for spread_pct in spreads:
            buy_price = self._instrument_spec.quantize_price(
                mid * (_ONE - spread_pct), "buy",
            )
            if not self._instrument_spec.validate_order(buy_price, quantity):
                self._desk.submit_order(
                    instrument_id=self._instrument_id,
                    side=OrderSide.BUY,
                    order_type=PaperOrderType.LIMIT,
                    price=buy_price,
                    quantity=quantity,
                    source_bot="backtest",
                )
                submitted += 1

            sell_price = self._instrument_spec.quantize_price(
                mid * (_ONE + spread_pct), "sell",
            )
            if not self._instrument_spec.validate_order(sell_price, quantity):
                self._desk.submit_order(
                    instrument_id=self._instrument_id,
                    side=OrderSide.SELL,
                    order_type=PaperOrderType.LIMIT,
                    price=sell_price,
                    quantity=quantity,
                    source_bot="backtest",
                )
                submitted += 1

        self._last_submitted_count = submitted
        return {"spreads": spreads, "regime": regime_name}

    def record_fill_notional(self, notional: Decimal) -> None:
        self._traded_notional_today += notional

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _cancel_all(self) -> None:
        try:
            self._desk.cancel_all(self._instrument_id)
        except Exception:
            pass  # Justification: best-effort teardown during simulation — desk may already be closed
