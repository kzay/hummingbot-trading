from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from controllers.ops_guard import GuardState


@dataclass(frozen=True)
class RuntimeRiskDecision:
    """Neutral risk outcome consumed by telemetry and execution gating."""

    risk_reasons: list[str]
    risk_hard_stop: bool
    daily_loss_pct: Decimal
    drawdown_pct: Decimal
    guard_state: GuardState


__all__ = ["RuntimeRiskDecision"]
