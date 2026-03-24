"""Regression test: ICTState on 2000-bar real BTC data matches pinned reference."""
from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from controllers.common.ict.state import ICTConfig, ICTState

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def ict_result():
    """Run ICTState over the 2000-bar BTC fixture and return final state."""
    cfg = ICTConfig()
    state = ICTState(cfg)
    csv_path = FIXTURES / "btc_2000_1m.csv"
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            state.add_bar(
                Decimal(row["open"]),
                Decimal(row["high"]),
                Decimal(row["low"]),
                Decimal(row["close"]),
                Decimal(row["volume"]),
            )
    return state


@pytest.fixture(scope="module")
def reference():
    """Load pinned reference expectations."""
    ref_path = FIXTURES / "btc_2000_reference.json"
    with open(ref_path) as f:
        return json.load(f)


class TestFixtureReference:
    def test_bar_count(self, ict_result, reference):
        assert ict_result.bar_count == reference["bar_count"]

    def test_swing_count(self, ict_result, reference):
        assert len(ict_result.swings) == reference["swing_count"]

    def test_fvg_total_count(self, ict_result, reference):
        assert len(ict_result.all_fvgs) == reference["fvg_total_count"]

    def test_fvg_active_count(self, ict_result, reference):
        assert len(ict_result.active_fvgs) == reference["fvg_active_count"]

    def test_structure_count(self, ict_result, reference):
        assert len(ict_result.structure_events) == reference["structure_count"]

    def test_ob_total_count(self, ict_result, reference):
        assert len(ict_result.all_obs) == reference["ob_total_count"]

    def test_displacement_count(self, ict_result, reference):
        assert len(ict_result.displacement_events) == reference["displacement_count"]

    def test_vi_total_count(self, ict_result, reference):
        assert len(ict_result.all_vis) == reference["vi_total_count"]

    def test_breaker_count(self, ict_result, reference):
        assert len(ict_result.all_breakers) == reference["breaker_count"]

    def test_trend(self, ict_result, reference):
        assert ict_result.trend == reference["trend"]

    def test_last_5_swings(self, ict_result, reference):
        swings = ict_result.swings[-5:]
        expected = reference["last_5_swings"]
        assert len(swings) == len(expected)
        for s, exp in zip(swings, expected):
            assert s.index == exp["index"]
            assert s.direction == exp["direction"]
            assert str(s.level) == exp["level"]

    def test_last_5_structures(self, ict_result, reference):
        structs = ict_result.structure_events[-5:]
        expected = reference["last_5_structures"]
        assert len(structs) == len(expected)
        for s, exp in zip(structs, expected):
            assert s.index == exp["index"]
            assert s.direction == exp["direction"]
            assert s.event_type == exp["event_type"]
