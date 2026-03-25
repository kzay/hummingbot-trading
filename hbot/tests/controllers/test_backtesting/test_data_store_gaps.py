"""Tests for scan_gaps in data_store.py."""
from __future__ import annotations

import pytest

from controllers.backtesting.data_store import scan_gaps


class TestScanGaps:
    def test_no_gaps(self) -> None:
        ts = [0, 60_000, 120_000, 180_000]
        assert scan_gaps(ts, expected_interval_ms=60_000) == []

    def test_single_gap(self) -> None:
        ts = [0, 60_000, 300_000, 360_000]
        gaps = scan_gaps(ts, expected_interval_ms=60_000)
        assert gaps == [(60_000, 300_000)]

    def test_multiple_gaps(self) -> None:
        ts = [0, 60_000, 300_000, 360_000, 900_000]
        gaps = scan_gaps(ts, expected_interval_ms=60_000)
        assert len(gaps) == 2
        assert gaps[0] == (60_000, 300_000)
        assert gaps[1] == (360_000, 900_000)

    def test_empty_list(self) -> None:
        assert scan_gaps([], expected_interval_ms=60_000) == []

    def test_single_element(self) -> None:
        assert scan_gaps([1000], expected_interval_ms=60_000) == []

    def test_threshold_boundary(self) -> None:
        ts = [0, 89_999]
        assert scan_gaps(ts, expected_interval_ms=60_000) == []
        ts2 = [0, 90_001]
        assert len(scan_gaps(ts2, expected_interval_ms=60_000)) == 1

    def test_custom_interval(self) -> None:
        ts = [0, 300_000, 1_000_000]
        gaps = scan_gaps(ts, expected_interval_ms=300_000)
        assert gaps == [(300_000, 1_000_000)]
