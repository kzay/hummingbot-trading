"""Protocol definitions for the v3 trading desk.

All major components are defined as protocols — concrete implementations
are injected via composition, not inheritance.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from controllers.runtime.v3.orders import DeskAction, DeskOrder
from controllers.runtime.v3.risk_types import RiskDecision
from controllers.runtime.v3.signals import TelemetrySchema, TradingSignal
from controllers.runtime.v3.types import MarketSnapshot, PositionSnapshot


# ── Strategy ─────────────────────────────────────────────────────────

@runtime_checkable
class StrategySignalSource(Protocol):
    """Contract that every strategy must satisfy.

    Implementations must be pure — no framework imports, no side effects.
    The evaluate() method receives a MarketSnapshot and returns a
    TradingSignal describing what the strategy wants.
    """

    def evaluate(self, snapshot: MarketSnapshot) -> TradingSignal:
        """Generate a trading signal from current market state."""
        ...

    def warmup_bars_required(self) -> int:
        """Number of historical bars needed before first evaluate() call."""
        ...

    def telemetry_schema(self) -> TelemetrySchema:
        """Declare strategy-specific telemetry fields."""
        ...


# ── Execution ────────────────────────────────────────────────────────

@runtime_checkable
class ExecutionAdapter(Protocol):
    """Translates trading signals into concrete desk orders.

    Separate from strategy logic — handles order type selection,
    barrier computation, grid construction, etc.
    """

    def translate(
        self,
        signal: TradingSignal,
        snapshot: MarketSnapshot,
    ) -> list[DeskOrder]:
        """Convert a signal into desk orders."""
        ...

    def manage_trailing(
        self,
        position: PositionSnapshot,
        signal: TradingSignal,
    ) -> list[DeskAction]:
        """Manage trailing stops and partial exits for open positions."""
        ...


# ── Risk ─────────────────────────────────────────────────────────────

@runtime_checkable
class RiskLayer(Protocol):
    """A single risk evaluation layer.

    Layers are composed by DeskRiskGate and evaluated in sequence:
    portfolio → bot → signal.
    """

    def evaluate(
        self,
        signal: TradingSignal,
        snapshot: MarketSnapshot,
    ) -> RiskDecision:
        """Evaluate the signal against this layer's risk rules."""
        ...


# ── Trading desk ─────────────────────────────────────────────────────

@runtime_checkable
class TradingDeskProtocol(Protocol):
    """Unified trading desk abstraction.

    Owns the tick loop: snapshot → signal → risk → execute → telemetry.
    Concrete implementations: LiveTradingDesk, BacktestTradingDesk.
    """

    def tick(self, now_ts: float) -> None:
        """Run one iteration of the tick loop."""
        ...

    def get_position(self) -> PositionSnapshot:
        """Current position state."""
        ...

    def submit_orders(self, orders: list[DeskOrder]) -> list[str]:
        """Submit orders, return list of order IDs."""
        ...

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a specific order. Returns True if cancelled."""
        ...

    def cancel_all(self) -> int:
        """Cancel all open orders. Returns count cancelled."""
        ...


__all__ = [
    "ExecutionAdapter",
    "RiskLayer",
    "StrategySignalSource",
    "TradingDeskProtocol",
]
