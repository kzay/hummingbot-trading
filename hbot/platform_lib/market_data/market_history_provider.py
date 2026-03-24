from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from platform_lib.market_data.market_history_types import MarketBar, MarketBarKey, MarketHistoryStatus

if TYPE_CHECKING:
    from controllers.price_buffer import PriceBuffer


class MarketHistoryProvider(Protocol):
    def get_bars(
        self,
        key: MarketBarKey,
        bar_interval_s: int = 60,
        limit: int = 300,
        end_time_ms: int | None = None,
        require_closed: bool = True,
    ) -> tuple[list[MarketBar], MarketHistoryStatus]:
        ...

    def get_status(
        self,
        key: MarketBarKey,
        bar_interval_s: int = 60,
    ) -> MarketHistoryStatus:
        ...

    def seed_price_buffer(
        self,
        buffer: PriceBuffer,
        key: MarketBarKey,
        bars_needed: int,
        now_ms: int,
    ) -> MarketHistoryStatus:
        ...
