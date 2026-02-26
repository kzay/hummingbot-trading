"""Core domain types for Paper Engine v2.

All types are pure Python with no Hummingbot dependency.
Design follows NautilusTrader conventions:
- Realized PnL is pure price PnL only (fees tracked separately).
- Margin model: LeveragedMarginModel (notional / leverage * ratio).
- Available balance clamped to zero on over-margin (graceful degradation).
"""
from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from enum import Enum
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")
_EPS = Decimal("1e-10")


# ---------------------------------------------------------------------------
# Identifier
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InstrumentId:
    """Unique identifier for a tradable instrument on a specific venue."""

    venue: str            # "bitget" | "binance" | "bybit" | "okx"
    trading_pair: str     # "BTC-USDT"
    instrument_type: str  # "spot" | "perp" | "future"

    @property
    def base_asset(self) -> str:
        return self.trading_pair.split("-")[0]

    @property
    def quote_asset(self) -> str:
        parts = self.trading_pair.split("-")
        return parts[1] if len(parts) > 1 else "USDT"

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.trading_pair}:{self.instrument_type}"

    @property
    def is_perp(self) -> bool:
        return self.instrument_type == "perp"

    def __str__(self) -> str:
        return self.key


# ---------------------------------------------------------------------------
# Instrument specification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InstrumentSpec:
    """Exchange-defined trading rules for an instrument.

    Carries precision, order limits, fee defaults, and margin ratios.
    Margin model follows NautilusTrader's LeveragedMarginModel:
      initial_margin = (notional / leverage) * margin_init_ratio
    """

    instrument_id: InstrumentId
    # Precision
    price_precision: int
    size_precision: int
    price_increment: Decimal   # min tick size
    size_increment: Decimal    # min lot size
    # Order limits
    min_quantity: Decimal
    min_notional: Decimal      # min order value in quote
    max_quantity: Decimal
    # Default fees (may be overridden by FeeModel)
    maker_fee_rate: Decimal    # e.g. 0.0002
    taker_fee_rate: Decimal    # e.g. 0.0006
    # Margin (perps only; 0 for spot)
    margin_init: Decimal       # initial margin ratio (e.g. 0.10 for 10x max)
    margin_maint: Decimal      # maintenance margin ratio (e.g. 0.05)
    leverage_max: int
    # Funding (perps only; 0 for spot)
    funding_interval_s: int    # seconds between funding; 28800 = 8h

    # -- Quantization -------------------------------------------------------

    def quantize_price(self, price: Decimal, side: str) -> Decimal:
        """Round price to valid tick. 'buy' rounds down, 'sell' rounds up."""
        if self.price_increment <= _ZERO:
            return price
        rounding = ROUND_DOWN if side == "buy" else ROUND_UP
        steps = (price / self.price_increment).to_integral_value(rounding=rounding)
        return max(self.price_increment, steps * self.price_increment)

    def quantize_size(self, size: Decimal) -> Decimal:
        """Round size down to valid lot, clamped to min_quantity."""
        if self.size_increment <= _ZERO:
            return size
        steps = (size / self.size_increment).to_integral_value(rounding=ROUND_DOWN)
        return max(self.min_quantity, steps * self.size_increment)

    def validate_order(self, price: Decimal, quantity: Decimal) -> Optional[str]:
        """Return rejection reason string or None if valid."""
        if quantity < self.min_quantity:
            return f"qty {quantity} < min {self.min_quantity}"
        if quantity > self.max_quantity:
            return f"qty {quantity} > max {self.max_quantity}"
        notional = price * quantity
        if notional < self.min_notional:
            return f"notional {notional:.4f} < min {self.min_notional}"
        return None

    # -- Margin (LeveragedMarginModel -- Nautilus default) ------------------

    def compute_margin_init(self, quantity: Decimal, price: Decimal, leverage: int) -> Decimal:
        """Initial margin = (notional / leverage) * margin_init_ratio."""
        if not self.instrument_id.is_perp or leverage <= 0 or self.margin_init <= _ZERO:
            return _ZERO
        notional = quantity * price
        return (notional / Decimal(leverage)) * self.margin_init

    def compute_margin_maint(self, quantity: Decimal, price: Decimal, leverage: int) -> Decimal:
        """Maintenance margin = (notional / leverage) * margin_maint_ratio."""
        if not self.instrument_id.is_perp or leverage <= 0 or self.margin_maint <= _ZERO:
            return _ZERO
        notional = quantity * price
        return (notional / Decimal(leverage)) * self.margin_maint

    # -- Factory methods ----------------------------------------------------

    @classmethod
    def from_hb_trading_rule(
        cls,
        instrument_id: InstrumentId,
        rule: Any,
        fee_profile: Optional[Dict[str, str]] = None,
    ) -> "InstrumentSpec":
        """Build from a Hummingbot connector trading_rules entry."""
        def _d(attr: str, default: str = "0") -> Decimal:
            v = getattr(rule, attr, None)
            try:
                return Decimal(str(v)) if v is not None else Decimal(default)
            except Exception:
                return Decimal(default)

        maker = Decimal(fee_profile["maker"]) if fee_profile and "maker" in fee_profile else Decimal("0.0002")
        taker = Decimal(fee_profile["taker"]) if fee_profile and "taker" in fee_profile else Decimal("0.0006")

        price_inc = _d("min_price_increment")
        if price_inc <= _ZERO:
            price_inc = _d("min_price_tick_size")
        if price_inc <= _ZERO:
            price_inc = Decimal("0.01")

        size_inc = _d("min_base_amount_increment")
        if size_inc <= _ZERO:
            size_inc = _d("min_order_size_increment")
        if size_inc <= _ZERO:
            size_inc = Decimal("0.0001")

        min_qty = _d("min_order_size")
        if min_qty <= _ZERO:
            min_qty = _d("min_base_amount")
        if min_qty <= _ZERO:
            min_qty = size_inc

        min_notional = _d("min_notional_size")
        if min_notional <= _ZERO:
            min_notional = _d("min_notional")
        if min_notional <= _ZERO:
            min_notional = _d("min_order_value")
        if min_notional <= _ZERO:
            min_notional = Decimal("1")

        max_qty = _d("max_order_size")
        if max_qty <= _ZERO:
            max_qty = Decimal("1000000")

        return cls(
            instrument_id=instrument_id,
            price_precision=int(getattr(rule, "price_precision", 2) or 2),
            size_precision=int(getattr(rule, "quantity_precision", 4) or 4),
            price_increment=price_inc,
            size_increment=size_inc,
            min_quantity=min_qty,
            min_notional=min_notional,
            max_quantity=max_qty,
            maker_fee_rate=maker,
            taker_fee_rate=taker,
            margin_init=Decimal("0.10"),
            margin_maint=Decimal("0.05"),
            leverage_max=20,
            funding_interval_s=28800 if instrument_id.is_perp else 0,
        )

    @classmethod
    def spot_usdt(cls, venue: str, pair: str) -> "InstrumentSpec":
        """Generic USDT spot instrument with conservative defaults."""
        iid = InstrumentId(venue=venue, trading_pair=pair, instrument_type="spot")
        return cls(
            instrument_id=iid,
            price_precision=2, size_precision=4,
            price_increment=Decimal("0.01"), size_increment=Decimal("0.0001"),
            min_quantity=Decimal("0.0001"), min_notional=Decimal("1"),
            max_quantity=Decimal("10000"),
            maker_fee_rate=Decimal("0.001"), taker_fee_rate=Decimal("0.001"),
            margin_init=_ZERO, margin_maint=_ZERO, leverage_max=1, funding_interval_s=0,
        )

    @classmethod
    def perp_usdt(cls, venue: str, pair: str, leverage_max: int = 20) -> "InstrumentSpec":
        """Generic USDT perp instrument with conservative defaults."""
        iid = InstrumentId(venue=venue, trading_pair=pair, instrument_type="perp")
        return cls(
            instrument_id=iid,
            price_precision=2, size_precision=4,
            price_increment=Decimal("0.01"), size_increment=Decimal("0.001"),
            min_quantity=Decimal("0.001"), min_notional=Decimal("5"),
            max_quantity=Decimal("100"),
            maker_fee_rate=Decimal("0.0002"), taker_fee_rate=Decimal("0.0006"),
            margin_init=Decimal("0.10"), margin_maint=Decimal("0.05"),
            leverage_max=leverage_max, funding_interval_s=28800,
        )


# ---------------------------------------------------------------------------
# Order types
# ---------------------------------------------------------------------------

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

    def opposite(self) -> "OrderSide":
        return OrderSide.SELL if self == OrderSide.BUY else OrderSide.BUY


class PaperOrderType(str, Enum):
    LIMIT = "limit"
    LIMIT_MAKER = "limit_maker"
    MARKET = "market"


class OrderStatus(str, Enum):
    PENDING_SUBMIT = "pending_submit"  # in latency queue
    OPEN = "open"
    PARTIALLY_FILLED = "partial"
    FILLED = "filled"        # terminal
    CANCELED = "canceled"    # terminal
    REJECTED = "rejected"    # terminal


# Allowed state transitions (Nautilus-style explicit state machine).
# Any transition not in this map is invalid.
_ORDER_TRANSITIONS: Dict[OrderStatus, tuple] = {
    OrderStatus.PENDING_SUBMIT: (OrderStatus.OPEN, OrderStatus.CANCELED, OrderStatus.REJECTED),
    OrderStatus.OPEN: (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED),
    OrderStatus.PARTIALLY_FILLED: (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELED),
    # Terminal states: no outgoing transitions
    OrderStatus.FILLED: (),
    OrderStatus.CANCELED: (),
    OrderStatus.REJECTED: (),
}


def order_status_transition(current: OrderStatus, next_status: OrderStatus) -> OrderStatus:
    """Apply a validated state transition.

    Raises ValueError on invalid transition; returns next_status if valid.
    Callers that need defensive (non-raising) behavior should catch ValueError.
    """
    allowed = _ORDER_TRANSITIONS.get(current, ())
    if next_status not in allowed:
        raise ValueError(
            f"Invalid order state transition: {current!r} -> {next_status!r}. "
            f"Allowed: {[s.value for s in allowed]}"
        )
    return next_status


@dataclass
class PaperOrder:
    order_id: str
    instrument_id: InstrumentId
    side: OrderSide
    order_type: PaperOrderType
    price: Decimal
    quantity: Decimal
    status: OrderStatus
    created_at_ns: int
    updated_at_ns: int
    filled_quantity: Decimal = field(default_factory=lambda: Decimal("0"))
    filled_notional: Decimal = field(default_factory=lambda: Decimal("0"))
    cumulative_fee: Decimal = field(default_factory=lambda: Decimal("0"))
    fill_count: int = 0
    max_fills: int = 8
    crossed_at_creation: bool = False
    source_bot: str = ""
    reject_reason: str = ""
    # Internal: set by engine at acceptance time for release on fill/cancel
    _reserved_asset: str = field(default="", repr=False)
    _reserved_amount: Decimal = field(default_factory=lambda: Decimal("0"), repr=False)

    @property
    def remaining_quantity(self) -> Decimal:
        return max(_ZERO, self.quantity - self.filled_quantity)

    @property
    def avg_fill_price(self) -> Decimal:
        if self.filled_quantity <= _ZERO:
            return self.price
        return self.filled_notional / self.filled_quantity

    @property
    def is_terminal(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED)

    @property
    def is_open(self) -> bool:
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

@dataclass
class PaperPosition:
    """Open or flat position for one instrument.

    realized_pnl is PURE price PnL only (no fees deducted).
    total_fees_paid tracks fees separately, matching Nautilus convention.
    Net P&L = realized_pnl + unrealized_pnl - total_fees_paid - funding_paid.
    """

    instrument_id: InstrumentId
    quantity: Decimal           # signed: >0 long, <0 short, 0 flat
    avg_entry_price: Decimal
    realized_pnl: Decimal       # pure price PnL, no fees
    unrealized_pnl: Decimal     # mark-to-market, updated on tick
    total_fees_paid: Decimal    # separate from PnL
    funding_paid: Decimal       # perps only
    opened_at_ns: int
    last_fill_at_ns: int

    @property
    def side(self) -> str:
        if self.quantity > _ZERO:
            return "long"
        if self.quantity < _ZERO:
            return "short"
        return "flat"

    @property
    def abs_quantity(self) -> Decimal:
        return abs(self.quantity)

    @property
    def net_pnl(self) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl - self.total_fees_paid - self.funding_paid

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrument_id": self.instrument_id.key,
            "quantity": str(self.quantity),
            "avg_entry_price": str(self.avg_entry_price),
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": str(self.unrealized_pnl),
            "total_fees_paid": str(self.total_fees_paid),
            "funding_paid": str(self.funding_paid),
            "opened_at_ns": self.opened_at_ns,
            "last_fill_at_ns": self.last_fill_at_ns,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any], instrument_id: InstrumentId) -> "PaperPosition":
        return cls(
            instrument_id=instrument_id,
            quantity=Decimal(d["quantity"]),
            avg_entry_price=Decimal(d["avg_entry_price"]),
            realized_pnl=Decimal(d["realized_pnl"]),
            unrealized_pnl=Decimal(d["unrealized_pnl"]),
            total_fees_paid=Decimal(d["total_fees_paid"]),
            funding_paid=Decimal(d["funding_paid"]),
            opened_at_ns=int(d["opened_at_ns"]),
            last_fill_at_ns=int(d["last_fill_at_ns"]),
        )

    @classmethod
    def flat(cls, instrument_id: InstrumentId) -> "PaperPosition":
        return cls(
            instrument_id=instrument_id, quantity=_ZERO,
            avg_entry_price=_ZERO, realized_pnl=_ZERO,
            unrealized_pnl=_ZERO, total_fees_paid=_ZERO,
            funding_paid=_ZERO, opened_at_ns=0, last_fill_at_ns=0,
        )


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class OrderBookSnapshot:
    instrument_id: InstrumentId
    bids: Tuple[BookLevel, ...]   # best (highest) first
    asks: Tuple[BookLevel, ...]   # best (lowest) first
    timestamp_ns: int

    @property
    def best_bid(self) -> Optional[BookLevel]:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[BookLevel]:
        return self.asks[0] if self.asks else None

    @property
    def mid_price(self) -> Optional[Decimal]:
        bb, ba = self.best_bid, self.best_ask
        if bb and ba:
            return (bb.price + ba.price) / _TWO
        return None

    @property
    def spread(self) -> Optional[Decimal]:
        bb, ba = self.best_bid, self.best_ask
        if bb and ba and ba.price > bb.price:
            return ba.price - bb.price
        return None

    @property
    def spread_pct(self) -> Optional[Decimal]:
        mid = self.mid_price
        sp = self.spread
        if mid and sp and mid > _ZERO:
            return sp / mid
        return None

    def is_stale(self, now_ns: int, max_age_ns: int) -> bool:
        return (now_ns - self.timestamp_ns) > max_age_ns


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


def _event_to_dict(event: Any) -> Dict[str, Any]:
    """Serialize an EngineEvent to a JSON-safe dict."""
    result = {}
    for f in dataclasses.fields(event):
        v = getattr(event, f.name)
        if isinstance(v, Decimal):
            result[f.name] = str(v)
        elif isinstance(v, InstrumentId):
            result[f.name] = v.key
        elif isinstance(v, PaperPosition):
            result[f.name] = v.to_dict()
        elif isinstance(v, Enum):
            result[f.name] = v.value
        else:
            result[f.name] = v
    result["_type"] = type(event).__name__
    return result


@dataclass(frozen=True)
class EngineEvent:
    event_id: str
    timestamp_ns: int
    instrument_id: InstrumentId

    def to_dict(self) -> Dict[str, Any]:
        return _event_to_dict(self)


@dataclass(frozen=True)
class OrderAccepted(EngineEvent):
    order_id: str
    side: str
    order_type: str
    price: Decimal
    quantity: Decimal
    source_bot: str


@dataclass(frozen=True)
class OrderRejected(EngineEvent):
    order_id: str
    reason: str
    source_bot: str


@dataclass(frozen=True)
class OrderFilled(EngineEvent):
    order_id: str
    fill_price: Decimal
    fill_quantity: Decimal
    fee: Decimal                 # tracked separately from PnL
    is_maker: bool
    remaining_quantity: Decimal
    source_bot: str


@dataclass(frozen=True)
class OrderCanceled(EngineEvent):
    order_id: str
    source_bot: str


@dataclass(frozen=True)
class PositionChanged(EngineEvent):
    position: PaperPosition
    trigger_order_id: str
    trigger_side: str
    fill_price: Decimal
    fill_quantity: Decimal
    realized_pnl: Decimal        # pure price PnL for this fill only (no fees)


@dataclass(frozen=True)
class FundingApplied(EngineEvent):
    funding_rate: Decimal
    charge_quote: Decimal
    position_notional: Decimal


@dataclass(frozen=True)
class EngineError(EngineEvent):
    error_type: str
    message: str
