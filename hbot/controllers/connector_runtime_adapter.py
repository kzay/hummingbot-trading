from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

try:
    from hummingbot.core.data_type.common import PositionAction, PriceType
except ImportError:
    from hummingbot.core.data_type.common import PriceType

    class PositionAction:  # pragma: no cover - lightweight test fallback
        AUTO = "auto"

from services.common.market_data_plane import (
    CanonicalMarketState,
    CanonicalMarketDataReader,
    DirectionalTradeFeatures,
    MarketTopOfBook,
    TradeFlowFeatures,
)
from services.common.utils import to_decimal

logger = logging.getLogger(__name__)

_ZERO_D = Decimal("0")
_EPS = Decimal("1e-8")


class ConnectorRuntimeAdapter:
    """Thin wrapper around Hummingbot connector lookups and reads.

    Keeps controller logic independent from connector access details and
    provides structured logging on failures.
    """

    def __init__(self, controller: Any):
        self._controller = controller
        self.balance_read_failed: bool = False
        pair = str(controller.config.trading_pair)
        self._base_asset, self._quote_asset = pair.split("-") if "-" in pair else (pair, "USDT")
        self._cached_connector: Optional[Any] = None
        self._last_mid_price: Decimal = _ZERO_D
        self._last_mid_price_ts: float = 0.0
        self._last_mid_fallback_log_ts: float = 0.0
        self._canonical_market_reader = CanonicalMarketDataReader(
            connector_name=str(controller.config.connector_name),
            trading_pair=str(controller.config.trading_pair),
        )
        self._aux_market_readers: Dict[str, CanonicalMarketDataReader] = {}

    @property
    def connector_name(self) -> str:
        return str(self._controller.config.connector_name)

    @property
    def trading_pair(self) -> str:
        return str(self._controller.config.trading_pair)

    def refresh_connector_cache(self) -> Optional[Any]:
        """Resolve and cache the connector reference. Call once per tick."""
        strategy = getattr(self._controller, "strategy", None) or getattr(self._controller, "_strategy", None)
        if strategy is not None:
            connectors = getattr(strategy, "connectors", None)
            if isinstance(connectors, dict):
                connector = connectors.get(self.connector_name)
                if connector is not None:
                    self._cached_connector = connector
                    return connector
        try:
            self._cached_connector = self._controller.market_data_provider.get_connector(self.connector_name)
        except Exception:
            logger.warning("Failed to get connector %s from market_data_provider", self.connector_name, exc_info=True)
            self._cached_connector = None
        return self._cached_connector

    def get_connector(self) -> Optional[Any]:
        if self._cached_connector is not None:
            return self._cached_connector
        return self.refresh_connector_cache()

    def get_trading_rule(self) -> Optional[Any]:
        connector = self.get_connector()
        if connector is None:
            return None
        try:
            trading_rules = getattr(connector, "trading_rules", {})
            return trading_rules.get(self.trading_pair)
        except Exception:
            logger.warning("Trading rules unavailable for %s", self.trading_pair, exc_info=True)
            return None

    def get_mid_price(self) -> Decimal:
        canonical_mid = self._canonical_market_reader.get_mid_price()
        if canonical_mid > _ZERO_D:
            self._last_mid_price = canonical_mid
            self._last_mid_price_ts = time.time()
            return canonical_mid
        connector = self.get_connector()
        if connector is not None:
            # 1) Prefer connector-native mid getter (usually order-book based).
            get_mid_fn = getattr(connector, "get_mid_price", None)
            if callable(get_mid_fn):
                try:
                    mid = to_decimal(get_mid_fn(self.trading_pair))
                    if mid > _ZERO_D:
                        self._last_mid_price = mid
                        self._last_mid_price_ts = time.time()
                        return mid
                except TypeError:
                    try:
                        mid = to_decimal(get_mid_fn())
                        if mid > _ZERO_D:
                            self._last_mid_price = mid
                            self._last_mid_price_ts = time.time()
                            return mid
                    except Exception:
                        logger.debug("Connector get_mid_price() fallback failed for %s", self.trading_pair, exc_info=True)
                except Exception:
                    logger.debug("Connector get_mid_price(%s) failed", self.trading_pair, exc_info=True)
            # 2) Fallback to generic price_by_type.
            try:
                mid = to_decimal(connector.get_price_by_type(self.trading_pair, PriceType.MidPrice))
                if mid > _ZERO_D:
                    self._last_mid_price = mid
                    self._last_mid_price_ts = time.time()
                    return mid
            except Exception:
                logger.debug("Mid price read failed on connector for %s", self.trading_pair, exc_info=True)
            # 3) Final connector-side fallback from top-of-book.
            get_book_fn = getattr(connector, "get_order_book", None)
            if callable(get_book_fn):
                try:
                    book = get_book_fn(self.trading_pair)
                    best_bid = getattr(book, "best_bid", None)
                    best_ask = getattr(book, "best_ask", None)
                    bid_price = to_decimal(getattr(best_bid, "price", best_bid) or _ZERO_D)
                    ask_price = to_decimal(getattr(best_ask, "price", best_ask) or _ZERO_D)
                    if bid_price > _ZERO_D and ask_price > _ZERO_D:
                        mid = (bid_price + ask_price) / Decimal("2")
                        self._last_mid_price = mid
                        self._last_mid_price_ts = time.time()
                        return mid
                except Exception:
                    logger.debug("Order-book mid fallback failed for %s", self.trading_pair, exc_info=True)

        # 4) Avoid returning zero on transient connector gaps: use last known mid.
        if self._last_mid_price > _ZERO_D:
            now = time.time()
            if now - self._last_mid_fallback_log_ts >= 120.0:
                self._last_mid_fallback_log_ts = now
                logger.warning(
                    "Mid price fallback active for %s/%s; reusing last known mid=%s (age_s=%d).",
                    self.connector_name,
                    self.trading_pair,
                    self._last_mid_price,
                    int(now - self._last_mid_price_ts) if self._last_mid_price_ts > 0 else -1,
                )
            return self._last_mid_price

        logger.error("Mid price unavailable for %s/%s and no cached fallback", self.connector_name, self.trading_pair)
        return Decimal("0")

    def get_top_of_book(self) -> MarketTopOfBook:
        canonical_top = self._canonical_market_reader.get_top_of_book()
        if canonical_top is not None:
            return canonical_top
        connector = self.get_connector()
        if connector is None:
            return MarketTopOfBook()
        try:
            book = connector.get_order_book(self.trading_pair)
        except Exception:
            logger.warning("Order book read failed for %s", self.trading_pair, exc_info=True)
            return MarketTopOfBook()
        bid_p = _ZERO_D
        ask_p = _ZERO_D
        bid_sz = _ZERO_D
        ask_sz = _ZERO_D
        try:
            best_bid = next(iter(book.bid_entries()), None)
            if best_bid is not None:
                bid_p = to_decimal(getattr(best_bid, "price", 0))
                bid_sz = to_decimal(getattr(best_bid, "amount", 0))
        except Exception:
            logger.debug("Top bid unavailable for %s", self.trading_pair, exc_info=True)
        try:
            best_ask = next(iter(book.ask_entries()), None)
            if best_ask is not None:
                ask_p = to_decimal(getattr(best_ask, "price", 0))
                ask_sz = to_decimal(getattr(best_ask, "amount", 0))
        except Exception:
            logger.debug("Top ask unavailable for %s", self.trading_pair, exc_info=True)
        spread_pct = _ZERO_D
        mid = (bid_p + ask_p) / Decimal("2") if bid_p > _ZERO_D and ask_p > _ZERO_D else _ZERO_D
        if mid > _ZERO_D and ask_p >= bid_p:
            spread_pct = (ask_p - bid_p) / mid
        return MarketTopOfBook(
            best_bid=bid_p,
            best_ask=ask_p,
            spread_pct=spread_pct,
            best_bid_size=bid_sz,
            best_ask_size=ask_sz,
        )

    def get_canonical_market_state(self) -> Optional[CanonicalMarketState]:
        return self._canonical_market_reader.get_market_state()

    def market_state_debug(self) -> Dict[str, Any]:
        debug = self._canonical_market_reader.market_state_debug()
        debug["connector_fallback_mid_price"] = (
            float(self._last_mid_price) if self._last_mid_price > _ZERO_D else None
        )
        debug["connector_fallback_mid_age_s"] = (
            max(0.0, time.time() - self._last_mid_price_ts) if self._last_mid_price_ts > 0 else None
        )
        return debug

    def get_depth_imbalance(self, depth: int = 5) -> Decimal:
        canonical_imbalance = self._canonical_market_reader.get_depth_imbalance(depth=depth)
        if canonical_imbalance != _ZERO_D:
            return canonical_imbalance
        try:
            connector = self.get_connector()
            if connector is None:
                return _ZERO_D
            book = connector.get_order_book(self.trading_pair)
            bid_depth = sum(to_decimal(getattr(e, "amount", 0)) for e in list(book.bid_entries())[:depth])
            ask_depth = sum(to_decimal(getattr(e, "amount", 0)) for e in list(book.ask_entries())[:depth])
            total = bid_depth + ask_depth
            if total <= _ZERO_D:
                return _ZERO_D
            return (bid_depth - ask_depth) / total
        except Exception:
            logger.debug("Depth imbalance unavailable for %s", self.trading_pair, exc_info=True)
            return _ZERO_D

    def _reader_for(self, connector_name: str, trading_pair: str) -> CanonicalMarketDataReader:
        key = f"{str(connector_name).strip().lower()}::{str(trading_pair).strip().upper()}"
        reader = self._aux_market_readers.get(key)
        if reader is None:
            reader = CanonicalMarketDataReader(connector_name=connector_name, trading_pair=trading_pair)
            self._aux_market_readers[key] = reader
        return reader

    def get_trade_flow_features(
        self,
        *,
        connector_name: Optional[str] = None,
        trading_pair: Optional[str] = None,
        count: int = 120,
        stale_after_ms: Optional[int] = None,
    ) -> TradeFlowFeatures:
        reader = (
            self._canonical_market_reader
            if not connector_name and not trading_pair
            else self._reader_for(connector_name or self.connector_name, trading_pair or self.trading_pair)
        )
        return reader.get_trade_flow_features(count=count, stale_after_ms=stale_after_ms)

    def get_directional_trade_features(
        self,
        *,
        spot_connector_name: str,
        spot_trading_pair: str,
        futures_count: int = 120,
        spot_count: int = 120,
        stale_after_ms: Optional[int] = None,
        divergence_threshold_pct: Decimal = Decimal("0.15"),
        stacked_imbalance_min: int = 3,
        delta_spike_threshold: Decimal = Decimal("3.0"),
        funding_rate: Optional[Decimal] = None,
        long_funding_max: Decimal = Decimal("0.0005"),
        short_funding_min: Decimal = Decimal("-0.0003"),
    ) -> DirectionalTradeFeatures:
        return self._canonical_market_reader.get_directional_trade_features(
            spot_connector_name=spot_connector_name,
            spot_trading_pair=spot_trading_pair,
            futures_count=futures_count,
            spot_count=spot_count,
            stale_after_ms=stale_after_ms,
            divergence_threshold_pct=divergence_threshold_pct,
            stacked_imbalance_min=stacked_imbalance_min,
            delta_spike_threshold=delta_spike_threshold,
            funding_rate=funding_rate,
            long_funding_max=long_funding_max,
            short_funding_min=short_funding_min,
        )

    def get_balances(self) -> Tuple[Decimal, Decimal]:
        connector = self.get_connector()
        if connector is None:
            self.balance_read_failed = True
            return _ZERO_D, _ZERO_D
        base = _ZERO_D
        quote = _ZERO_D
        try:
            base = to_decimal(connector.get_balance(self._base_asset))
            quote = to_decimal(connector.get_balance(self._quote_asset))
            self.balance_read_failed = False
        except Exception:
            self.balance_read_failed = True
            logger.error("Balance read failed for %s on %s", self.trading_pair, self.connector_name, exc_info=True)
        return base, quote

    def get_position_amount(
        self,
        *,
        position_action: Optional[PositionAction] = None,
    ) -> Decimal:
        connector = self.get_connector()
        if connector is None:
            return _ZERO_D
        pos_fn = getattr(connector, "get_position", None) or getattr(connector, "account_positions", None)
        if not callable(pos_fn):
            return _ZERO_D
        try:
            if position_action is not None:
                try:
                    pos = pos_fn(self.trading_pair, position_action=position_action)
                except TypeError:
                    pos = pos_fn(self.trading_pair, position_side=str(getattr(position_action, "name", position_action)).lower())
            else:
                try:
                    pos = pos_fn(self.trading_pair)
                except TypeError:
                    pos = pos_fn()
        except Exception:
            logger.debug("Position read failed for %s", self.trading_pair, exc_info=True)
            return _ZERO_D
        if hasattr(pos, "amount"):
            return to_decimal(getattr(pos, "amount", _ZERO_D))
        if isinstance(pos, dict):
            if position_action is not None:
                action_key = str(getattr(position_action, "name", position_action)).strip().lower()
                bucket = pos.get(action_key) if isinstance(pos.get(action_key), dict) else pos.get(self.trading_pair, {})
                if isinstance(bucket, dict):
                    if action_key in {"open_long", "close_long"} and "long_amount" in bucket:
                        return to_decimal(bucket.get("long_amount", _ZERO_D))
                    if action_key in {"open_short", "close_short"} and "short_amount" in bucket:
                        return to_decimal(bucket.get("short_amount", _ZERO_D))
                    return to_decimal(bucket.get("amount", _ZERO_D))
            bucket = pos.get(self.trading_pair, {}) if isinstance(pos.get(self.trading_pair), dict) else pos
            if isinstance(bucket, dict):
                return to_decimal(bucket.get("amount", _ZERO_D))
        return _ZERO_D

    def balances_consistent(self) -> bool:
        connector = self.get_connector()
        if connector is None:
            return False
        try:
            base_total = to_decimal(connector.get_balance(self._base_asset))
            base_free = to_decimal(connector.get_available_balance(self._base_asset))
            quote_total = to_decimal(connector.get_balance(self._quote_asset))
            quote_free = to_decimal(connector.get_available_balance(self._quote_asset))
        except Exception:
            logger.warning("Balance consistency check failed for %s", self.trading_pair, exc_info=True)
            return False
        if base_total < 0 or quote_total < 0:
            return False
        if base_free > base_total + _EPS:
            return False
        if quote_free > quote_total + _EPS:
            return False
        return True

    def status_dict(self) -> Dict[str, bool]:
        connector = self.get_connector()
        if connector is None:
            return {}
        try:
            status = getattr(connector, "status_dict", None)
            return dict(status) if isinstance(status, dict) else {}
        except Exception:
            logger.debug("status_dict read failed for %s", self.connector_name, exc_info=True)
            return {}

    def ready(self) -> bool:
        connector = self.get_connector()
        if connector is None:
            return False
        try:
            ready_attr = getattr(connector, "ready", None)
            return bool(ready_attr() if callable(ready_attr) else ready_attr)
        except Exception:
            logger.warning("Connector ready check failed for %s", self.connector_name, exc_info=True)
            return False

    def status_summary(self) -> Dict[str, bool]:
        """Return the connector's status_dict with a ready flag for observability."""
        result = self.status_dict()
        result["ready"] = self.ready()
        return result
