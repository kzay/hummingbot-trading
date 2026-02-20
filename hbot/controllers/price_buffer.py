from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Deque, List, Optional, Tuple


@dataclass
class MinuteBar:
    ts_minute: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class MidPriceBuffer:
    """
    Builds 1-minute bars from mid-price samples.
    Samples are expected every ~10s; missing minute gaps are forward-filled.
    """

    def __init__(self, sample_interval_sec: int = 10, max_minutes: int = 2880):
        self.sample_interval_sec = sample_interval_sec
        self.max_minutes = max_minutes
        self._bars: Deque[MinuteBar] = deque(maxlen=max_minutes)
        self._samples: Deque[Tuple[float, Decimal]] = deque(maxlen=720)

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
            return

        last = self._bars[-1]
        if minute_ts == last.ts_minute:
            last.high = max(last.high, mid_price)
            last.low = min(last.low, mid_price)
            last.close = mid_price
            return

        if minute_ts > last.ts_minute:
            cursor = last.ts_minute + 60
            while cursor < minute_ts:
                # Gap forward-fill
                self._bars.append(
                    MinuteBar(ts_minute=cursor, open=last.close, high=last.close, low=last.close, close=last.close)
                )
                last = self._bars[-1]
                cursor += 60
            self._bars.append(
                MinuteBar(ts_minute=minute_ts, open=mid_price, high=mid_price, low=mid_price, close=mid_price)
            )

    def ready(self, min_bars: int) -> bool:
        return len(self._bars) >= min_bars

    def latest_close(self) -> Optional[Decimal]:
        if not self._bars:
            return None
        return self._bars[-1].close

    def ema(self, period: int) -> Optional[Decimal]:
        if period <= 0 or len(self._bars) < period:
            return None
        closes = [bar.close for bar in self._bars]
        alpha = Decimal("2") / Decimal(period + 1)
        ema_value = closes[0]
        for close in closes[1:]:
            ema_value = alpha * close + (Decimal("1") - alpha) * ema_value
        return ema_value

    def atr(self, period: int) -> Optional[Decimal]:
        if period <= 0 or len(self._bars) < period + 1:
            return None
        bars = list(self._bars)
        trs: List[Decimal] = []
        for i in range(1, len(bars)):
            prev_close = bars[i - 1].close
            high = bars[i].high
            low = bars[i].low
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        recent = trs[-period:]
        return sum(recent, Decimal("0")) / Decimal(len(recent))

    def band_pct(self, atr_period: int = 14) -> Optional[Decimal]:
        price = self.latest_close()
        atr_val = self.atr(atr_period)
        if price is None or atr_val is None or price <= 0:
            return None
        return atr_val / price

    def adverse_drift_30s(self, now_ts: float) -> Decimal:
        if len(self._samples) < 2:
            return Decimal("0")
        now_mid = self._samples[-1][1]
        older: Optional[Decimal] = None
        threshold = now_ts - 30.0
        for sample_ts, sample_mid in reversed(self._samples):
            if sample_ts <= threshold:
                older = sample_mid
                break
        if older is None or older <= 0:
            return Decimal("0")
        return abs(now_mid - older) / older

    @staticmethod
    def minute_iso(minute_ts: int) -> str:
        return datetime.fromtimestamp(minute_ts, tz=timezone.utc).isoformat()
