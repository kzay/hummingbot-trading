"""Market data feeds for Paper Engine v2.

Implements the MarketDataFeed protocol with three adapters:
- HummingbotDataFeed: reads from HB connector (used inside HB paper mode)
- ReplayDataFeed: replays from event store JSONL (regression testing)
- NullDataFeed: always returns None (for tests without live data)

CCXTDataFeed is implemented but requires ccxt.pro and runs in a daemon thread.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Protocol

from controllers.paper_engine_v2.types import (
    BookLevel,
    InstrumentId,
    OrderBookSnapshot,
    _ZERO,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class MarketDataFeed(Protocol):
    def get_book(self, instrument_id: InstrumentId) -> Optional[OrderBookSnapshot]: ...
    def get_mid_price(self, instrument_id: InstrumentId) -> Optional[Decimal]: ...
    def get_funding_rate(self, instrument_id: InstrumentId) -> Decimal: ...


# ---------------------------------------------------------------------------
# NullDataFeed (tests)
# ---------------------------------------------------------------------------

class NullDataFeed:
    """Returns None for all queries. Used in unit tests."""

    def get_book(self, instrument_id: InstrumentId) -> Optional[OrderBookSnapshot]:
        return None

    def get_mid_price(self, instrument_id: InstrumentId) -> Optional[Decimal]:
        return None

    def get_funding_rate(self, instrument_id: InstrumentId) -> Decimal:
        return _ZERO


# ---------------------------------------------------------------------------
# StaticDataFeed (tests with fixed book)
# ---------------------------------------------------------------------------

class StaticDataFeed:
    """Returns a fixed book snapshot. Used in unit tests."""

    def __init__(self, book: OrderBookSnapshot, funding_rate: Decimal = _ZERO):
        self._book = book
        self._rate = funding_rate

    def get_book(self, instrument_id: InstrumentId) -> Optional[OrderBookSnapshot]:
        return self._book

    def get_mid_price(self, instrument_id: InstrumentId) -> Optional[Decimal]:
        return self._book.mid_price if self._book else None

    def get_funding_rate(self, instrument_id: InstrumentId) -> Decimal:
        return self._rate


# ---------------------------------------------------------------------------
# HummingbotDataFeed
# ---------------------------------------------------------------------------

class HummingbotDataFeed:
    """Reads live book from a Hummingbot connector.

    This adapter is the only class in data_feeds.py that imports HB types.
    The import is deferred to avoid import errors in non-HB environments.
    """

    def __init__(self, connector: object, trading_pair: str):
        self._connector = connector
        self._trading_pair = trading_pair

    def get_book(self, instrument_id: InstrumentId) -> Optional[OrderBookSnapshot]:
        try:
            book = self._connector.get_order_book(self._trading_pair)
            if book is None:
                return None

            bids = []
            asks = []

            try:
                for entry in book.bid_entries():
                    p = Decimal(str(getattr(entry, "price", 0)))
                    s = Decimal(str(getattr(entry, "amount", 0)))
                    if p > _ZERO and s > _ZERO:
                        bids.append(BookLevel(price=p, size=s))
            except Exception:
                pass

            try:
                for entry in book.ask_entries():
                    p = Decimal(str(getattr(entry, "price", 0)))
                    s = Decimal(str(getattr(entry, "amount", 0)))
                    if p > _ZERO and s > _ZERO:
                        asks.append(BookLevel(price=p, size=s))
            except Exception:
                pass

            if not bids and not asks:
                return None

            import time
            return OrderBookSnapshot(
                instrument_id=instrument_id,
                bids=tuple(sorted(bids, key=lambda x: -x.price)),
                asks=tuple(sorted(asks, key=lambda x: x.price)),
                timestamp_ns=int(time.time() * 1_000_000_000),
            )
        except Exception as exc:
            logger.debug("HB book read failed: %s", exc)
            return None

    def get_mid_price(self, instrument_id: InstrumentId) -> Optional[Decimal]:
        try:
            from hummingbot.core.data_type.common import PriceType  # type: ignore
            v = self._connector.get_price_by_type(self._trading_pair, PriceType.MidPrice)
            p = Decimal(str(v)) if v else None
            return p if p and p > _ZERO else None
        except Exception:
            book = self.get_book(instrument_id)
            return book.mid_price if book else None

    def get_funding_rate(self, instrument_id: InstrumentId) -> Decimal:
        try:
            rates = getattr(self._connector, "funding_rates", {})
            if isinstance(rates, dict):
                v = rates.get(self._trading_pair)
                if v is not None:
                    return Decimal(str(v))
        except Exception:
            pass
        return _ZERO


# ---------------------------------------------------------------------------
# ReplayDataFeed (regression testing)
# ---------------------------------------------------------------------------

class ReplayDataFeed:
    """Replays market_snapshot events from a JSONL event store file.

    Deterministic: same file always produces the same book sequence.
    Used for regression testing and backtest integration.
    """

    def __init__(self, events_path: str, trading_pair: str):
        self._trading_pair = trading_pair
        self._snapshots: list[Dict] = []
        self._idx: int = 0
        self._load(events_path)

    def _load(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            logger.warning("ReplayDataFeed: file not found: %s", path)
            return
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if ev.get("event_type") == "market_snapshot":
                    if ev.get("trading_pair") == self._trading_pair:
                        self._snapshots.append(ev)
            except Exception:
                pass
        logger.info("ReplayDataFeed: loaded %d snapshots for %s", len(self._snapshots), self._trading_pair)

    def get_book(self, instrument_id: InstrumentId) -> Optional[OrderBookSnapshot]:
        if self._idx >= len(self._snapshots):
            return None
        ev = self._snapshots[self._idx]
        self._idx += 1

        mid = Decimal(str(ev.get("mid_price", 0)))
        if mid <= _ZERO:
            return None

        # Synthesize a minimal L1 book from mid price
        spread_pct = Decimal("0.0005")  # 5bps synthetic spread
        half = mid * spread_pct / 2
        bid = BookLevel(price=mid - half, size=Decimal("1"))
        ask = BookLevel(price=mid + half, size=Decimal("1"))

        return OrderBookSnapshot(
            instrument_id=instrument_id,
            bids=(bid,),
            asks=(ask,),
            timestamp_ns=int(ev.get("timestamp_ms", 0) * 1_000_000),
        )

    def get_mid_price(self, instrument_id: InstrumentId) -> Optional[Decimal]:
        book = self.get_book(instrument_id)
        return book.mid_price if book else None

    def get_funding_rate(self, instrument_id: InstrumentId) -> Decimal:
        return _ZERO

    def reset(self) -> None:
        self._idx = 0
