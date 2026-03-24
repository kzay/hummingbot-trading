"""Shared test scaffolding for hbot/tests/services/."""
from __future__ import annotations

from typing import Any


class _CaptureCursor:
    """Minimal DB cursor fake that records execute() calls and the last SQL."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.last_sql: str = ""

    def __enter__(self) -> _CaptureCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.last_sql = sql
        self.calls.append(params or {})


class _CaptureConn:
    """Minimal DB connection fake backed by a single _CaptureCursor."""

    def __init__(self) -> None:
        self.cur = _CaptureCursor()

    def cursor(self) -> _CaptureCursor:
        return self.cur


class _Proc:
    """Minimal subprocess.CompletedProcess fake for monkeypatching subprocess.run."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
