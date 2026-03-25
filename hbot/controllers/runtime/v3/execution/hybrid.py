"""Hybrid execution adapter — MM grid + directional bias switching.

When conviction is above the directional threshold, acts like
DirectionalExecutionAdapter on the signal side.  Below that but
above the bias threshold, uses MM grid with skewed sizing.
Below both thresholds, uses symmetric MM grid.
"""

from __future__ import annotations

from decimal import Decimal

from controllers.runtime.v3.execution.directional import DirectionalExecutionAdapter
from controllers.runtime.v3.execution.mm_grid import MMGridExecutionAdapter
from controllers.runtime.v3.orders import DeskAction, DeskOrder
from controllers.runtime.v3.signals import TradingSignal
from controllers.runtime.v3.types import MarketSnapshot, PositionSnapshot

_ZERO = Decimal("0")


class HybridExecutionAdapter:
    """Hybrid MM + directional adapter.

    Switches between MM grid and directional modes based on
    signal conviction thresholds.
    """

    def __init__(
        self,
        *,
        directional_threshold: Decimal = Decimal("0.85"),
        bias_threshold: Decimal = Decimal("0.65"),
        mm_adapter: MMGridExecutionAdapter | None = None,
        dir_adapter: DirectionalExecutionAdapter | None = None,
    ) -> None:
        self._directional_threshold = directional_threshold
        self._bias_threshold = bias_threshold
        self._mm = mm_adapter or MMGridExecutionAdapter()
        self._dir = dir_adapter or DirectionalExecutionAdapter()

    def translate(
        self,
        signal: TradingSignal,
        snapshot: MarketSnapshot,
    ) -> list[DeskOrder]:
        if signal.family == "no_trade" or signal.direction == "off":
            return []

        # High conviction: directional mode
        if signal.conviction >= self._directional_threshold:
            return self._dir.translate(signal, snapshot)

        # Medium conviction: skewed MM grid
        if signal.conviction >= self._bias_threshold:
            return self._mm.translate(signal, snapshot)

        # Low conviction: symmetric MM (treat as both sides)
        symmetric = TradingSignal(
            family="mm_grid",
            direction="both",
            conviction=signal.conviction,
            target_net_base_pct=signal.target_net_base_pct,
            levels=signal.levels,
            metadata=signal.metadata,
            reason=signal.reason,
        )
        return self._mm.translate(symmetric, snapshot)

    def manage_trailing(
        self,
        position: PositionSnapshot,
        signal: TradingSignal,
    ) -> list[DeskAction]:
        if signal.conviction >= self._directional_threshold:
            return self._dir.manage_trailing(position, signal)
        return []


__all__ = ["HybridExecutionAdapter"]
