"""Regime-to-action policy: maps regime predictions to trading constraints.

This module provides a clean, configurable mapping layer between regime
classifications and concrete trading behavior.  Instead of scattering
regime-specific logic across strategy code, all regime-dependent rules
live here as data.

Usage::

    policy = RegimePolicy()  # uses built-in defaults
    action = policy.get(regime_name)
    if not action.trading_allowed:
        return  # skip this tick
    size *= action.sizing_mult
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegimeAction:
    """Trading constraints for a single regime."""

    regime: str

    # Strategy selection
    allowed_strategies: tuple[str, ...] = ("mm_grid", "directional", "hybrid")
    disallowed_strategies: tuple[str, ...] = ()

    # Position sizing
    sizing_mult: float = 1.0
    max_leverage: float = 5.0
    max_exposure_pct: float = 1.0

    # Risk limits
    stop_loss_style: str = "atr"        # "atr" | "fixed_pct" | "trailing"
    stop_loss_mult: float = 2.0         # ATR multiplier for SL
    take_profit_style: str = "atr"      # "atr" | "fixed_pct" | "trailing"
    take_profit_mult: float = 3.0       # ATR multiplier for TP
    max_concurrent_positions: int = 5

    # Behavior flags
    trading_allowed: bool = True
    directional_allowed: bool = True
    mean_reversion_allowed: bool = True
    breakout_allowed: bool = True

    # Spread / quoting
    spread_mult: float = 1.0           # multiplier on base spread

    # Descriptive
    description: str = ""


# ---------------------------------------------------------------------------
# Built-in regime action defaults
# ---------------------------------------------------------------------------

_DEFAULT_ACTIONS: dict[str, RegimeAction] = {
    "neutral_low_vol": RegimeAction(
        regime="neutral_low_vol",
        sizing_mult=1.0,
        max_leverage=5.0,
        stop_loss_mult=2.0,
        take_profit_mult=3.0,
        spread_mult=1.0,
        description="Low volatility, normal conditions — full operation",
    ),
    "neutral_high_vol": RegimeAction(
        regime="neutral_high_vol",
        sizing_mult=0.6,
        max_leverage=3.0,
        stop_loss_mult=2.5,
        take_profit_mult=2.5,
        spread_mult=1.5,
        breakout_allowed=False,
        description="Elevated volatility, no trend — reduce size, widen spreads, mean reversion only",
    ),
    "up": RegimeAction(
        regime="up",
        allowed_strategies=("directional", "hybrid"),
        sizing_mult=0.8,
        max_leverage=4.0,
        stop_loss_mult=2.0,
        take_profit_mult=4.0,
        spread_mult=1.2,
        mean_reversion_allowed=False,
        description="Uptrend — favor longs, pullback continuation, no mean reversion shorts",
    ),
    "down": RegimeAction(
        regime="down",
        allowed_strategies=("directional", "hybrid"),
        sizing_mult=0.8,
        max_leverage=4.0,
        stop_loss_mult=2.0,
        take_profit_mult=4.0,
        spread_mult=1.2,
        mean_reversion_allowed=False,
        description="Downtrend — favor shorts, pullback continuation, no mean reversion longs",
    ),
    "high_vol_shock": RegimeAction(
        regime="high_vol_shock",
        allowed_strategies=("mm_grid",),
        sizing_mult=0.3,
        max_leverage=1.0,
        max_exposure_pct=0.3,
        stop_loss_mult=3.0,
        take_profit_mult=2.0,
        spread_mult=3.0,
        directional_allowed=False,
        breakout_allowed=False,
        max_concurrent_positions=2,
        description="Extreme volatility / shock — minimal size, wide spreads, defensive only",
    ),
}

# Fallback for unknown regime names
_SAFE_FALLBACK = RegimeAction(
    regime="unknown",
    sizing_mult=0.5,
    max_leverage=2.0,
    spread_mult=2.0,
    description="Unknown regime — conservative fallback",
)


class RegimePolicy:
    """Configurable regime → action mapping.

    Can be loaded from a JSON file or constructed with custom actions.
    """

    def __init__(
        self,
        actions: dict[str, RegimeAction] | None = None,
        fallback: RegimeAction | None = None,
    ) -> None:
        self._actions = dict(actions or _DEFAULT_ACTIONS)
        self._fallback = fallback or _SAFE_FALLBACK

    def get(self, regime: str) -> RegimeAction:
        """Get the action policy for a regime name."""
        action = self._actions.get(regime)
        if action is None:
            logger.warning("No regime policy for '%s', using fallback", regime)
            return self._fallback
        return action

    def is_strategy_allowed(self, regime: str, strategy_family: str) -> bool:
        """Check if a strategy execution family is permitted in this regime."""
        action = self.get(regime)
        if not action.trading_allowed:
            return False
        if strategy_family in action.disallowed_strategies:
            return False
        if action.allowed_strategies and strategy_family not in action.allowed_strategies:
            return False
        return True

    def effective_sizing(self, regime: str, base_size: float) -> float:
        """Apply regime sizing multiplier to a base position size."""
        action = self.get(regime)
        return base_size * action.sizing_mult

    @property
    def regimes(self) -> list[str]:
        """List of all configured regime names."""
        return list(self._actions.keys())

    # ── Serialization ─────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (for JSON export)."""
        import dataclasses
        return {
            name: dataclasses.asdict(action)
            for name, action in self._actions.items()
        }

    @classmethod
    def from_json(cls, path: str | Path) -> "RegimePolicy":
        """Load regime policy from a JSON config file.

        Expected format::

            {
                "neutral_low_vol": {
                    "sizing_mult": 1.0,
                    "max_leverage": 5.0,
                    ...
                },
                ...
            }
        """
        raw = json.loads(Path(path).read_text())
        actions: dict[str, RegimeAction] = {}
        for regime_name, params in raw.items():
            # Convert list values to tuples for frozen dataclass
            for key in ("allowed_strategies", "disallowed_strategies"):
                if key in params and isinstance(params[key], list):
                    params[key] = tuple(params[key])
            actions[regime_name] = RegimeAction(regime=regime_name, **params)
        return cls(actions=actions)


__all__ = ["RegimeAction", "RegimePolicy"]
