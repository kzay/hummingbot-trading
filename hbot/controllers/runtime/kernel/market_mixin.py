"""Market conditions evaluation mixin for SharedRuntimeKernel."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from hummingbot.core.data_type.common import TradeType

from controllers.runtime.kernel.config import _ZERO, _TWO, _10K
from controllers.runtime.runtime_types import MarketConditions
from platform_lib.core.utils import to_decimal

logger = logging.getLogger(__name__)


class MarketConditionsMixin:

    def _evaluate_market_conditions(self, now_ts: float, band_pct: Decimal) -> MarketConditions:
        """Build market condition snapshot with reconnect-aware stale-book detection."""
        is_high_vol = band_pct >= self.config.high_vol_band_pct
        bid_p, ask_p, market_spread_pct, best_bid_size, best_ask_size = self._get_top_of_book()
        if self.config.ob_imbalance_skew_weight > _ZERO:
            self._ob_imbalance = self._compute_ob_imbalance(self.config.ob_imbalance_depth)

        connector_ready_now = self._connector_ready()
        if not self._last_connector_ready and connector_ready_now:
            self._ws_reconnect_count += 1
            self._reconnect_cooldown_until = now_ts + self.config.reconnect_cooldown_s
            reconnect_grace_s = max(0.0, float(self.config.order_book_reconnect_grace_s))
            self._book_reconnect_grace_until_ts = now_ts + reconnect_grace_s
            # Reset stale clock at reconnect boundary; keep fail-closed logic for true long stale windows.
            if self._book_stale_since_ts > 0.0:
                self._book_stale_since_ts = now_ts
            logger.info("Connector reconnected (count=%d), cooldown %.0fs",
                        self._ws_reconnect_count, self.config.reconnect_cooldown_s)
        self._last_connector_ready = connector_ready_now

        if bid_p > _ZERO and ask_p > _ZERO:
            # Treat the book as "fresh" if either top prices OR top sizes change.
            # Price-only checks trigger false staleness during calm markets.
            if (
                bid_p == self._last_book_bid
                and ask_p == self._last_book_ask
                and best_bid_size == self._last_book_bid_size
                and best_ask_size == self._last_book_ask_size
            ):
                if self._book_stale_since_ts <= 0:
                    self._book_stale_since_ts = now_ts
            else:
                self._book_stale_since_ts = 0.0
                self._last_book_bid = bid_p
                self._last_book_ask = ask_p
                self._last_book_bid_size = best_bid_size
                self._last_book_ask_size = best_ask_size
        order_book_stale = self._is_order_book_stale(now_ts)
        market_spread_threshold = Decimal(self.config.min_market_spread_bps) / _10K
        market_spread_too_small = (
            self.config.min_market_spread_bps > 0 and market_spread_pct > 0 and market_spread_pct < market_spread_threshold
        )

        # Keep a tiny absolute floor to avoid zero-distance quoting edge cases.
        side_spread_floor = max(Decimal("0.000001"), to_decimal(self.config.min_side_spread_bps) / _10K)
        if market_spread_pct > 0:
            half_market = market_spread_pct / _TWO + side_spread_floor
            if half_market > side_spread_floor:
                side_spread_floor = half_market

        return MarketConditions(
            is_high_vol=is_high_vol,
            bid_p=bid_p,
            ask_p=ask_p,
            market_spread_pct=market_spread_pct,
            best_bid_size=best_bid_size,
            best_ask_size=best_ask_size,
            connector_ready=connector_ready_now,
            order_book_stale=order_book_stale,
            market_spread_too_small=market_spread_too_small,
            side_spread_floor=side_spread_floor,
        )

    def _order_book_stale_age_s(self, now_ts: float) -> float:
        if self._book_stale_since_ts <= 0.0:
            return 0.0
        return max(0.0, float(now_ts) - float(self._book_stale_since_ts))

    def _is_order_book_stale(self, now_ts: float) -> bool:
        if self._book_stale_since_ts <= 0.0:
            return False
        if float(now_ts) < float(getattr(self, "_book_reconnect_grace_until_ts", 0.0) or 0.0):
            return False
        stale_after_s = (
            max(5.0, float(self.config.order_book_stale_after_s))
            + max(0.0, float(self.config.max_clock_skew_s))
        )
        return self._order_book_stale_age_s(now_ts) > stale_after_s

    def _get_top_of_book(self) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        top = self._runtime_adapter.get_top_of_book()
        return top.best_bid, top.best_ask, top.spread_pct, top.best_bid_size, top.best_ask_size

    def _open_order_level_ids(self) -> list[str]:
        """Return side level_ids occupied by open orders on the connector.

        When an executor is stopped but its underlying order lingers, this
        marks the side as occupied so duplicate makers are not layered.
        Works uniformly for both paper (bridged) and live connectors.

        NOTE: the live Bitget perp connector does NOT expose
        ``get_open_orders()``; it uses ``in_flight_orders`` / ``limit_orders``
        instead.  Before going live, either (a) add a live-connector adapter
        that wraps ``limit_orders`` into ``get_open_orders()``, or (b) fall
        back to ``connector.limit_orders`` here.  The ``callable()`` guard
        below silently returns an empty list when the method is absent.
        """
        try:
            connector = self._connector()
            open_orders_fn = getattr(connector, "get_open_orders", None)
            if not callable(open_orders_fn):
                return []
            connector_name = str(getattr(self.config, "connector_name", "") or "")
            trading_pair = str(self.config.trading_pair)
            occupied: set = set()
            for order in (open_orders_fn() or []):
                if str(getattr(order, "trading_pair", "")) != trading_pair:
                    continue
                source_bot = str(getattr(order, "source_bot", "") or "")
                if connector_name and source_bot and source_bot != connector_name:
                    continue
                side = str(getattr(getattr(order, "trade_type", None), "name", "") or "").upper()
                if side == "BUY":
                    occupied.update(
                        self.get_level_id_from_side(TradeType.BUY, level)
                        for level in range(len(self._runtime_levels.buy_spreads))
                    )
                elif side == "SELL":
                    occupied.update(
                        self.get_level_id_from_side(TradeType.SELL, level)
                        for level in range(len(self._runtime_levels.sell_spreads))
                    )
            return sorted(occupied)
        except Exception:
            return []

    def _open_order_count(self) -> int:
        """Return open order count for this controller via the connector."""
        try:
            connector = self._connector()
            open_orders_fn = getattr(connector, "get_open_orders", None)
            if not callable(open_orders_fn):
                return 0
            connector_name = str(getattr(self.config, "connector_name", "") or "")
            trading_pair = str(self.config.trading_pair)
            count = 0
            for order in (open_orders_fn() or []):
                if str(getattr(order, "trading_pair", "")) != trading_pair:
                    continue
                source_bot = str(getattr(order, "source_bot", "") or "")
                if connector_name and source_bot and source_bot != connector_name:
                    continue
                count += 1
            return count
        except Exception:
            return 0
