"""Fee resolution and state management for EPP v2.4.

Encapsulates the fee resolution cascade (API → project profile → manual
fallback) and tracks fee state across tick cycles.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional

from services.common.fee_provider import FeeResolver
from services.common.utils import to_decimal

logger = logging.getLogger(__name__)


class FeeManager:
    """Manages fee resolution lifecycle and exposes current fee rates."""

    def __init__(
        self,
        fee_mode: str,
        fee_profile: str,
        require_fee_resolution: bool,
        fee_refresh_s: int,
        spot_fee_pct: Decimal,
    ):
        self._mode = fee_mode
        self._profile = fee_profile
        self._require = require_fee_resolution
        self._refresh_s = fee_refresh_s
        self.maker_fee_pct: Decimal = to_decimal(spot_fee_pct)
        self.taker_fee_pct: Decimal = to_decimal(spot_fee_pct)
        self.fee_source: str = "manual"
        self.fee_resolved: bool = False
        self.fee_resolution_error: str = ""
        self._last_resolve_ts: float = 0.0

    @property
    def require_resolution(self) -> bool:
        return self._require

    def ensure_fees(
        self,
        now_ts: float,
        connector: Any,
        connector_name: str,
        trading_pair: str,
        market_data_provider: Any,
    ) -> None:
        """Run the fee resolution cascade if due.

        Resolution order: manual → auto (API → connector runtime) → project profile → fallback.
        """
        canonical_name = (
            connector_name[:-12]
            if str(connector_name).endswith("_paper_trade")
            else connector_name
        )

        if self._mode in {"manual", "project"} and self.fee_resolved:
            return
        if self._mode == "auto" and self.fee_resolved and self.fee_source.startswith("api:"):
            return
        if self._last_resolve_ts > 0 and (now_ts - self._last_resolve_ts) < self._refresh_s:
            return
        self._last_resolve_ts = now_ts

        if self._mode == "manual":
            self.fee_source = "manual:spot_fee_pct"
            self.fee_resolved = self.maker_fee_pct > 0
            self.fee_resolution_error = "" if self.fee_resolved else "manual_fee_non_positive"
            return

        if self._mode == "auto":
            live_api = FeeResolver.from_exchange_api(connector, connector_name, trading_pair)
            if live_api is None and connector_name.endswith("_paper_trade"):
                try:
                    base_connector = market_data_provider.get_connector(canonical_name)
                except Exception:
                    base_connector = None
                live_api = FeeResolver.from_exchange_api(base_connector, canonical_name, trading_pair)
            if live_api is not None:
                self.maker_fee_pct = live_api.maker
                self.taker_fee_pct = live_api.taker
                self.fee_source = live_api.source
                self.fee_resolved = True
                self.fee_resolution_error = ""
                logger.info("Fee resolved via %s: maker=%s taker=%s", live_api.source, live_api.maker, live_api.taker)
                return
            runtime = FeeResolver.from_connector_runtime(connector, trading_pair)
            if runtime is not None:
                self.maker_fee_pct = runtime.maker
                self.taker_fee_pct = runtime.taker
                self.fee_source = runtime.source
                self.fee_resolved = True
                self.fee_resolution_error = ""
                return

        profile = FeeResolver.from_project_profile(connector_name, self._profile)
        if profile is not None:
            self.maker_fee_pct = profile.maker
            self.taker_fee_pct = profile.taker
            self.fee_source = profile.source
            self.fee_resolved = True
            self.fee_resolution_error = ""
            return

        if self.maker_fee_pct > 0:
            self.fee_source = "manual_fallback:spot_fee_pct"
            self.taker_fee_pct = self.maker_fee_pct
            self.fee_resolved = not self._require
            if self._require:
                self.fee_resolution_error = "resolver_failed_with_require_true"
            else:
                self.fee_resolution_error = ""
        else:
            self.fee_resolution_error = "no_fee_available"
            logger.error("Fee resolution failed: no source available for %s/%s", connector_name, trading_pair)
