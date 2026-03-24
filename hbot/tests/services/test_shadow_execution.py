from __future__ import annotations

from services.shadow_execution.main import _to_ms


def test_to_ms_none():
    assert _to_ms(None) is None


def test_to_ms_empty_string():
    assert _to_ms("") is None


def test_to_ms_digits():
    assert _to_ms("1710000000000") == 1710000000000


def test_to_ms_iso_string():
    result = _to_ms("2026-03-10T12:00:00+00:00")
    assert result is not None
    assert isinstance(result, int)
    assert result > 0


def test_to_ms_invalid():
    assert _to_ms("not-a-date") is None


def test_to_ms_integer_input():
    assert _to_ms(1234567890) == 1234567890
