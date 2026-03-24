"""Post-init replay dependency injection for real controllers."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MethodType
from typing import Any

ReaderFactory = Callable[[str, str], Any]


class ReplayInjection:
    @staticmethod
    def apply(
        controller: Any,
        *,
        trade_reader: Any,
        replay_connector: Any,
        market_data_provider: Any,
        aux_readers: Mapping[str, Any] | None = None,
        reader_factory: ReaderFactory | None = None,
    ) -> Any:
        """Replace live data sources on an already-instantiated controller."""
        controller._trade_reader = trade_reader
        controller.market_data_provider = market_data_provider

        connector_name = str(getattr(getattr(controller, "config", None), "connector_name", "") or "")
        controller.connectors = {connector_name: replay_connector} if connector_name else {}

        for attr in ("strategy", "_strategy"):
            strategy = getattr(controller, attr, None)
            if strategy is None:
                continue
            strategy.connectors = controller.connectors
            strategy.market_data_provider = market_data_provider

        runtime_adapter = getattr(controller, "_runtime_adapter", None)
        if runtime_adapter is None:
            return controller

        runtime_adapter._canonical_market_reader = trade_reader
        runtime_adapter._cached_connector = replay_connector
        runtime_adapter._aux_market_readers = dict(aux_readers or {})

        if reader_factory is not None:
            def _reader_for(self, requested_connector_name: str, trading_pair: str):
                return reader_factory(requested_connector_name, trading_pair)

            runtime_adapter._reader_for = MethodType(_reader_for, runtime_adapter)

        return controller


__all__ = ["ReplayInjection"]
