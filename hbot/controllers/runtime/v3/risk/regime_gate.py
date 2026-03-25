"""Regime-aware risk layer — enforces regime policy constraints on signals.

Slots into DeskRiskGate as an additional layer alongside portfolio, bot,
and signal gates.  Uses the RegimePolicy to check whether a signal's
strategy family is allowed in the current regime and to apply sizing
adjustments.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from controllers.ml.regime_policy import RegimeAction, RegimePolicy
from controllers.runtime.v3.risk_types import RiskDecision
from controllers.runtime.v3.signals import TradingSignal
from controllers.runtime.v3.types import MarketSnapshot

logger = logging.getLogger(__name__)


class RegimeRiskGate:
    """Risk layer that enforces regime-dependent trading constraints.

    Evaluates the current market regime from the snapshot and applies
    the corresponding ``RegimeAction`` rules:

    1. If trading is not allowed in this regime → reject.
    2. If the signal's strategy family is not allowed → reject.
    3. Apply sizing multiplier to the signal's levels.
    """

    def __init__(
        self,
        policy: RegimePolicy | None = None,
        enabled: bool = True,
    ) -> None:
        self._policy = policy or RegimePolicy()
        self._enabled = enabled

    def evaluate(
        self,
        signal: TradingSignal,
        snapshot: MarketSnapshot,
    ) -> RiskDecision:
        if not self._enabled:
            return RiskDecision.approve("regime")

        if signal.family == "no_trade":
            return RiskDecision.approve("regime")

        regime_name = snapshot.regime.name
        action = self._policy.get(regime_name)

        # Gate 1: trading allowed at all?
        if not action.trading_allowed:
            return RiskDecision.reject(
                "regime",
                "regime_trading_halted",
                regime=regime_name,
            )

        # Gate 2: strategy family allowed?
        if not self._policy.is_strategy_allowed(regime_name, signal.family):
            return RiskDecision.reject(
                "regime",
                "regime_strategy_blocked",
                regime=regime_name,
                family=signal.family,
                allowed=list(action.allowed_strategies),
            )

        # Gate 3: direction checks
        if signal.direction in ("buy", "sell") and not action.directional_allowed:
            return RiskDecision.reject(
                "regime",
                "regime_directional_blocked",
                regime=regime_name,
                direction=signal.direction,
            )

        # Sizing adjustment — reduce conviction/sizes by regime multiplier
        if action.sizing_mult < 1.0 and signal.levels:
            adjusted_conviction = Decimal(str(
                float(signal.conviction) * action.sizing_mult
            ))
            adjusted_levels = tuple(
                type(lvl)(
                    side=lvl.side,
                    spread_pct=lvl.spread_pct * Decimal(str(action.spread_mult)),
                    size_quote=lvl.size_quote * Decimal(str(action.sizing_mult)),
                    level_id=lvl.level_id,
                )
                for lvl in signal.levels
            )
            modified_signal = TradingSignal(
                family=signal.family,
                direction=signal.direction,
                conviction=adjusted_conviction,
                target_net_base_pct=signal.target_net_base_pct,
                levels=adjusted_levels,
                metadata={
                    **signal.metadata,
                    "regime_sizing_mult": action.sizing_mult,
                    "regime_spread_mult": action.spread_mult,
                },
                reason=signal.reason,
            )
            return RiskDecision.modify(
                "regime",
                modified_signal,
                reason="regime_sizing_applied",
                regime=regime_name,
                sizing_mult=action.sizing_mult,
                spread_mult=action.spread_mult,
            )

        return RiskDecision.approve("regime")


__all__ = ["RegimeRiskGate"]
