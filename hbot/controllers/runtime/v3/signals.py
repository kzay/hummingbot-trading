"""Trading signal types for the v3 trading desk.

Strategies return TradingSignal from their evaluate() method.
All types are frozen dataclasses — immutable after creation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal


_ZERO = Decimal("0")


@dataclass(frozen=True)
class SignalLevel:
    """A single level in a multi-level signal (spread + size)."""

    side: Literal["buy", "sell"]
    spread_pct: Decimal
    size_quote: Decimal
    level_id: str = ""


@dataclass(frozen=True)
class TradingSignal:
    """Output of a strategy's evaluate() method.

    Describes *what* the strategy wants — the execution adapter
    translates this into concrete DeskOrder objects.
    """

    family: Literal["mm_grid", "directional", "hybrid", "no_trade"]
    direction: Literal["buy", "sell", "both", "off"]
    conviction: Decimal = _ZERO
    """Signal strength in [0, 1]."""

    target_net_base_pct: Decimal = _ZERO
    """Signed position target (negative = short bias)."""

    levels: tuple[SignalLevel, ...] = ()
    """Spread + size per level.  Empty for no_trade."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Strategy-specific telemetry values (flows to CSV/Redis)."""

    reason: str = ""
    """Human-readable explanation of the signal."""

    @staticmethod
    def no_trade(reason: str = "no_signal") -> TradingSignal:
        """Convenience factory for a no-trade signal."""
        return TradingSignal(
            family="no_trade",
            direction="off",
            conviction=_ZERO,
            reason=reason,
        )


# ── Telemetry schema ─────────────────────────────────────────────────

@dataclass(frozen=True)
class TelemetryField:
    """One column in a strategy's telemetry output."""

    name: str
    """CSV column / Redis key name."""

    key: str
    """Maps to TradingSignal.metadata[key]."""

    type: Literal["decimal", "int", "str", "bool"] = "decimal"
    default: Any = _ZERO


@dataclass(frozen=True)
class TelemetrySchema:
    """Typed declaration of strategy-specific telemetry fields."""

    fields: tuple[TelemetryField, ...] = ()

    @property
    def column_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def extract(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Extract telemetry values from signal metadata, applying defaults."""
        return {
            f.name: metadata.get(f.key, f.default)
            for f in self.fields
        }


__all__ = [
    "SignalLevel",
    "TelemetryField",
    "TelemetrySchema",
    "TradingSignal",
]
