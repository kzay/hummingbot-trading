from __future__ import annotations

import pytest

from services.ops_db_writer.main import _apply_timescale


class _BombConn:
    def cursor(self):  # pragma: no cover - should never be called in disabled mode
        raise AssertionError("cursor should not be used when timescale is disabled")


class _FailCreateCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):  # noqa: ANN001
        raise RuntimeError("extension not available")

    def fetchone(self):
        return (False,)


class _FailCreateConn:
    def cursor(self):
        return _FailCreateCursor()

    def commit(self):
        return None

    def rollback(self):
        return None


def test_apply_timescale_disabled_skips_db_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_DB_TIMESCALE_ENABLED", "false")
    meta = _apply_timescale(_BombConn())  # type: ignore[arg-type]
    assert meta["enabled"] is False
    assert meta["extension_available"] is False


def test_apply_timescale_required_raises_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_DB_TIMESCALE_ENABLED", "true")
    monkeypatch.setenv("OPS_DB_TIMESCALE_REQUIRED", "true")
    with pytest.raises(RuntimeError):
        _apply_timescale(_FailCreateConn())  # type: ignore[arg-type]
