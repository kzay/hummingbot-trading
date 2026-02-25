"""Latency model for Paper Engine v2.

Follows NautilusTrader LatencyModelConfig with nanosecond-precision,
per-command-type latency (base + insert + cancel).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LatencyModel:
    """Simulates network + exchange processing latency for order commands.

    All values are in nanoseconds. Set to 0 to disable latency simulation.
    Matches NautilusTrader LatencyModelConfig field names.
    """

    base_latency_ns: int = 0          # applied to all commands
    insert_latency_ns: int = 0        # additional latency for order insert
    cancel_latency_ns: int = 0        # additional latency for cancel

    @property
    def total_insert_ns(self) -> int:
        return self.base_latency_ns + self.insert_latency_ns

    @property
    def total_cancel_ns(self) -> int:
        return self.base_latency_ns + self.cancel_latency_ns

    @property
    def is_active(self) -> bool:
        return self.total_insert_ns > 0 or self.total_cancel_ns > 0

    @classmethod
    def from_ms(cls, base_ms: int = 0, insert_ms: int = 0, cancel_ms: int = 0) -> "LatencyModel":
        return cls(
            base_latency_ns=base_ms * 1_000_000,
            insert_latency_ns=insert_ms * 1_000_000,
            cancel_latency_ns=cancel_ms * 1_000_000,
        )


# -- Convenience presets ----------------------------------------------------

NO_LATENCY = LatencyModel()

FAST_LATENCY = LatencyModel(base_latency_ns=50_000_000)          # 50ms all

REALISTIC_LATENCY = LatencyModel(
    base_latency_ns=100_000_000,      # 100ms base
    insert_latency_ns=50_000_000,     # +50ms insert
    cancel_latency_ns=30_000_000,     # +30ms cancel
)

PAPER_DEFAULT_LATENCY = LatencyModel.from_ms(base_ms=150)         # 150ms, matches paper_latency_ms default


def make_latency_model(name: str, latency_ms: int = 0) -> LatencyModel:
    """Create a latency model by name string."""
    if name == "fast":
        return FAST_LATENCY
    if name == "realistic":
        return REALISTIC_LATENCY
    if name == "none" or name == "":
        return NO_LATENCY
    if latency_ms > 0:
        return LatencyModel.from_ms(base_ms=latency_ms)
    return NO_LATENCY
