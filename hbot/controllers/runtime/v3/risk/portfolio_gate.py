"""Portfolio-level risk gate — cross-bot risk from Redis."""

from __future__ import annotations

import logging
import time
from typing import Any

from controllers.runtime.v3.risk_types import RiskDecision
from controllers.runtime.v3.signals import TradingSignal
from controllers.runtime.v3.types import MarketSnapshot

logger = logging.getLogger(__name__)


class PortfolioRiskGate:
    """Layer 1: Cross-bot portfolio risk.

    Reads PORTFOLIO_RISK_STREAM from Redis.  When a breach is detected,
    hard-stops all signal processing.
    """

    def __init__(self, redis_client: Any = None) -> None:
        self._redis = redis_client
        self._hard_stop_latched: bool = False
        self._last_check_ts: float = 0.0
        self._check_interval_s: float = 1.0

    def evaluate(
        self,
        signal: TradingSignal,
        snapshot: MarketSnapshot,
    ) -> RiskDecision:
        if self._hard_stop_latched:
            return RiskDecision.reject("portfolio", "portfolio_hard_stop_latched")

        now = time.time()
        if now - self._last_check_ts < self._check_interval_s:
            return RiskDecision.approve("portfolio")

        self._last_check_ts = now

        if self._redis is not None:
            try:
                breach = self._check_redis_stream()
                if breach:
                    self._hard_stop_latched = True
                    logger.warning("Portfolio risk breach detected: %s", breach)
                    return RiskDecision.reject(
                        "portfolio",
                        "portfolio_breach",
                        breach_detail=breach,
                    )
            except Exception as e:
                logger.debug("Portfolio risk check failed: %s", e)

        return RiskDecision.approve("portfolio")

    def _check_redis_stream(self) -> str:
        """Check PORTFOLIO_RISK_STREAM for breach events. Returns reason or empty."""
        from platform_lib.contracts.stream_names import PORTFOLIO_RISK_STREAM

        try:
            entries = self._redis.read_latest(PORTFOLIO_RISK_STREAM, count=1)
            if entries:
                for _stream, messages in entries:
                    for _msg_id, data in messages:
                        action = data.get("action", "")
                        if action in ("hard_stop", "emergency_stop"):
                            return data.get("reason", action)
        except Exception:
            pass
        return ""

    def reset(self) -> None:
        """Clear latched hard-stop (manual recovery)."""
        self._hard_stop_latched = False


__all__ = ["PortfolioRiskGate"]
