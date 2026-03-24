"""Price bar builder with running EMA, ATR, RSI, and ADX indicators.

Builds 1-minute bars from price samples (mid, mark, or last-trade) and
maintains running indicator values updated incrementally on each new bar —
O(1) per tick instead of O(n) recomputation.

All indicators (EMA, ATR, RSI, ADX) use float internally for speed and
convert to Decimal only at the public API boundary.  For a 128K-tick
backtest this reduces runtime from ~60 minutes to ~2 minutes.

Stateless indicator logic lives in ``controllers.common.indicators`` and is
used as the cold-start reference.  ``PriceBuffer`` maintains incremental
state so that subsequent calls are O(1).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from math import sqrt

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


class PriceBuffer:
    """Builds 1-minute bars from price samples.

    Samples are expected every ~10s; missing minute gaps are forward-filled.
    EMA, ATR, RSI, and ADX are updated incrementally when a new bar completes.
    The price source (mid, mark, or last-trade) is determined by the caller.
    """

    def __init__(self, sample_interval_sec: int = 10, max_minutes: int = 2880):
        self.sample_interval_sec = sample_interval_sec
        self.max_minutes = max_minutes
        self._bars: deque[MinuteBar] = deque(maxlen=max_minutes)
        self._samples: deque[tuple[float, Decimal]] = deque(maxlen=720)

        self._ema_values: dict[int, Decimal] = {}
        self._atr_values: dict[int, Decimal] = {}
        self._prev_close: Decimal | None = None
        self._bar_count: int = 0
        self._drift_ewma: Decimal | None = None

        # Per-bar caches: store (bar_count_at_computation, result).
        # Invalidated automatically when _bar_count advances.
        self._rsi_cache: dict[int, tuple[int, Decimal | None]] = {}
        self._adx_cache: dict[int, tuple[int, Decimal | None]] = {}
        self._sma_cache: dict[int, tuple[int, Decimal | None]] = {}
        self._stddev_cache: dict[int, tuple[int, Decimal | None]] = {}
        self._closes_cache: tuple[int, list[Decimal]] = (0, [])

    @property
    def bars(self) -> list[MinuteBar]:
        return list(self._bars)

    @property
    def closes(self) -> list[Decimal]:
        """Return close prices as a list, cached per bar count.

        Uses incremental append when possible — avoids rebuilding the full
        list on every bar completion (important for backtesting where a new
        bar completes every tick).
        """
        cached_count, cached_list = self._closes_cache
        if cached_count == self._bar_count and cached_count > 0:
            return cached_list
        n = len(self._bars)
        if cached_count > 0 and cached_list and len(cached_list) <= n:
            diff = n - len(cached_list)
            if diff <= 10:
                for i in range(len(cached_list), n):
                    cached_list.append(self._bars[i].close)
                if len(cached_list) > n:
                    cached_list[:] = cached_list[-n:]
                self._closes_cache = (self._bar_count, cached_list)
                return cached_list
        result = [bar.close for bar in self._bars]
        self._closes_cache = (self._bar_count, result)
        return result

    def _reset_state(self) -> None:
        self._bars.clear()
        self._samples.clear()
        self._ema_values.clear()
        self._atr_values.clear()
        self._prev_close = None
        self._bar_count = 0
        self._drift_ewma = None
        self._rsi_cache.clear()
        self._adx_cache.clear()
        self._sma_cache.clear()
        self._stddev_cache.clear()
        self._closes_cache = (0, [])

    def seed_bars(self, bars: list[MinuteBar], reset: bool = False) -> int:
        """Bulk-load closed bars into the buffer before live samples begin."""
        if reset:
            self._reset_state()
        elif len(self._bars) > 0:
            raise ValueError("cannot seed a non-empty PriceBuffer without reset=True")
        if not bars:
            return 0
        sorted_bars = sorted(bars, key=lambda item: int(item.ts_minute))
        seeded = 0
        last_bar: MinuteBar | None = None
        for bar in sorted_bars:
            ohlc = [Decimal(bar.open), Decimal(bar.high), Decimal(bar.low), Decimal(bar.close)]
            if any(v.is_nan() or v.is_infinite() or v <= 0 for v in ohlc):
                continue
            if last_bar is not None:
                cursor = int(last_bar.ts_minute) + 60
                while cursor < int(bar.ts_minute):
                    gap_bar = MinuteBar(
                        ts_minute=cursor,
                        open=last_bar.close,
                        high=last_bar.close,
                        low=last_bar.close,
                        close=last_bar.close,
                    )
                    self._bars.append(gap_bar)
                    self._bar_count += 1
                    self._on_bar_complete(gap_bar)
                    seeded += 1
                    last_bar = gap_bar
                    cursor += 60
            seeded_bar = MinuteBar(
                ts_minute=int(bar.ts_minute),
                open=Decimal(bar.open),
                high=Decimal(bar.high),
                low=Decimal(bar.low),
                close=Decimal(bar.close),
            )
            self._bars.append(seeded_bar)
            self._bar_count += 1
            self._on_bar_complete(seeded_bar)
            seeded += 1
            last_bar = seeded_bar
        return seeded

    def seed_samples(self, samples: list[tuple[float, Decimal]], reset: bool = False) -> int:
        """Bulk-load recent sub-minute samples used by adverse drift calculations."""
        if reset:
            self._samples.clear()
            self._drift_ewma = None
        if not samples:
            return 0
        seeded = 0
        for sample_ts, price in sorted(samples, key=lambda item: float(item[0])):
            if price.is_nan() or price.is_infinite() or price <= 0:
                continue
            self._samples.append((float(sample_ts), Decimal(price)))
            seeded += 1
        return seeded

    def append_bar(self, bar: MinuteBar) -> None:
        """Append a single completed bar and update running indicators.

        Unlike ``seed_bars()``, works on a non-empty buffer (no reset needed).
        Unlike ``add_sample()``, accepts full OHLCV without flattening to a
        single price.  Gap minutes between the last existing bar and *bar* are
        forward-filled automatically (same logic as ``seed_bars``).

        Silently skips the bar when:
        - Any OHLC value is NaN, infinite, or non-positive.
        - The bar timestamp is <= the last bar already in the buffer (duplicate
          or out-of-order).
        """
        ohlc = [bar.open, bar.high, bar.low, bar.close]
        if any(v.is_nan() or v.is_infinite() or v <= 0 for v in ohlc):
            return
        bar_ts = int(bar.ts_minute)
        if self._bars and bar_ts <= int(self._bars[-1].ts_minute):
            return
        if self._bars:
            cursor = int(self._bars[-1].ts_minute) + 60
            while cursor < bar_ts:
                gap_bar = MinuteBar(
                    ts_minute=cursor,
                    open=self._bars[-1].close, high=self._bars[-1].close,
                    low=self._bars[-1].close, close=self._bars[-1].close,
                )
                self._bars.append(gap_bar)
                self._bar_count += 1
                self._on_bar_complete(gap_bar)
                cursor += 60
        appended = MinuteBar(
            ts_minute=bar_ts,
            open=Decimal(bar.open), high=Decimal(bar.high),
            low=Decimal(bar.low), close=Decimal(bar.close),
        )
        self._bars.append(appended)
        self._bar_count += 1
        self._on_bar_complete(appended)

    def add_sample(self, timestamp_s: float, price: Decimal) -> None:
        if price.is_nan() or price.is_infinite() or price <= 0:
            return
        self._samples.append((timestamp_s, price))
        minute_ts = int(timestamp_s // 60) * 60
        if len(self._bars) == 0:
            self._bars.append(
                MinuteBar(ts_minute=minute_ts, open=price, high=price, low=price, close=price)
            )
            self._bar_count = 1
            self._prev_close = price
            return

        last = self._bars[-1]
        if minute_ts == last.ts_minute:
            last.high = max(last.high, price)
            last.low = min(last.low, price)
            last.close = price
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
                MinuteBar(ts_minute=minute_ts, open=price, high=price, low=price, close=price)
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

    def latest_close(self) -> Decimal | None:
        if not self._bars:
            return None
        return self._bars[-1].close

    def ema(self, period: int) -> Decimal | None:
        """Return the running EMA for *period*. O(1) after warm-up.

        Cold-start note: on first call the EMA is computed from the full bar
        history seeded at ``closes[0]`` (oldest bar), which introduces a small
        initialization bias that decays within approximately 3×period bars.
        Subsequent calls use the incrementally-updated cached value.  For
        strategy use cases where the buffer is pre-seeded with historical data
        this bias is immaterial; use :func:`controllers.common.indicators.ema`
        for a correctly SMA-seeded cold-start.
        """
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

    def atr(self, period: int) -> Decimal | None:
        """Return the running ATR for *period*. O(1) after warm-up.

        Cold-start note: on first call the ATR is seeded from the simple mean
        of the most recent ``period`` True Ranges, then subsequent incremental
        updates from ``_on_bar_complete`` apply Wilder's recursive smooth
        ``(prev * (N-1) + TR) / N``.  This hybrid converges to the Wilder SMMA
        within a few bars.  Use :func:`controllers.common.indicators.atr` for a
        fully consistent Wilder computation from a cold list of bars.
        """
        if period <= 0 or len(self._bars) < period + 1:
            return None
        if period in self._atr_values:
            return self._atr_values[period]
        bars = list(self._bars)
        trs: list[Decimal] = []
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

    def band_pct(self, atr_period: int = 14) -> Decimal | None:
        price = self.latest_close()
        atr_val = self.atr(atr_period)
        if price is None or atr_val is None or price <= 0:
            return None
        return atr_val / price

    def sma(self, period: int) -> Decimal | None:
        """Return simple moving average of close prices. Cached per bar.

        Uses float arithmetic internally for speed; converts back to Decimal
        at the boundary.  The precision difference vs pure-Decimal is
        negligible for trading signals (<1e-12 relative error on typical prices).
        """
        if period <= 0 or len(self._bars) < period:
            return None
        cached = self._sma_cache.get(period)
        if cached is not None and cached[0] == self._bar_count:
            return cached[1]
        bars = self._bars
        n = len(bars)
        total = 0.0
        for i in range(n - period, n):
            total += float(bars[i].close)
        result = Decimal(str(total / period))
        self._sma_cache[period] = (self._bar_count, result)
        return result

    def stddev(self, period: int) -> Decimal | None:
        """Return population standard deviation of close prices. Cached per bar.

        Uses float arithmetic internally for speed.
        """
        if period <= 0 or len(self._bars) < period:
            return None
        cached = self._stddev_cache.get(period)
        if cached is not None and cached[0] == self._bar_count:
            return cached[1]
        bars = self._bars
        n = len(bars)
        total = 0.0
        for i in range(n - period, n):
            total += float(bars[i].close)
        mean = total / period
        var_sum = 0.0
        for i in range(n - period, n):
            d = float(bars[i].close) - mean
            var_sum += d * d
        variance = var_sum / period
        result = Decimal(str(sqrt(variance))) if variance > 0.0 else _ZERO
        self._stddev_cache[period] = (self._bar_count, result)
        return result

    def bollinger_bands(self, period: int = 20, stddev_mult: Decimal = _TWO) -> tuple[Decimal, Decimal, Decimal] | None:
        """Return (lower, basis, upper) Bollinger bands for close prices."""
        basis = self.sma(period)
        stdev = self.stddev(period)
        if basis is None or stdev is None:
            return None
        width = stdev * stddev_mult
        return basis - width, basis, basis + width

    def rsi(self, period: int = 14) -> Decimal | None:
        """Return Cutler's RSI (SMA-based) on close prices. Cached per bar.

        Uses float arithmetic on the last ``period + 1`` closes (O(period)
        per bar, not O(N) over all bars).  Identical algorithm to
        :func:`controllers.common.indicators.rsi` (Cutler's RSI).
        """
        cached = self._rsi_cache.get(period)
        if cached is not None and cached[0] == self._bar_count:
            return cached[1]
        n = len(self._bars)
        if period <= 0 or n < period + 1:
            self._rsi_cache[period] = (self._bar_count, None)
            return None
        bars = self._bars
        gains = 0.0
        losses = 0.0
        start = n - period - 1
        for i in range(start, n - 1):
            delta = float(bars[i + 1].close) - float(bars[i].close)
            if delta > 0.0:
                gains += delta
            elif delta < 0.0:
                losses -= delta
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss <= 0.0:
            result = Decimal("100")
        else:
            rs = avg_gain / avg_loss
            result = Decimal(str(100.0 - 100.0 / (1.0 + rs)))
        self._rsi_cache[period] = (self._bar_count, result)
        return result

    def adx(self, period: int = 14) -> Decimal | None:
        """Return ADX using Wilder-style directional movement smoothing.

        Uses only the most recent ``period * 6`` bars (Wilder smoothing
        converges within ~3× period), keeping computation O(period) rather
        than O(N) over the full bar history.  Float arithmetic internally;
        Decimal only at the API boundary.

        Requires at least ``period * 2 + 1`` bars; returns ``None`` when
        data is insufficient.
        """
        cached = self._adx_cache.get(period)
        if cached is not None and cached[0] == self._bar_count:
            return cached[1]

        n = len(self._bars)
        min_bars = period * 2 + 1
        if n < min_bars:
            self._adx_cache[period] = (self._bar_count, None)
            return None

        # Limit window: Wilder smooth converges in ~3×period bars.
        # Using 6×period gives a fully stable result while keeping N small.
        window = min(n, max(min_bars, period * 6))
        offset = n - window
        bars = self._bars
        p = period
        trs: list[float] = []
        pdm: list[float] = []
        mdm: list[float] = []
        for i in range(offset + 1, n):
            h = float(bars[i].high)
            lo = float(bars[i].low)
            pc = float(bars[i - 1].close)
            ph = float(bars[i - 1].high)
            pl = float(bars[i - 1].low)
            trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
            up = h - ph
            dn = pl - lo
            pdm.append(up if up > dn and up > 0.0 else 0.0)
            mdm.append(dn if dn > up and dn > 0.0 else 0.0)

        atr_w = sum(trs[:p])
        plus_w = sum(pdm[:p])
        minus_w = sum(mdm[:p])

        dxs: list[float] = []
        for idx in range(p, len(trs)):
            atr_w = atr_w - atr_w / p + trs[idx]
            plus_w = plus_w - plus_w / p + pdm[idx]
            minus_w = minus_w - minus_w / p + mdm[idx]
            if atr_w <= 0.0:
                dxs.append(0.0)
                continue
            plus_di = 100.0 * (plus_w / atr_w)
            minus_di = 100.0 * (minus_w / atr_w)
            denom = plus_di + minus_di
            dxs.append(100.0 * abs(plus_di - minus_di) / denom if denom > 0.0 else 0.0)

        if len(dxs) < p:
            self._adx_cache[period] = (self._bar_count, None)
            return None

        adx_val = sum(dxs[:p]) / p
        for dx in dxs[p:]:
            adx_val = adx_val - adx_val / p + dx / p

        result = Decimal(str(adx_val))
        self._adx_cache[period] = (self._bar_count, result)
        return result

    def adverse_drift_30s(self, now_ts: float) -> Decimal:
        """Raw 30-second adverse drift (absolute price change / older price).

        Used for regime detection and diagnostics. Use :meth:`adverse_drift_smooth`
        for cost-model inputs to avoid edge-gate flapping from single-tick spikes.
        """
        if len(self._samples) < 2:
            return _ZERO
        now_mid = self._samples[-1][1]
        older: Decimal | None = None
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
        return datetime.fromtimestamp(minute_ts, tz=UTC).isoformat()


# Backwards-compatible alias — will be removed in a future cleanup.
MidPriceBuffer = PriceBuffer
