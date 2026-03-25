"""Order and action types for the v3 trading desk.

ExecutionAdapters produce DeskOrder objects.  The TradingDesk also
creates DeskAction objects for lifecycle management (cancel, close, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Union


_ZERO = Decimal("0")


# ── Desk orders ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class DeskOrder:
    """A concrete order instruction for the trading desk."""

    side: Literal["buy", "sell"]
    order_type: Literal["limit", "market"]
    price: Decimal
    amount_quote: Decimal
    level_id: str = ""
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    time_limit_s: int | None = None


# ── Desk actions (typed union) ───────────────────────────────────────

@dataclass(frozen=True)
class SubmitOrder:
    """Submit a new order to the exchange."""

    action: Literal["submit"] = "submit"
    order: DeskOrder = DeskOrder(side="buy", order_type="limit", price=_ZERO, amount_quote=_ZERO)


@dataclass(frozen=True)
class CancelOrder:
    """Cancel an existing order."""

    action: Literal["cancel"] = "cancel"
    level_id: str = ""
    order_id: str = ""


@dataclass(frozen=True)
class ModifyOrder:
    """Modify an existing order (cancel + replace)."""

    action: Literal["modify"] = "modify"
    level_id: str = ""
    order_id: str = ""
    new_price: Decimal = _ZERO
    new_amount_quote: Decimal = _ZERO


@dataclass(frozen=True)
class ClosePosition:
    """Close the entire position at market."""

    action: Literal["close_position"] = "close_position"
    reason: str = ""


@dataclass(frozen=True)
class PartialReduce:
    """Reduce position by a fraction."""

    action: Literal["partial_reduce"] = "partial_reduce"
    reduce_ratio: Decimal = _ZERO
    """Fraction of current position to close (e.g. 0.33 = 1/3)."""
    reason: str = ""


DeskAction = Union[SubmitOrder, CancelOrder, ModifyOrder, ClosePosition, PartialReduce]
"""Typed union of all desk actions."""


__all__ = [
    "CancelOrder",
    "ClosePosition",
    "DeskAction",
    "DeskOrder",
    "ModifyOrder",
    "PartialReduce",
    "SubmitOrder",
]
