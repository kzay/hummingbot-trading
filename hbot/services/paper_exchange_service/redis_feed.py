"""Redis-backed market-data feed for PaperDesk service mode.

Implements the ``MarketDataFeed`` protocol by holding the latest
``OrderBookSnapshot`` per instrument, updated by the service main loop
when market data rows arrive from ``hb.market_data.v1``.
"""
from __future__ import annotations

import time
from decimal import Decimal

from simulation.types import (
    _ZERO,
    BookLevel,
    InstrumentId,
    OrderBookSnapshot,
)

_NS_PER_MS = 1_000_000


class RedisMarketFeed:
    """Mutable feed that the service loop pushes data into.

    ``PaperDesk`` reads from this via ``get_book`` / ``get_mid_price``
    during ``tick()``.
    """

    def __init__(self) -> None:
        self._books: dict[str, OrderBookSnapshot] = {}
        self._funding_rates: dict[str, Decimal] = {}

    def update_book(
        self,
        instrument_id: InstrumentId,
        bids: list[tuple[Decimal, Decimal]],
        asks: list[tuple[Decimal, Decimal]],
        timestamp_ms: int,
        funding_rate: Decimal = _ZERO,
    ) -> None:
        bid_levels = tuple(BookLevel(price=p, size=s) for p, s in bids if p > _ZERO and s > _ZERO)
        ask_levels = tuple(BookLevel(price=p, size=s) for p, s in asks if p > _ZERO and s > _ZERO)
        if not bid_levels and not ask_levels:
            return
        snap = OrderBookSnapshot(
            instrument_id=instrument_id,
            bids=bid_levels,
            asks=ask_levels,
            timestamp_ns=int(timestamp_ms) * _NS_PER_MS,
        )
        key = instrument_id.key
        self._books[key] = snap
        if funding_rate != _ZERO:
            self._funding_rates[key] = funding_rate

    def set_funding_rate(self, instrument_id: InstrumentId, rate: Decimal) -> None:
        self._funding_rates[instrument_id.key] = rate

    # -- MarketDataFeed protocol ---------------------------------------------

    def get_book(self, instrument_id: InstrumentId) -> OrderBookSnapshot | None:
        return self._books.get(instrument_id.key)

    def get_mid_price(self, instrument_id: InstrumentId) -> Decimal | None:
        book = self._books.get(instrument_id.key)
        return book.mid_price if book else None

    def get_funding_rate(self, instrument_id: InstrumentId) -> Decimal:
        return self._funding_rates.get(instrument_id.key, _ZERO)

    def has_data(self, instrument_id: InstrumentId) -> bool:
        return instrument_id.key in self._books

    def book_age_ms(self, instrument_id: InstrumentId) -> int:
        book = self._books.get(instrument_id.key)
        if book is None:
            return 999_999
        now_ns = int(time.time() * 1_000_000_000)
        return max(0, (now_ns - book.timestamp_ns) // _NS_PER_MS)
