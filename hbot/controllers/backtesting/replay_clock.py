"""Controlled replay-time clock used by replay harness components."""
from __future__ import annotations


class ReplayClock:
    def __init__(self, start_ns: int):
        self._now_ns = int(start_ns)

    @property
    def now_ns(self) -> int:
        return self._now_ns

    @property
    def now_ms(self) -> int:
        return self._now_ns // 1_000_000

    def time(self) -> float:
        return self._now_ns / 1_000_000_000.0

    def advance(self, step_ns: int) -> int:
        self._now_ns += int(step_ns)
        return self._now_ns


__all__ = ["ReplayClock"]
