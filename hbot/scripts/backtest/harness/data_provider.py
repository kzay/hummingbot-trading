"""Market data providers for backtesting.

Provides bar data from event store JSONL files (primary) or OHLCV sources
(secondary) through a common ``MarketDataProvider`` protocol.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterator, List, Optional, Protocol

from services.common.utils import to_decimal


@dataclass(frozen=True)
class BarData:
    """Single bar of market data consumed by strategy adapters."""
    timestamp_s: float
    mid_price: Decimal
    bid_price: Decimal
    ask_price: Decimal
    bid_size: Decimal
    ask_size: Decimal
    spread_pct: Decimal
    equity_quote: Optional[Decimal] = None
    base_pct: Optional[Decimal] = None
    extra: Optional[dict] = None


class MarketDataProvider(Protocol):
    """Protocol for bar-by-bar market data iteration."""

    def bars(self) -> Iterator[BarData]:
        """Yield bars in chronological order."""
        ...

    @property
    def source_label(self) -> str:
        """Human-readable data source identifier."""
        ...


class EventStoreProvider:
    """Reads ``market_snapshot`` events from event store JSONL files."""

    def __init__(self, event_file: Path, trading_pair: Optional[str] = None):
        self._path = event_file
        self._pair_filter = trading_pair

    @property
    def source_label(self) -> str:
        return f"event_store:{self._path.name}"

    def bars(self) -> Iterator[BarData]:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                payload = event.get("payload", event)
                if not isinstance(payload, dict):
                    continue
                event_type = str(payload.get("event_type", event.get("event_type", ""))).strip()
                if event_type != "market_snapshot":
                    continue
                pair = str(payload.get("trading_pair", "")).strip()
                if self._pair_filter and pair != self._pair_filter:
                    continue

                mid = to_decimal(payload.get("mid_price", 0))
                if mid <= 0:
                    continue
                spread = to_decimal(payload.get("spread_pct", "0.002"))
                half_spread = spread / Decimal("2")
                yield BarData(
                    timestamp_s=float(payload.get("timestamp_ms", 0)) / 1000.0,
                    mid_price=mid,
                    bid_price=mid * (Decimal("1") - half_spread),
                    ask_price=mid * (Decimal("1") + half_spread),
                    bid_size=Decimal("1"),
                    ask_size=Decimal("1"),
                    spread_pct=spread,
                    equity_quote=to_decimal(payload.get("equity_quote")) if payload.get("equity_quote") else None,
                    base_pct=to_decimal(payload.get("base_pct")) if payload.get("base_pct") else None,
                    extra=payload,
                )
