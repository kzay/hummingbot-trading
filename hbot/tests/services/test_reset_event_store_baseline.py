from __future__ import annotations

from scripts.utils.reset_event_store_baseline import _stream_entries_added


class _FakeRedisClient:
    def __init__(self, *, xinfo_response=None, xinfo_error: Exception | None = None, xlen_value: int = 0):
        self._xinfo_response = xinfo_response
        self._xinfo_error = xinfo_error
        self._xlen_value = int(xlen_value)

    def xinfo_stream(self, _stream: str):
        if self._xinfo_error is not None:
            raise self._xinfo_error
        return self._xinfo_response

    def xlen(self, _stream: str) -> int:
        return self._xlen_value


def test_stream_entries_added_prefers_xinfo_entries_added_value() -> None:
    client = _FakeRedisClient(xinfo_response={"entries-added": "12345", "length": 500}, xlen_value=500)
    assert _stream_entries_added(client, "hb.market_data.v1") == 12345


def test_stream_entries_added_falls_back_to_xlen_when_xinfo_fails() -> None:
    client = _FakeRedisClient(xinfo_error=RuntimeError("redis unavailable"), xlen_value=77)
    assert _stream_entries_added(client, "hb.market_data.v1") == 77


def test_stream_entries_added_falls_back_to_xlen_when_entries_added_is_invalid() -> None:
    client = _FakeRedisClient(xinfo_response={"entries-added": "not-a-number", "length": 99}, xlen_value=99)
    assert _stream_entries_added(client, "hb.market_data.v1") == 99

