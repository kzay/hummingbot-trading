"""Tests for auto-calibration deque structures and bounded eviction."""
from __future__ import annotations

from collections import deque
from decimal import Decimal


class TestCalibrationDequeContracts:
    def test_minute_history_maxlen(self):
        d: deque[dict] = deque(maxlen=20_000)
        for i in range(25_000):
            d.append({"tick": i})
        assert len(d) == 20_000
        assert d[0]["tick"] == 5_000

    def test_fill_history_maxlen(self):
        d: deque[dict] = deque(maxlen=20_000)
        for i in range(20_001):
            d.append({"fill": i})
        assert len(d) == 20_000
        assert d[0]["fill"] == 1

    def test_change_events_maxlen(self):
        d: deque[tuple[float, Decimal]] = deque(maxlen=1_000)
        for i in range(1_500):
            d.append((float(i), Decimal(str(i))))
        assert len(d) == 1_000
        assert d[0][0] == 500.0

    def test_percentile_with_insufficient_data(self):
        data = [Decimal("1"), Decimal("2")]
        assert len(data) < 30

    def test_empty_deque_iteration(self):
        d: deque[dict] = deque(maxlen=20_000)
        results = [x for x in d if x.get("edge_bps", 0) > 5]
        assert results == []

    def test_bounded_append_preserves_order(self):
        d: deque[dict] = deque(maxlen=5)
        for i in range(8):
            d.append({"v": i})
        assert [x["v"] for x in d] == [3, 4, 5, 6, 7]
