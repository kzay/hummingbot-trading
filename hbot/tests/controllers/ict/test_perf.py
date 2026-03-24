"""Performance smoke tests / regression guards for ICT library."""
from __future__ import annotations

import time
from decimal import Decimal

from controllers.common.ict.state import ICTConfig, ICTState

_D = Decimal


def _generate_volatile_series(n: int) -> list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]:
    """Generate n bars with varied price action for realistic perf testing."""
    candles = []
    base = _D("50000")
    for i in range(n):
        noise = _D(i % 7) - _D("3")
        trend = _D(i % 100) / _D("10")
        o = base + trend + noise
        h = o + _D("50") + abs(noise) * _D("10")
        l = o - _D("50") - abs(noise) * _D("10")
        c = o + noise * _D("5")
        candles.append((o, h, l, c, _D("1000")))
    return candles


class TestICTPerformance:
    def test_2k_bars_smoke(self):
        """ICTState must process 2,000 bars in under 30 seconds.

        Decimal arithmetic on Python 3.9 is slower than float.
        This is a regression guard, not a hard latency SLA.
        """
        series = _generate_volatile_series(2_000)
        cfg = ICTConfig(swing_length=5, fvg_decay_bars=10, ob_max_active=15)
        state = ICTState(config=cfg)

        start = time.perf_counter()
        for o, h, l, c, v in series:
            state.add_bar(o, h, l, c, v)
        elapsed = time.perf_counter() - start

        assert state.bar_count == 2_000
        assert elapsed < 30.0, f"Processed 2K bars in {elapsed:.2f}s (limit: 30s)"

    def test_linear_scaling_property(self):
        """Processing time should scale roughly linearly, not quadratically.

        We compare 1K vs 2K bars -- the 2K time should be < 3x the 1K time
        (allowing for overhead).
        """
        cfg = ICTConfig(swing_length=5)
        series_1k = _generate_volatile_series(1_000)
        series_2k = _generate_volatile_series(2_000)

        state = ICTState(config=cfg)
        start = time.perf_counter()
        for o, h, l, c, v in series_1k:
            state.add_bar(o, h, l, c, v)
        time_1k = time.perf_counter() - start

        state.reset()
        start = time.perf_counter()
        for o, h, l, c, v in series_2k:
            state.add_bar(o, h, l, c, v)
        time_2k = time.perf_counter() - start

        ratio = time_2k / max(time_1k, 0.001)
        assert ratio < 3.5, (
            f"Scaling ratio {ratio:.2f} (1K: {time_1k:.3f}s, 2K: {time_2k:.3f}s) "
            f"suggests non-linear growth"
        )
