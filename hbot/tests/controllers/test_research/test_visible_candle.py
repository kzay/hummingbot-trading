"""Tests for VisibleCandleRow — lookahead bias prevention."""
from __future__ import annotations

import math
from decimal import Decimal

import pytest

from controllers.backtesting.types import CandleRow, VisibleCandleRow


def _make_candle() -> CandleRow:
    return CandleRow(
        timestamp_ns=1_000_000_000,
        open=Decimal("100.0"),
        high=Decimal("105.0"),
        low=Decimal("95.0"),
        close=Decimal("102.0"),
        volume=Decimal("500.0"),
    )


class TestVisibleCandleRow:
    def test_masked_fields_are_nan_before_final_step(self):
        candle = _make_candle()
        v = VisibleCandleRow(candle, step_index=0, max_step=4)
        assert math.isnan(float(v.high))
        assert math.isnan(float(v.low))
        assert math.isnan(float(v.close))

    def test_open_always_visible(self):
        candle = _make_candle()
        v = VisibleCandleRow(candle, step_index=0, max_step=4)
        assert v.open == Decimal("100.0")

    def test_volume_always_visible(self):
        candle = _make_candle()
        v = VisibleCandleRow(candle, step_index=0, max_step=4)
        assert v.volume == Decimal("500.0")

    def test_timestamp_always_visible(self):
        candle = _make_candle()
        v = VisibleCandleRow(candle, step_index=0, max_step=4)
        assert v.timestamp_ns == 1_000_000_000

    def test_final_step_reveals_all_fields(self):
        candle = _make_candle()
        v = VisibleCandleRow(candle, step_index=4, max_step=4)
        assert v.high == Decimal("105.0")
        assert v.low == Decimal("95.0")
        assert v.close == Decimal("102.0")

    def test_step_index_equals_max_step_reveals(self):
        candle = _make_candle()
        v = VisibleCandleRow(candle, step_index=3, max_step=3)
        assert not math.isnan(float(v.close))

    def test_mid_step_still_masked(self):
        candle = _make_candle()
        v = VisibleCandleRow(candle, step_index=2, max_step=4)
        assert math.isnan(float(v.high))
