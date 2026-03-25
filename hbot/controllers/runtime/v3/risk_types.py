"""Risk decision types for the v3 trading desk."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from controllers.runtime.v3.signals import TradingSignal


@dataclass(frozen=True)
class RiskDecision:
    """Result of a risk layer evaluation.

    Each layer (portfolio, bot, signal) produces one of these.
    The DeskRiskGate composes them into a final decision.
    """

    approved: bool
    reason: str = ""
    layer: str = ""
    modified_signal: TradingSignal | None = None
    """If approved but the layer reduced sizing / widened spreads."""

    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def approve(layer: str, **metadata: Any) -> RiskDecision:
        return RiskDecision(approved=True, layer=layer, metadata=metadata)

    @staticmethod
    def reject(layer: str, reason: str, **metadata: Any) -> RiskDecision:
        return RiskDecision(approved=False, reason=reason, layer=layer, metadata=metadata)

    @staticmethod
    def modify(
        layer: str,
        signal: TradingSignal,
        reason: str = "",
        **metadata: Any,
    ) -> RiskDecision:
        return RiskDecision(
            approved=True,
            reason=reason,
            layer=layer,
            modified_signal=signal,
            metadata=metadata,
        )


__all__ = ["RiskDecision"]
