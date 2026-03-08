"""Shared test scaffolding for hbot/tests/services/."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class _CaptureCursor:
    """Minimal DB cursor fake that records execute() calls and the last SQL."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.last_sql: str = ""

    def __enter__(self) -> "_CaptureCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> None:
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
