from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

BarSource = Literal["quote_mid", "exchange_ohlcv"]
HistoryStatus = Literal["fresh", "stale", "gapped", "degraded", "empty"]


@dataclass(frozen=True)
class MarketBarKey:
    connector_name: str
    trading_pair: str
    bar_source: BarSource = "quote_mid"


@dataclass
class MarketBar:
    bucket_start_ms: int
    bar_interval_s: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume_base: Decimal | None = None
    volume_quote: Decimal | None = None
    is_closed: bool = True
    bar_source: str = "quote_mid"


@dataclass
class MarketHistoryStatus:
    status: HistoryStatus
    freshness_ms: int
    max_gap_s: int
    coverage_ratio: float
    source_used: str
    degraded_reason: str = ""
    bars_returned: int = 0
    bars_requested: int = 0


@dataclass
class HistoryPolicy:
    preferred_sources: list[str] = field(default_factory=lambda: ["quote_mid"])
    allow_fallback: bool = True
    require_closed: bool = True
    min_acceptable_status: Literal["fresh", "degraded"] = "degraded"
    min_bars_before_trading: int = 30
    max_acceptable_gap_s: int = 300
