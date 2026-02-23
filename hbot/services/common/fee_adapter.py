"""Pluggable exchange fee adapters.

Provides a protocol-based registry so adding a new exchange requires only
implementing ``ExchangeFeeAdapter.fetch_fees()`` — no changes to caller code.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional, Protocol

from services.common.fee_provider import FeeRates
from services.common.utils import to_decimal

logger = logging.getLogger(__name__)


class ExchangeFeeAdapter(Protocol):
    """Protocol for exchange-specific fee fetching."""

    def fetch_fees(
        self, connector: Any, connector_name: str, trading_pair: str
    ) -> Optional[FeeRates]:
        """Fetch maker/taker fee rates from the exchange API.

        Returns ``None`` if credentials are missing or the API call fails.
        """
        ...


class BitgetFeeAdapter:
    """Bitget fee adapter — delegates to the existing ``FeeResolver.from_exchange_api``."""

    def fetch_fees(
        self, connector: Any, connector_name: str, trading_pair: str
    ) -> Optional[FeeRates]:
        from services.common.fee_provider import FeeResolver
        return FeeResolver.from_exchange_api(connector, connector_name, trading_pair)


class BinanceFeeAdapter:
    """Binance fee adapter — extracts fees from connector runtime attributes.

    Binance connectors typically expose ``trading_fees`` or per-connector
    fee attributes.  This adapter tries those paths.
    """

    def fetch_fees(
        self, connector: Any, connector_name: str, trading_pair: str
    ) -> Optional[FeeRates]:
        if connector is None:
            return None
        try:
            trading_fees = getattr(connector, "trading_fees", None)
            if isinstance(trading_fees, dict):
                row = trading_fees.get(trading_pair)
                if row is not None:
                    maker = to_decimal(getattr(row, "maker_fee", getattr(row, "maker_fee_rate", 0)))
                    taker = to_decimal(getattr(row, "taker_fee", getattr(row, "taker_fee_rate", 0)))
                    if maker > 0 and taker > 0:
                        return FeeRates(maker=maker, taker=taker, source="api:binance:trading_fees")
        except Exception:
            logger.warning("Binance fee extraction failed for %s", trading_pair, exc_info=True)
        return None


class FeeAdapterRegistry:
    """Registry mapping exchange name prefixes to fee adapters."""

    def __init__(self) -> None:
        self._adapters: Dict[str, ExchangeFeeAdapter] = {}

    def register(self, exchange_prefix: str, adapter: ExchangeFeeAdapter) -> None:
        self._adapters[exchange_prefix] = adapter

    def resolve(
        self, connector: Any, connector_name: str, trading_pair: str
    ) -> Optional[FeeRates]:
        """Try each registered adapter whose prefix matches *connector_name*."""
        canonical = connector_name.replace("_paper_trade", "")
        for prefix, adapter in self._adapters.items():
            if canonical.startswith(prefix):
                result = adapter.fetch_fees(connector, connector_name, trading_pair)
                if result is not None:
                    return result
        return None


_default_registry = FeeAdapterRegistry()
_default_registry.register("bitget", BitgetFeeAdapter())
_default_registry.register("binance", BinanceFeeAdapter())


def get_default_registry() -> FeeAdapterRegistry:
    """Return the singleton fee adapter registry with built-in adapters."""
    return _default_registry
