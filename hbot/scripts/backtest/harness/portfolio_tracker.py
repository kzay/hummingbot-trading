"""Generic portfolio tracker for backtesting.

Maintains a multi-asset ledger with fee tracking and PnL accounting.
Strategy-agnostic — works with any strategy adapter output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List

from scripts.backtest.harness.fill_simulator import SimulatedFill
from services.common.utils import to_decimal


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state for reporting."""
    timestamp_s: float
    equity_quote: Decimal
    base_balance: Decimal
    quote_balance: Decimal
    base_pct: Decimal
    drawdown_pct: Decimal
    fill_count: int
    total_fees_quote: Decimal
    total_pnl_quote: Decimal


class PortfolioTracker:
    """Tracks balances, fills, fees, PnL, and drawdown during a backtest."""

    def __init__(
        self,
        initial_base: Decimal,
        initial_quote: Decimal,
    ):
        self.base_balance = initial_base
        self.quote_balance = initial_quote
        self._initial_equity: Decimal = Decimal("0")
        self._peak_equity: Decimal = Decimal("0")
        self.total_fees_quote: Decimal = Decimal("0")
        self.fill_count: int = 0
        self._snapshots: List[PortfolioSnapshot] = []

    def apply_fill(self, fill: SimulatedFill) -> None:
        """Update balances for a fill."""
        notional = fill.price * fill.amount
        if fill.side == "buy":
            self.base_balance += fill.amount
            self.quote_balance -= notional + fill.fee_quote
        else:
            self.base_balance -= fill.amount
            self.quote_balance += notional - fill.fee_quote
        self.total_fees_quote += fill.fee_quote
        self.fill_count += 1

    def snapshot(self, timestamp_s: float, mid_price: Decimal) -> PortfolioSnapshot:
        """Record and return a portfolio snapshot at *mid_price*."""
        equity = self.quote_balance + self.base_balance * mid_price
        if self._initial_equity == Decimal("0"):
            self._initial_equity = equity
        if equity > self._peak_equity:
            self._peak_equity = equity
        drawdown_pct = Decimal("0")
        if self._peak_equity > 0:
            drawdown_pct = max(Decimal("0"), (self._peak_equity - equity) / self._peak_equity)
        base_pct = (self.base_balance * mid_price) / equity if equity > 0 else Decimal("0")
        total_pnl = equity - self._initial_equity

        snap = PortfolioSnapshot(
            timestamp_s=timestamp_s,
            equity_quote=equity,
            base_balance=self.base_balance,
            quote_balance=self.quote_balance,
            base_pct=base_pct,
            drawdown_pct=drawdown_pct,
            fill_count=self.fill_count,
            total_fees_quote=self.total_fees_quote,
            total_pnl_quote=total_pnl,
        )
        self._snapshots.append(snap)
        return snap

    @property
    def snapshots(self) -> List[PortfolioSnapshot]:
        return list(self._snapshots)
