"""Baseline tests for shadow-execution (parity) service — pure functions."""
from __future__ import annotations

import json
from pathlib import Path

from services.shadow_execution.main import (
    _latest_market_mid,
    _metric_result,
    _read_json,
    _to_ms,
)


class TestToMs:
    def test_none(self):
        assert _to_ms(None) is None

    def test_empty_string(self):
        assert _to_ms("") is None

    def test_digits(self):
        assert _to_ms("1710000000000") == 1710000000000

    def test_iso_string(self):
        result = _to_ms("2026-03-10T12:00:00+00:00")
        assert result is not None
        assert isinstance(result, int)
        assert result > 0

    def test_invalid(self):
        assert _to_ms("not-a-date") is None

    def test_integer_input(self):
        assert _to_ms(1234567890) == 1234567890


class TestReadJson:
    def test_missing_file(self, tmp_path: Path):
        result = _read_json(tmp_path / "nope.json", {"fallback": True})
        assert result == {"fallback": True}

    def test_valid_json(self, tmp_path: Path):
        p = tmp_path / "data.json"
        p.write_text(json.dumps({"key": "value"}))
        result = _read_json(p, {})
        assert result["key"] == "value"

    def test_invalid_json(self, tmp_path: Path):
        p = tmp_path / "bad.json"
        p.write_text("NOT{JSON")
        result = _read_json(p, {"default": 1})
        assert result == {"default": 1}

    def test_non_dict_json(self, tmp_path: Path):
        p = tmp_path / "list.json"
        p.write_text("[1, 2, 3]")
        result = _read_json(p, {"x": 0})
        assert result == {"x": 0}


class TestLatestMarketMid:
    def test_exact_match(self):
        markets = [(100, 50000.0), (200, 51000.0)]
        assert _latest_market_mid(markets, 200) == 51000.0

    def test_returns_closest_before(self):
        markets = [(100, 50000.0), (200, 51000.0), (300, 52000.0)]
        assert _latest_market_mid(markets, 250) == 51000.0

    def test_returns_none_if_all_future(self):
        markets = [(500, 50000.0)]
        assert _latest_market_mid(markets, 100) is None

    def test_empty_list(self):
        assert _latest_market_mid([], 100) is None


class TestMetricResult:
    def test_pass_within_delta(self):
        r = _metric_result("price", 100.0, 100.5, 1.0, informative=True, fail_when_missing=True)
        assert r["pass"] is True
        assert r["delta"] == -0.5

    def test_fail_outside_delta(self):
        r = _metric_result("price", 100.0, 105.0, 1.0, informative=True, fail_when_missing=True)
        assert r["pass"] is False

    def test_none_value_with_fail_when_missing(self):
        r = _metric_result("price", None, 100.0, 1.0, informative=True, fail_when_missing=True)
        assert r["pass"] is False
        assert r["note"] == "insufficient_data"

    def test_none_value_no_fail(self):
        r = _metric_result("price", None, 100.0, 1.0, informative=True, fail_when_missing=False)
        assert r["pass"] is True

    def test_not_informative(self):
        r = _metric_result("price", 100.0, 100.0, 1.0, informative=False, fail_when_missing=True)
        assert r["note"] == "insufficient_data"
