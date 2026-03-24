"""Frozen event dataclasses for the ICT indicator library.

All events are immutable snapshots.  State changes (e.g. OB mitigation,
liquidity sweep) produce a new replacement event -- detectors never mutate
an existing event object.

NOTE: ``slots=True`` requires Python 3.10+.  This project targets 3.9,
so we omit it.  The ``frozen=True`` invariant is the critical guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SwingEvent:
    """Confirmed swing high or swing low."""

    index: int
    direction: int  # +1 = swing high, -1 = swing low
    level: Decimal


@dataclass(frozen=True)
class FVGEvent:
    """Fair Value Gap (imbalance zone)."""

    index: int
    direction: int  # +1 bullish, -1 bearish
    top: Decimal
    bottom: Decimal
    size_bps: Decimal
    mitigated: bool = False
    mitigated_index: int = -1


@dataclass(frozen=True)
class StructureEvent:
    """Break of Structure or Change of Character."""

    index: int
    event_type: str  # "bos" | "choch"
    direction: int  # +1 bullish, -1 bearish
    level: Decimal
    swing_index: int


@dataclass(frozen=True)
class OrderBlockEvent:
    """Order Block zone."""

    index: int
    direction: int  # +1 bullish, -1 bearish
    top: Decimal
    bottom: Decimal
    status: str  # "active" | "mitigated" | "breaker"
    status_index: int = -1


@dataclass(frozen=True)
class LiquidityPool:
    """Cluster of swing highs or lows forming a liquidity zone."""

    start_index: int
    end_index: int
    direction: int  # +1 buy-side (highs cluster), -1 sell-side
    level: Decimal
    count: int
    swept: bool = False
    sweep_index: int = -1


@dataclass(frozen=True)
class DisplacementEvent:
    """Large-body candle exceeding ATR threshold."""

    index: int
    direction: int
    body_atr_ratio: Decimal


@dataclass(frozen=True)
class VolumeImbalanceEvent:
    """Body-to-body gap (not wick-to-wick like FVG)."""

    index: int
    direction: int
    top: Decimal
    bottom: Decimal
    mitigated: bool = False
    mitigated_index: int = -1
