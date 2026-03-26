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

Resolution support: PriceBuffer accepts ``resolution_minutes`` at construction.
Internally it always stores 1-minute bars in ``_1m_store``.  When
``resolution_minutes > 1``, the ``_indicator_bars`` property returns cached
resampled bars aligned to wall-clock boundaries.  All indicator methods read
from ``_indicator_bars`` — no per-call resolution parameter needed.
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

SUPPORTED_RESOLUTIONS = {1, 5, 15, 60}


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

    When ``resolution_minutes > 1``, indicator methods automatically operate
    on resampled bars (e.g. 15-minute bars) while the underlying storage
    remains at 1-minute granularity.
    """

    def __init__(
        self,
        sample_interval_sec: int = 10,
        max_minutes: int = 2880,
        resolution_minutes: int = 1,
    ):
        if resolution_minutes not in SUPPORTED_RESOLUTIONS:
            raise ValueError(
                f"resolution_minutes={resolution_minutes} not in "
                f"{sorted(SUPPORTED_RESOLUTIONS)}"
            )
        self.sample_interval_sec = sample_interval_sec
        self.max_minutes = max_minutes
        self._resolution_minutes = resolution_minutes
        self._1m_store: deque[MinuteBar] = deque(maxlen=max_minutes)
        self._samples: deque[tuple[float, Decimal]] = deque(maxlen=720)

        self._ema_values: dict[int, Decimal] = {}
        self._atr_values: dict[int, Decimal] = {}
        self._prev_close: Decimal | None = None
        self._bar_count: int = 0
        self._drift_ewma: Decimal | None = None

        # Resampled bars cache (used only when resolution > 1)
        self._res_cache: list[MinuteBar] = []
        self._res_cache_version: int = -1

        # Per-bar caches: store (bar_count_at_computation, result).
        # Invalidated automatically when _bar_count advances.
        self._rsi_cache: dict[int, tuple[int, Decimal | None]] = {}
        self._adx_cache: dict[int, tuple[int, Decimal | None]] = {}
        self._sma_cache: dict[int, tuple[int, Decimal | None]] = {}
        self._stddev_cache: dict[int, tuple[int, Decimal | None]] = {}
        self._closes_cache: tuple[int, list[Decimal]] = (0, [])
        self._macd_cache: dict[tuple[int, int, int], tuple[int, tuple[Decimal, Decimal, Decimal] | None]] = {}
        self._stoch_rsi_cache: dict[tuple[int, int, int, int], tuple[int, tuple[Decimal, Decimal] | None]] = {}

    @property
    def resolution_minutes(self) -> int:
        """Configured bar resolution in minutes (read-only)."""
        return self._resolution_minutes

    @property
    def bar_count(self) -> int:
        """Number of 1-minute bars currently in the buffer."""
        return self._bar_count

    @property
    def _indicator_bars(self) -> deque[MinuteBar] | list[MinuteBar]:
        """Return bars at the configured resolution for indicator computation.

        At resolution=1 this returns ``_1m_store`` directly (zero overhead).
        At resolution>1 this returns a cached list of resampled bars,
        invalidated whenever a new 1m bar is added.
        """
        if self._resolution_minutes == 1:
            return self._1m_store
        if self._res_cache_version == self._bar_count:
            return self._res_cache
        self._res_cache = self._resample()
        self._res_cache_version = self._bar_count
        return self._res_cache

    def _resample(self) -> list[MinuteBar]:
        """Aggregate 1m bars into higher-TF bars aligned to wall-clock boundaries."""
        bucket_sec = self._resolution_minutes * 60
        result: list[MinuteBar] = []
        current: MinuteBar | None = None
        current_ts: int = 0
        for bar in self._1m_store:
            bucket_ts = (int(bar.ts_minute) // bucket_sec) * bucket_sec
            if current is None or bucket_ts != current_ts:
                if current is not None:
                    result.append(current)
                current = MinuteBar(
                    ts_minute=bucket_ts,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                )
                current_ts = bucket_ts
            else:
                current.high = max(current.high, bar.high)
                current.low = min(current.low, bar.low)
                current.close = bar.close
        if current is not None:
            result.append(current)
        return result

    @property
    def bars(self) -> list[MinuteBar]:
        """Return bars at the configured resolution."""
        result = self._indicator_bars
        if isinstance(result, list):
            return result
        return list(result)

    @property
    def bars_1m(self) -> list[MinuteBar]:
        """Return raw 1-minute bars regardless of resolution."""
        return list(self._1m_store)

    @property
    def closes(self) -> list[Decimal]:
        """Return close prices at the configured resolution, cached per bar count."""
        cached_count, cached_list = self._closes_cache
        if cached_count == self._bar_count and cached_count > 0:
            return cached_list
        result = [bar.close for bar in self._indicator_bars]
        self._closes_cache = (self._bar_count, result)
        return result

    def _reset_state(self) -> None:
        self._1m_store.clear()
        self._samples.clear()
        self._ema_values.clear()
        self._atr_values.clear()
        self._prev_close = None
        self._bar_count = 0
        self._drift_ewma = None
        self._res_cache.clear()
        self._res_cache_version = -1
        self._rsi_cache.clear()
        self._adx_cache.clear()
        self._sma_cache.clear()
        self._stddev_cache.clear()
        self._closes_cache = (0, [])
        self._macd_cache.clear()
        self._stoch_rsi_cache.clear()

    def seed_bars(self, bars: list[MinuteBar], reset: bool = False) -> int:
        """Bulk-load closed bars into the buffer before live samples begin."""
        if reset:
            self._reset_state()
        elif len(self._1m_store) > 0:
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
                    self._1m_store.append(gap_bar)
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
            self._1m_store.append(seeded_bar)
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
        if self._1m_store and bar_ts <= int(self._1m_store[-1].ts_minute):
            return
        if self._1m_store:
            cursor = int(self._1m_store[-1].ts_minute) + 60
            while cursor < bar_ts:
                gap_bar = MinuteBar(
                    ts_minute=cursor,
                    open=self._1m_store[-1].close, high=self._1m_store[-1].close,
                    low=self._1m_store[-1].close, close=self._1m_store[-1].close,
                )
                self._1m_store.append(gap_bar)
                self._bar_count += 1
                self._on_bar_complete(gap_bar)
                cursor += 60
        appended = MinuteBar(
            ts_minute=bar_ts,
            open=Decimal(bar.open), high=Decimal(bar.high),
            low=Decimal(bar.low), close=Decimal(bar.close),
        )
        self._1m_store.append(appended)
        self._bar_count += 1
        self._on_bar_complete(appended)

    def add_sample(self, timestamp_s: float, price: Decimal) -> None:
        if price.is_nan() or price.is_infinite() or price <= 0:
            return
        self._samples.append((timestamp_s, price))
        minute_ts = int(timestamp_s // 60) * 60
        if len(self._1m_store) == 0:
            self._1m_store.append(
                MinuteBar(ts_minute=minute_ts, open=price, high=price, low=price, close=price)
            )
            self._bar_count = 1
            self._prev_close = price
            return

        last = self._1m_store[-1]
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
                self._1m_store.append(gap_bar)
                last = self._1m_store[-1]
                self._bar_count += 1
                self._on_bar_complete(gap_bar)
                cursor += 60
            self._1m_store.append(
                MinuteBar(ts_minute=minute_ts, open=price, high=price, low=price, close=price)
            )
            self._bar_count += 1

    def _on_bar_complete(self, bar: MinuteBar) -> None:
        """Update running indicators when a bar finalizes."""
        close = bar.close

        if self._resolution_minutes == 1:
            # Unchanged: incremental EMA/ATR at 1m resolution
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
        else:
            # At higher resolution: clear EMA/ATR caches only when a
            # resolution-level bar boundary is crossed.  This avoids
            # wasteful full-recompute on every 1m bar.
            bucket_sec = self._resolution_minutes * 60
            if int(bar.ts_minute) % bucket_sec == 0:
                self._ema_values.clear()
                self._atr_values.clear()
                self._prev_close = None

    def ready(self, min_bars: int) -> bool:
        return len(self._indicator_bars) >= min_bars

    def latest_close(self) -> Decimal | None:
        bars = self._indicator_bars
        if not bars:
            return None
        return bars[-1].close

    def ema(self, period: int) -> Decimal | None:
        """Return the running EMA for *period*. O(1) after warm-up at resolution=1.

        At resolution>1, recomputed from resampled bars on each bar change
        (trivial cost at typical bar counts).
        """
        bars = self._indicator_bars
        if period <= 0 or len(bars) < period:
            return None
        if period in self._ema_values:
            return self._ema_values[period]
        closes = [bar.close for bar in bars]
        alpha = _TWO / Decimal(period + 1)
        one_minus_alpha = _ONE - alpha
        ema_value = closes[0]
        for close in closes[1:]:
            ema_value = alpha * close + one_minus_alpha * ema_value
        self._ema_values[period] = ema_value
        return ema_value

    def atr(self, period: int) -> Decimal | None:
        """Return the running ATR for *period*. O(1) after warm-up at resolution=1.

        At resolution>1, recomputed from resampled bars on each bar change.
        """
        bars = self._indicator_bars
        if period <= 0 or len(bars) < period + 1:
            return None
        if period in self._atr_values:
            return self._atr_values[period]
        bars_list = list(bars) if not isinstance(bars, list) else bars
        trs: list[Decimal] = []
        for i in range(1, len(bars_list)):
            prev_close = bars_list[i - 1].close
            high = bars_list[i].high
            low = bars_list[i].low
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
        """Return simple moving average of close prices. Cached per bar."""
        bars = self._indicator_bars
        if period <= 0 or len(bars) < period:
            return None
        cached = self._sma_cache.get(period)
        if cached is not None and cached[0] == self._bar_count:
            return cached[1]
        n = len(bars)
        total = 0.0
        for i in range(n - period, n):
            total += float(bars[i].close)
        result = Decimal(str(total / period))
        self._sma_cache[period] = (self._bar_count, result)
        return result

    def stddev(self, period: int) -> Decimal | None:
        """Return population standard deviation of close prices. Cached per bar."""
        bars = self._indicator_bars
        if period <= 0 or len(bars) < period:
            return None
        cached = self._stddev_cache.get(period)
        if cached is not None and cached[0] == self._bar_count:
            return cached[1]
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

    def macd(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple[Decimal, Decimal, Decimal] | None:
        """Return (macd_line, signal_line, histogram) computed from closes.

        Returns None when fewer than ``max(fast, slow) + signal`` completed
        bars are available.  Results are cached per ``_bar_count`` and
        parameter tuple.
        """
        key = (fast, slow, signal)
        cached = self._macd_cache.get(key)
        if cached is not None and cached[0] == self._bar_count:
            return cached[1]

        closes = self.closes
        min_bars = max(fast, slow) + signal
        if fast <= 0 or slow <= 0 or signal <= 0 or len(closes) < min_bars:
            self._macd_cache[key] = (self._bar_count, None)
            return None

        fast_alpha = 2.0 / (fast + 1)
        slow_alpha = 2.0 / (slow + 1)

        fast_ema = float(closes[0])
        slow_ema = float(closes[0])
        macd_series: list[float] = []

        for c in closes:
            cf = float(c)
            fast_ema = fast_alpha * cf + (1.0 - fast_alpha) * fast_ema
            slow_ema = slow_alpha * cf + (1.0 - slow_alpha) * slow_ema
            macd_series.append(fast_ema - slow_ema)

        sig_alpha = 2.0 / (signal + 1)
        sig_ema = macd_series[0]
        for v in macd_series[1:]:
            sig_ema = sig_alpha * v + (1.0 - sig_alpha) * sig_ema

        macd_line = Decimal(str(macd_series[-1]))
        signal_line = Decimal(str(sig_ema))
        histogram = macd_line - signal_line
        result = (macd_line, signal_line, histogram)
        self._macd_cache[key] = (self._bar_count, result)
        return result

    def rsi(self, period: int = 14) -> Decimal | None:
        """Return Cutler's RSI (SMA-based) on close prices. Cached per bar."""
        cached = self._rsi_cache.get(period)
        if cached is not None and cached[0] == self._bar_count:
            return cached[1]
        bars = self._indicator_bars
        n = len(bars)
        if period <= 0 or n < period + 1:
            self._rsi_cache[period] = (self._bar_count, None)
            return None
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

    def stoch_rsi(
        self,
        rsi_period: int = 14,
        stoch_period: int = 14,
        k_smooth: int = 3,
        d_smooth: int = 3,
    ) -> tuple[Decimal, Decimal] | None:
        """Return (K, D) of Stochastic RSI, each in [0, 100].

        Derives a full RSI series from close history, then applies a rolling
        stochastic oscillator over that series.  Returns None when insufficient
        bars exist to compute the full pipeline.

        Flat-price guard: if RSI is constant (no range) in the stochastic
        window, returns (50, 50) instead of a division-by-zero.
        """
        key = (rsi_period, stoch_period, k_smooth, d_smooth)
        cached = self._stoch_rsi_cache.get(key)
        if cached is not None and cached[0] == self._bar_count:
            return cached[1]

        closes = self.closes
        min_bars = rsi_period + 1 + stoch_period + k_smooth + d_smooth - 2
        if (
            rsi_period <= 0
            or stoch_period <= 0
            or k_smooth <= 0
            or d_smooth <= 0
            or len(closes) < min_bars
        ):
            self._stoch_rsi_cache[key] = (self._bar_count, None)
            return None

        rsi_series: list[float] = []
        for end in range(rsi_period + 1, len(closes) + 1):
            gains = 0.0
            losses = 0.0
            for i in range(end - rsi_period - 1, end - 1):
                delta = float(closes[i + 1]) - float(closes[i])
                if delta > 0.0:
                    gains += delta
                elif delta < 0.0:
                    losses -= delta
            avg_gain = gains / rsi_period
            avg_loss = losses / rsi_period
            if avg_loss <= 0.0:
                rsi_series.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_series.append(100.0 - 100.0 / (1.0 + rs))

        if len(rsi_series) < stoch_period:
            self._stoch_rsi_cache[key] = (self._bar_count, None)
            return None

        raw_k: list[float] = []
        for i in range(stoch_period - 1, len(rsi_series)):
            window = rsi_series[i - stoch_period + 1: i + 1]
            hi = max(window)
            lo = min(window)
            rng = hi - lo
            if rng < 1e-12:
                raw_k.append(50.0)
            else:
                raw_k.append((rsi_series[i] - lo) / rng * 100.0)

        if len(raw_k) < k_smooth:
            self._stoch_rsi_cache[key] = (self._bar_count, None)
            return None

        k_line: list[float] = []
        for i in range(k_smooth - 1, len(raw_k)):
            k_line.append(sum(raw_k[i - k_smooth + 1: i + 1]) / k_smooth)

        if len(k_line) < d_smooth:
            self._stoch_rsi_cache[key] = (self._bar_count, None)
            return None

        d_values: list[float] = []
        for i in range(d_smooth - 1, len(k_line)):
            d_values.append(sum(k_line[i - d_smooth + 1: i + 1]) / d_smooth)

        k_val = Decimal(str(k_line[-1]))
        d_val = Decimal(str(d_values[-1]))
        result = (k_val, d_val)
        self._stoch_rsi_cache[key] = (self._bar_count, result)
        return result

    def adx(self, period: int = 14) -> Decimal | None:
        """Return ADX using Wilder-style directional movement smoothing."""
        cached = self._adx_cache.get(period)
        if cached is not None and cached[0] == self._bar_count:
            return cached[1]

        bars = self._indicator_bars
        n = len(bars)
        min_bars = period * 2 + 1
        if n < min_bars:
            self._adx_cache[period] = (self._bar_count, None)
            return None

        window = min(n, max(min_bars, period * 6))
        offset = n - window
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

        Uses raw price samples, independent of bar resolution.
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

        Uses raw price samples, independent of bar resolution.
        """
        raw = self.adverse_drift_30s(now_ts)
        if self._drift_ewma is None:
            self._drift_ewma = raw
        else:
            self._drift_ewma = alpha * raw + (_ONE - alpha) * self._drift_ewma
        return self._drift_ewma

    @staticmethod
    def min_bars_for_resolution(period: int, resolution_minutes: int) -> int:
        """Minimum number of 1m bars needed for an indicator at a given resolution."""
        return period * resolution_minutes

    @staticmethod
    def minute_iso(minute_ts: int) -> str:
        return datetime.fromtimestamp(minute_ts, tz=UTC).isoformat()


# Backwards-compatible alias — will be removed in a future cleanup.
MidPriceBuffer = PriceBuffer
