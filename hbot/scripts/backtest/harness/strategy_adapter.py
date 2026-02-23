"""Strategy adapter protocol for the generic backtest harness.

Each strategy type implements a thin adapter that converts bar data into
order intents.  Adding a new strategy = implementing ``process_bar()``.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Protocol

from scripts.backtest.harness.data_provider import BarData


@dataclass
class OrderIntent:
    """A single order intent produced by a strategy adapter."""
    side: str
    price: Decimal
    amount: Decimal
    order_type: str
    level_id: str
    expires_at_ms: int = 0


@dataclass
class BacktestState:
    """Mutable state carried across bars during a backtest run."""
    equity_quote: Decimal = Decimal("0")
    base_balance: Decimal = Decimal("0")
    quote_balance: Decimal = Decimal("0")
    base_pct: Decimal = Decimal("0")
    bar_index: int = 0
    strategy_state: Dict[str, object] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.strategy_state is None:
            self.strategy_state = {}


class StrategyAdapter(Protocol):
    """Protocol for strategy-specific bar processing.

    Implementations receive a bar and the current backtest state, and return
    order intents.  All fill simulation, portfolio tracking, and reporting
    are handled by the generic harness.
    """

    @property
    def strategy_name(self) -> str:
        """Unique strategy identifier (e.g. ``epp_v2_4``)."""
        ...

    def process_bar(self, bar: BarData, state: BacktestState) -> List[OrderIntent]:
        """Process one bar and return order intents."""
        ...
