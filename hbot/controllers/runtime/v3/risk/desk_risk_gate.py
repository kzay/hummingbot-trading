"""Composed desk risk gate — evaluates all layers in sequence."""

from __future__ import annotations

from controllers.runtime.v3.protocols import RiskLayer
from controllers.runtime.v3.risk.bot_gate import BotRiskGate
from controllers.runtime.v3.risk.portfolio_gate import PortfolioRiskGate
from controllers.runtime.v3.risk.signal_gate import SignalRiskGate
from controllers.runtime.v3.risk_types import RiskDecision
from controllers.runtime.v3.signals import TradingSignal
from controllers.runtime.v3.types import MarketSnapshot


class DeskRiskGate:
    """Composes risk layers with short-circuit evaluation.

    Order: portfolio → bot → regime → signal.
    If any layer rejects, subsequent layers are skipped.
    If a layer modifies the signal (e.g. reduces sizing),
    subsequent layers see the modified signal.
    """

    def __init__(
        self,
        portfolio: PortfolioRiskGate | None = None,
        bot: BotRiskGate | None = None,
        signal: SignalRiskGate | None = None,
        regime: RiskLayer | None = None,
    ) -> None:
        self._layers: list[RiskLayer] = []
        if portfolio is not None:
            self._layers.append(portfolio)
        if bot is not None:
            self._layers.append(bot)
        if regime is not None:
            self._layers.append(regime)
        if signal is not None:
            self._layers.append(signal)

    def evaluate(
        self,
        signal: TradingSignal,
        snapshot: MarketSnapshot,
    ) -> RiskDecision:
        """Run all layers.  Short-circuit on rejection."""
        current_signal = signal
        last_decision = RiskDecision.approve("none")

        for layer in self._layers:
            decision = layer.evaluate(current_signal, snapshot)

            if not decision.approved:
                return decision

            # Layer may have modified the signal (e.g. reduced sizing)
            if decision.modified_signal is not None:
                current_signal = decision.modified_signal
                last_decision = decision
            else:
                last_decision = decision

        # If signal was modified by any layer, return the final modified version
        if current_signal is not signal:
            return RiskDecision.modify(
                "desk",
                current_signal,
                reason=last_decision.reason,
                **last_decision.metadata,
            )

        return RiskDecision.approve("desk")


__all__ = ["DeskRiskGate"]
