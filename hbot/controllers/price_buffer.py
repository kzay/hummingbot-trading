"""Mid-price bar builder with running EMA and ATR indicators.

Builds 1-minute bars from mid-price samples and maintains running indicator
values updated incrementally on each new bar — O(1) per tick instead of
O(n) recomputation.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Deque, Dict, List, Optional, Tuple

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")


@dataclass
class MinuteBar:
    ts_minute: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class MidPriceBuffer:
    """Builds 1-minute bars from mid-price samples.

    Samples are expected every ~10s; missing minute gaps are forward-filled.
    EMA and ATR are updated incrementally when a new bar completes.
    """

    def __init__(self, sample_interval_sec: int = 10, max_minutes: int = 2880):
        self.sample_interval_sec = sample_interval_sec
        self.max_minutes = max_minutes
        self._bars: Deque[MinuteBar] = deque(maxlen=max_minutes)
        self._samples: Deque[Tuple[float, Decimal]] = deque(maxlen=720)

        self._ema_values: Dict[int, Decimal] = {}
        self._atr_values: Dict[int, Decimal] = {}
        self._prev_close: Optional[Decimal] = None
        self._bar_count: int = 0
        self._drift_ewma: Optional[Decimal] = None

    @property
    def bars(self) -> List[MinuteBar]:
        return list(self._bars)

    def add_sample(self, timestamp_s: float, mid_price: Decimal) -> None:
        if mid_price <= 0:
            return
        self._samples.append((timestamp_s, mid_price))
        minute_ts = int(timestamp_s // 60) * 60
        if len(self._bars) == 0:
            self._bars.append(
                MinuteBar(ts_minute=minute_ts, open=mid_price, high=mid_price, low=mid_price, close=mid_price)
            )
            self._bar_count = 1
            self._prev_close = mid_price
            return

        last = self._bars[-1]
        if minute_ts == last.ts_minute:
            last.high = max(last.high, mid_price)
            last.low = min(last.low, mid_price)
            last.close = mid_price
            return

        if minute_ts > last.ts_minute:
            completed_bar = last
            self._on_bar_complete(completed_bar)

            cursor = last.ts_minute + 60
            while cursor < minute_ts:
                gap_bar = MinuteBar(
                    ts_minute=cursor, open=last.close, high=last.close,
                    low=last.close, close=last.close,
                )
                self._bars.append(gap_bar)
                last = self._bars[-1]
                self._bar_count += 1
                self._on_bar_complete(gap_bar)
                cursor += 60
            self._bars.append(
                MinuteBar(ts_minute=minute_ts, open=mid_price, high=mid_price, low=mid_price, close=mid_price)
            )
            self._bar_count += 1

    def _on_bar_complete(self, bar: MinuteBar) -> None:
        """Update running indicators when a bar finalizes."""
        close = bar.close

        for period in list(self._ema_values.keys()):
            alpha = _TWO / Decimal(period + 1)
            self._ema_values[period] = alpha * close + (_ONE - alpha) * self._ema_values[period]

        if self._prev_close is not None:
            tr = max(
                bar.high - bar.low,
                abs(bar.high - self._prev_close),
                abs(bar.low - self._prev_close),
            )
            for period in list(self._atr_values.keys()):
                p = Decimal(period)
                self._atr_values[period] = (self._atr_values[period] * (p - _ONE) + tr) / p

        self._prev_close = close

    def ready(self, min_bars: int) -> bool:
        return len(self._bars) >= min_bars

    def latest_close(self) -> Optional[Decimal]:
        if not self._bars:
            return None
        return self._bars[-1].close

    def ema(self, period: int) -> Optional[Decimal]:
        """Return the running EMA for *period*. O(1) after warm-up."""
        if period <= 0 or len(self._bars) < period:
            return None
        if period in self._ema_values:
            return self._ema_values[period]
        closes = [bar.close for bar in self._bars]
        alpha = _TWO / Decimal(period + 1)
        one_minus_alpha = _ONE - alpha
        ema_value = closes[0]
        for close in closes[1:]:
            ema_value = alpha * close + one_minus_alpha * ema_value
        self._ema_values[period] = ema_value
        return ema_value

    def atr(self, period: int) -> Optional[Decimal]:
        """Return the running ATR for *period*. O(1) after warm-up."""
        if period <= 0 or len(self._bars) < period + 1:
            return None
        if period in self._atr_values:
            return self._atr_values[period]
        bars = list(self._bars)
        trs: List[Decimal] = []
        for i in range(1, len(bars)):
            prev_close = bars[i - 1].close
            high = bars[i].high
            low = bars[i].low
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        recent = trs[-period:]
        atr_val = sum(recent, _ZERO) / Decimal(len(recent))
        self._atr_values[period] = atr_val
        return atr_val

    def band_pct(self, atr_period: int = 14) -> Optional[Decimal]:
        price = self.latest_close()
        atr_val = self.atr(atr_period)
        if price is None or atr_val is None or price <= 0:
            return None
        return atr_val / price

    def adverse_drift_30s(self, now_ts: float) -> Decimal:
        """Raw 30-second adverse drift (absolute price change / older price).

        Used for regime detection and diagnostics. Use :meth:`adverse_drift_smooth`
        for cost-model inputs to avoid edge-gate flapping from single-tick spikes.
        """
        if len(self._samples) < 2:
            return _ZERO
        now_mid = self._samples[-1][1]
        older: Optional[Decimal] = None
        threshold = now_ts - 30.0
        for sample_ts, sample_mid in reversed(self._samples):
            if sample_ts <= threshold:
                older = sample_mid
                break
        if older is None or older <= 0:
            return _ZERO
        return abs(now_mid - older) / older

    def adverse_drift_smooth(self, now_ts: float, alpha: Decimal) -> Decimal:
        """EWMA-smoothed adverse drift for stable cost modeling.

        Applies exponential smoothing to the raw 30s drift so that transient
        microstructure spikes do not immediately suppress net edge and trigger
        edge-gate pauses. ``alpha`` controls responsiveness (0.05=slow, 0.5=fast).
        """
        raw = self.adverse_drift_30s(now_ts)
        if self._drift_ewma is None:
            self._drift_ewma = raw
        else:
            self._drift_ewma = alpha * raw + (_ONE - alpha) * self._drift_ewma
        return self._drift_ewma

    @staticmethod
    def minute_iso(minute_ts: int) -> str:
        return datetime.fromtimestamp(minute_ts, tz=timezone.utc).isoformat()
