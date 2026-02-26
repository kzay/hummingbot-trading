"""Pure position accounting core for Paper Engine v2.

Inspired by NautilusTrader position.pyx accounting semantics.
Upstream reference: https://github.com/nautechsystems/nautilus_trader
(Licensed LGPLv3; attribution in hbot/third_party/nautilus_trader.LICENSE.txt)

This module is a dependency-free, pure-Python reimplementation of position
lifecycle accounting. It is intentionally kept separate from persistence,
event emission, and ledger logic so it can be unit-tested deterministically
against a table of scenarios.

Position state machine (signed quantity):
  FLAT (qty == 0)
    -> BUY  -> LONG (qty > 0)
    -> SELL -> SHORT (qty < 0)
  LONG (qty > 0)
    -> BUY  -> LONG (qty increases, avg_entry updated)
    -> SELL -> REDUCING (qty decreases, partial close, realized PnL generated)
           -> FLAT     (qty == 0, position closed, realized PnL generated)
           -> FLIP_SHORT (qty < 0 after crossing zero, flip realized + re-open)
  SHORT (qty < 0)
    -> SELL -> SHORT (qty more negative, avg_entry updated)
    -> BUY  -> REDUCING (qty less negative, partial close)
           -> FLAT
           -> FLIP_LONG (qty > 0, flip realized + re-open)

Accounting invariants (enforced by this module):
  - realized_pnl = pure price PnL only (no fees, no funding)
  - avg_entry price is VWAP over same-direction fills
  - On flip: realized PnL computed for close leg ONLY; re-open leg starts
    at fill_price with size = |overshoot|
  - fees and funding are tracked separately (caller's responsibility)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Tuple

_ZERO = Decimal("0")
_ONE = Decimal("1")
_EPS = Decimal("1e-10")


# ---------------------------------------------------------------------------
# Position side / transition enums
# ---------------------------------------------------------------------------

class PositionSide(str, Enum):
    FLAT = "flat"
    LONG = "long"
    SHORT = "short"


class FillTransition(str, Enum):
    """Result of applying a fill to a position."""
    OPEN = "open"           # flat → long or short
    ADD = "add"             # adding to existing direction
    REDUCE = "reduce"       # partial close
    CLOSE = "close"         # full close, now flat
    FLIP = "flip"           # close + re-open in opposite direction


# ---------------------------------------------------------------------------
# PositionState — pure immutable accounting snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PositionState:
    """Immutable snapshot of position accounting after a fill.

    These fields correspond 1:1 with PaperPosition but are stripped of
    timestamps and instrument references so the accounting function can be
    pure and trivially tested.
    """
    quantity: Decimal          # signed; 0 = flat
    avg_entry_price: Decimal
    realized_pnl: Decimal      # cumulative pure price PnL
    opened_at_ns: int


@dataclass(frozen=True)
class FillResult:
    """Output of apply_fill(). Carries the new state and metadata."""
    new_state: PositionState
    transition: FillTransition
    fill_realized_pnl: Decimal     # PnL realized BY THIS fill alone
    close_quantity: Decimal        # qty that was closed (0 if OPEN/ADD)
    open_quantity: Decimal         # qty that was newly opened (0 if CLOSE)

    @property
    def is_closing(self) -> bool:
        return self.transition in (
            FillTransition.REDUCE,
            FillTransition.CLOSE,
            FillTransition.FLIP,
        )


# ---------------------------------------------------------------------------
# Core accounting function
# ---------------------------------------------------------------------------

def apply_fill(
    old: PositionState,
    fill_side: str,      # "buy" or "sell"
    fill_qty: Decimal,
    fill_price: Decimal,
    now_ns: int = 0,
) -> FillResult:
    """Apply a single fill to a position and return the new state.

    This is the central accounting function. All callers (PaperPortfolio,
    replay engine, backtester) should funnel through here.

    Parameters
    ----------
    old:
        Existing position state before the fill.
    fill_side:
        "buy" or "sell".
    fill_qty:
        Positive magnitude of the fill (must be > 0).
    fill_price:
        Execution price (must be > 0).
    now_ns:
        Nanosecond timestamp used for opened_at_ns when opening a new position.

    Returns
    -------
    FillResult
        New position state and metadata for this fill.

    Accounting rules (Nautilus-aligned)
    ------------------------------------
    1. realized_pnl = pure price PnL only (no fees).
    2. avg_entry uses VWAP for same-direction accumulation.
    3. Flip: close_qty = |old_qty|, realize PnL, then open residual at fill_price.
    4. EPS-clamped flat detection (avoids float dust keeping positions alive).
    """
    if fill_qty <= _ZERO:
        # No-op fill — return old state unchanged.
        return FillResult(
            new_state=old,
            transition=FillTransition.OPEN if old.quantity == _ZERO else FillTransition.ADD,
            fill_realized_pnl=_ZERO,
            close_quantity=_ZERO,
            open_quantity=_ZERO,
        )

    fill_signed = fill_qty if fill_side == "buy" else -fill_qty
    old_qty = old.quantity
    new_qty_raw = old_qty + fill_signed

    # Clamp near-zero to exactly zero (dust avoidance)
    new_qty = _ZERO if abs(new_qty_raw) <= _EPS else new_qty_raw

    old_side = _side(old_qty)
    fill_dir = _side(fill_signed)
    is_closing = (old_side == PositionSide.LONG and fill_dir == PositionSide.SHORT) or (
        old_side == PositionSide.SHORT and fill_dir == PositionSide.LONG
    )

    realized_pnl = _ZERO
    close_qty = _ZERO
    open_qty = _ZERO
    new_avg_entry = old.avg_entry_price
    opened_at_ns = old.opened_at_ns

    if old_side == PositionSide.FLAT:
        # Opening a new position from flat.
        transition = FillTransition.OPEN
        new_avg_entry = fill_price
        open_qty = fill_qty
        opened_at_ns = now_ns if opened_at_ns == 0 else opened_at_ns

    elif not is_closing:
        # Adding to existing direction (same side as current position).
        transition = FillTransition.ADD
        abs_old = abs(old_qty)
        abs_new = abs(new_qty) if new_qty != _ZERO else _ZERO
        if abs_new > _ZERO:
            old_cost = abs_old * old.avg_entry_price
            add_cost = fill_qty * fill_price
            new_avg_entry = (old_cost + add_cost) / abs_new
        open_qty = fill_qty

    else:
        # Closing or flipping.
        close_qty = min(fill_qty, abs(old_qty))
        direction = _ONE if old_qty > _ZERO else Decimal("-1")
        realized_pnl = (fill_price - old.avg_entry_price) * close_qty * direction

        residual = fill_qty - close_qty  # > 0 on flip, 0 on reduce/close

        if abs(new_qty) <= _EPS:
            # Exact close or dust-clamped close.
            transition = FillTransition.CLOSE
            new_qty = _ZERO
            new_avg_entry = _ZERO
            opened_at_ns = 0

        elif residual > _EPS and _side(new_qty) != old_side:
            # Flip: open in opposite direction with residual qty.
            transition = FillTransition.FLIP
            new_avg_entry = fill_price
            open_qty = residual
            opened_at_ns = now_ns

        else:
            # Partial close (reduce).
            transition = FillTransition.REDUCE
            # avg_entry unchanged for remaining direction.
            open_qty = _ZERO

    new_state = PositionState(
        quantity=new_qty,
        avg_entry_price=new_avg_entry,
        realized_pnl=old.realized_pnl + realized_pnl,
        opened_at_ns=opened_at_ns,
    )
    return FillResult(
        new_state=new_state,
        transition=transition,
        fill_realized_pnl=realized_pnl,
        close_quantity=close_qty,
        open_quantity=open_qty,
    )


def position_side(quantity: Decimal) -> PositionSide:
    """Public helper: classify a signed quantity as LONG, SHORT, or FLAT."""
    return _side(quantity)


# ---------------------------------------------------------------------------
# VWAP helper (for callers doing multi-leg avg price)
# ---------------------------------------------------------------------------

def vwap_avg_entry(
    old_qty: Decimal,
    old_avg: Decimal,
    add_qty: Decimal,
    add_price: Decimal,
) -> Decimal:
    """Return the VWAP-weighted average entry price after adding to a position.

    Both old_qty and add_qty should be positive magnitudes.
    """
    total = old_qty + add_qty
    if total <= _ZERO:
        return add_price
    return (old_qty * old_avg + add_qty * add_price) / total


# ---------------------------------------------------------------------------
# Unrealized PnL helper
# ---------------------------------------------------------------------------

def unrealized_pnl(
    quantity: Decimal,
    avg_entry_price: Decimal,
    mark_price: Decimal,
) -> Decimal:
    """Mark-to-market unrealized PnL for a position.

    Returns 0 if flat or prices are non-positive.
    """
    if quantity == _ZERO or avg_entry_price <= _ZERO or mark_price <= _ZERO:
        return _ZERO
    direction = _ONE if quantity > _ZERO else Decimal("-1")
    return (mark_price - avg_entry_price) * abs(quantity) * direction


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _side(qty: Decimal) -> PositionSide:
    if qty > _ZERO:
        return PositionSide.LONG
    if qty < _ZERO:
        return PositionSide.SHORT
    return PositionSide.FLAT
