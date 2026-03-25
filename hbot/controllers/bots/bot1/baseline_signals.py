"""Bot1 Baseline — pure signal module for market-making.

Bot1 is a two-sided market maker that relies on the kernel's edge gate
and selective quoting. The signal logic is simple: evaluate the current
spread/edge state and determine the quoting mode.

No framework imports — only standard library and v3 types.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from controllers.runtime.v3.signals import (
    SignalLevel,
    TelemetryField,
    TelemetrySchema,
    TradingSignal,
)
from controllers.runtime.v3.types import MarketSnapshot

_ZERO = Decimal("0")


@dataclass
class BaselineConfig:
    """Configuration for the baseline MM strategy."""

    min_spread_pct: Decimal = Decimal("0.001")
    levels: int = 3
    quote_size_pct: Decimal = Decimal("0.10")
    edge_gate_enabled: bool = True


class BaselineSignalSource:
    """Bot1 baseline market-making signal source.

    Evaluates market state and produces an MM grid signal.
    The kernel's edge gate and selective quoting (now in DeskRiskGate)
    handle the actual gating — this module just builds the grid.
    """

    def __init__(self, config: BaselineConfig | None = None) -> None:
        self._cfg = config or BaselineConfig()

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        """Generate an MM grid signal from current market state."""
        mid = snapshot.mid
        if mid <= _ZERO:
            return TradingSignal.no_trade("no_mid_price")

        cfg = self._cfg
        regime = snapshot.regime

        # Use regime-specific spread if available, else config default
        spread_min = regime.spread_min if regime.spread_min > _ZERO else cfg.min_spread_pct
        spread_max = regime.spread_max if regime.spread_max > _ZERO else spread_min * 2
        levels_count = min(cfg.levels, regime.levels_max) if regime.levels_max > 0 else cfg.levels

        # Determine direction from regime one_sided setting
        one_sided = regime.one_sided
        if one_sided == "buy_only":
            direction = "buy"
        elif one_sided == "sell_only":
            direction = "sell"
        else:
            direction = "both"

        # Build grid levels
        levels = _build_grid_levels(
            direction=direction,
            levels_count=levels_count,
            spread_min=spread_min,
            spread_max=spread_max,
            total_quote=mid * cfg.quote_size_pct,
        )

        if not levels:
            return TradingSignal.no_trade("no_levels_generated")

        # Conviction based on indicator availability and regime stability
        bars = snapshot.indicators.bars_available
        conviction = Decimal("0.5") if bars < 100 else Decimal("0.8")

        return TradingSignal(
            family="mm_grid",
            direction=direction,
            conviction=conviction,
            target_net_base_pct=regime.target_base_pct,
            levels=tuple(levels),
            metadata={
                "gate_state": "active",
                "regime": regime.name,
                "spread_min": spread_min,
                "spread_max": spread_max,
                "levels_count": levels_count,
                "one_sided": one_sided,
            },
            reason=f"mm_grid_{regime.name}",
        )

    def warmup_bars_required(self) -> int:
        return 50  # Bot1 needs minimal warmup — EMA/ATR for regime detection

    def telemetry_schema(self) -> TelemetrySchema:
        return TelemetrySchema(fields=(
            TelemetryField(name="bot1_gate_state", key="gate_state", type="str", default="n/a"),
            TelemetryField(name="bot1_regime", key="regime", type="str", default="neutral_low_vol"),
            TelemetryField(name="bot1_spread_min", key="spread_min", type="decimal", default=_ZERO),
            TelemetryField(name="bot1_levels_count", key="levels_count", type="int", default=0),
            TelemetryField(name="bot1_one_sided", key="one_sided", type="str", default="off"),
        ))


def _build_grid_levels(
    *,
    direction: str,
    levels_count: int,
    spread_min: Decimal,
    spread_max: Decimal,
    total_quote: Decimal,
) -> list[SignalLevel]:
    """Build symmetric or one-sided grid levels."""
    if levels_count <= 0 or total_quote <= _ZERO:
        return []

    spread_step = (spread_max - spread_min) / max(1, levels_count - 1) if levels_count > 1 else _ZERO
    size_per_level = total_quote / Decimal(str(levels_count))

    levels: list[SignalLevel] = []
    sides = []
    if direction in ("both", "buy"):
        sides.append("buy")
    if direction in ("both", "sell"):
        sides.append("sell")

    for side in sides:
        for i in range(levels_count):
            spread = spread_min + spread_step * i
            levels.append(SignalLevel(
                side=side,
                spread_pct=spread,
                size_quote=size_per_level,
                level_id=f"b1_{side[0]}{i}",
            ))

    return levels


__all__ = ["BaselineConfig", "BaselineSignalSource"]
