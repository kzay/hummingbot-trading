from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from hummingbot.core.data_type.common import PriceType

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
        connector = self.get_connector()
        if connector is not None:
            try:
                return to_decimal(connector.get_price_by_type(self.trading_pair, PriceType.MidPrice))
            except Exception:
                logger.warning("Mid price read failed on connector for %s", self.trading_pair)
        try:
            return to_decimal(
                self._controller.market_data_provider.get_price_by_type(
                    self.connector_name,
                    self.trading_pair,
                    PriceType.MidPrice,
                )
            )
        except Exception:
            logger.error("Mid price unavailable for %s/%s", self.connector_name, self.trading_pair, exc_info=True)
            return Decimal("0")

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
            return {}

    def ready(self) -> bool:
        connector = self.get_connector()
        if connector is None:
            return False
        try:
            ready_attr = getattr(connector, "ready", None)
            return bool(ready_attr() if callable(ready_attr) else ready_attr)
        except Exception:
            logger.warning("Connector ready check failed for %s", self.connector_name)
            return False

    def status_summary(self) -> Dict[str, bool]:
        """Return the connector's status_dict with a ready flag for observability."""
        result = self.status_dict()
        result["ready"] = self.ready()
        return result
