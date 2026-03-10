from __future__ import annotations

from typing import List, Optional, Protocol, Tuple, TYPE_CHECKING

from services.common.market_history_types import MarketBar, MarketBarKey, MarketHistoryStatus

if TYPE_CHECKING:
    from controllers.price_buffer import MidPriceBuffer


class MarketHistoryProvider(Protocol):
    def get_bars(
        self,
        key: MarketBarKey,
        bar_interval_s: int = 60,
        limit: int = 300,
        end_time_ms: Optional[int] = None,
        require_closed: bool = True,
    ) -> Tuple[List[MarketBar], MarketHistoryStatus]:
        ...

    def get_status(
        self,
        key: MarketBarKey,
        bar_interval_s: int = 60,
    ) -> MarketHistoryStatus:
        ...

    def seed_midprice_buffer(
        self,
        buffer: "MidPriceBuffer",
        key: MarketBarKey,
        bars_needed: int,
        now_ms: int,
    ) -> MarketHistoryStatus:
        ...
