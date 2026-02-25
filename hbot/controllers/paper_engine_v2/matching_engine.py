"""Order Matching Engine for Paper Engine v2.

One engine instance per instrument. Manages order acceptance, latency queueing,
fill evaluation, fee computation, settlement, and event emission.

Error handling contract: no public method raises. All exceptions are caught,
logged, and returned as EngineError events. This ensures the tick loop is
always safe.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from controllers.paper_engine_v2.fee_models import FeeModel
from controllers.paper_engine_v2.fill_models import FillModel
from controllers.paper_engine_v2.latency_model import LatencyModel, NO_LATENCY
from controllers.paper_engine_v2.portfolio import PaperPortfolio
from controllers.paper_engine_v2.types import (
    EngineError,
    EngineEvent,
    InstrumentId,
    InstrumentSpec,
    OrderAccepted,
    OrderCanceled,
    OrderRejected,
    OrderSide,
    OrderStatus,
    PaperOrder,
    PaperOrderType,
    OrderBookSnapshot,
    _EPS,
    _ZERO,
    _uuid,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class EngineConfig:
    latency_ms: int = 150               # min ms between fills on same order
    max_fills_per_order: int = 8
    max_open_orders: int = 50           # per-instrument
    reject_crossed_maker: bool = True   # reject LIMIT_MAKER crossing the spread
    prune_terminal_after_s: float = 60.0
    liquidity_consumption: bool = False  # track consumed depth per tick (Nautilus option)


# ---------------------------------------------------------------------------
# OrderMatchingEngine
# ---------------------------------------------------------------------------

class OrderMatchingEngine:
    """Single-instrument order matching engine.

    Thread safety: not thread-safe; must be driven from a single tick thread.
    """

    def __init__(
        self,
        instrument_id: InstrumentId,
        instrument_spec: InstrumentSpec,
        portfolio: PaperPortfolio,
        fill_model: FillModel,
        fee_model: FeeModel,
        latency_model: LatencyModel,
        config: EngineConfig,
        leverage: int = 1,
    ):
        self._iid = instrument_id
        self._spec = instrument_spec
        self._portfolio = portfolio
        self._fill_model = fill_model
        self._fee_model = fee_model
        self._latency_model = latency_model
        self._config = config
        self._leverage = max(1, leverage)

        self._book: Optional[OrderBookSnapshot] = None
        self._orders: Dict[str, PaperOrder] = {}
        # inflight queue: (due_at_ns, action: str, order: PaperOrder)
        self._inflight: List[Tuple[int, str, PaperOrder]] = []
        self._last_fill_ns: Dict[str, int] = {}
        # liquidity consumption tracking
        self._consumed: Dict[Decimal, Decimal] = {}

    # -- Public API --------------------------------------------------------

    def submit_order(self, order: PaperOrder, now_ns: int) -> EngineEvent:
        """Validate, quantize, and accept/reject an order. Never raises."""
        try:
            return self._submit_order_impl(order, now_ns)
        except Exception as exc:
            logger.error("submit_order failed for %s: %s", order.order_id, exc, exc_info=True)
            return EngineError(
                event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                error_type=type(exc).__name__, message=str(exc),
            )

    def cancel_order(self, order_id: str, now_ns: int) -> Optional[EngineEvent]:
        """Cancel an open order. Returns OrderCanceled or None if not found. Never raises."""
        try:
            return self._cancel_order_impl(order_id, now_ns)
        except Exception as exc:
            logger.error("cancel_order failed for %s: %s", order_id, exc, exc_info=True)
            return EngineError(
                event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                error_type=type(exc).__name__, message=str(exc),
            )

    def cancel_all(self, now_ns: int) -> List[EngineEvent]:
        """Cancel all open orders. Never raises."""
        events: List[EngineEvent] = []
        for oid in list(self._orders.keys()):
            ev = self.cancel_order(oid, now_ns)
            if ev is not None:
                events.append(ev)
        # Also cancel inflight
        for (_, action, order) in list(self._inflight):
            if action == "accept":
                order.status = OrderStatus.CANCELED
                events.append(OrderCanceled(
                    event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                    order_id=order.order_id, source_bot=order.source_bot,
                ))
        self._inflight.clear()
        return events

    def update_book(self, snapshot: OrderBookSnapshot) -> None:
        """Mirror the latest book snapshot. Resets liquidity consumption."""
        if self._config.liquidity_consumption:
            if self._book is None or snapshot.timestamp_ns != self._book.timestamp_ns:
                self._consumed.clear()
        self._book = snapshot

    def tick(self, now_ns: int) -> List[EngineEvent]:
        """Drive one tick: process inflight, match orders. Never raises."""
        events: List[EngineEvent] = []
        try:
            events.extend(self._process_inflight(now_ns))
            events.extend(self._match_orders(now_ns))
            self._prune_terminal(now_ns)
        except Exception as exc:
            logger.error("engine.tick failed for %s: %s", self._iid.key, exc, exc_info=True)
            events.append(EngineError(
                event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                error_type=type(exc).__name__, message=str(exc),
            ))
        return events

    def open_orders(self) -> List[PaperOrder]:
        return [o for o in self._orders.values() if o.is_open]

    def get_order(self, order_id: str) -> Optional[PaperOrder]:
        return self._orders.get(order_id)

    # -- Internal ----------------------------------------------------------

    def _submit_order_impl(self, order: PaperOrder, now_ns: int) -> EngineEvent:
        # 1. Quantize
        order.price = self._spec.quantize_price(order.price, order.side.value)
        order.quantity = self._spec.quantize_size(order.quantity)

        # 2. Spec validation
        reject = self._spec.validate_order(order.price, order.quantity)
        if reject:
            return self._reject(order, reject, now_ns)

        # 3. LIMIT_MAKER cross check
        if order.order_type == PaperOrderType.LIMIT_MAKER and self._book:
            if self._would_cross(order):
                if self._config.reject_crossed_maker:
                    return self._reject(order, "limit_maker_would_cross", now_ns)
                order.crossed_at_creation = True

        # 4. Reserve check
        asset, amount = self._compute_reserve(order)
        if not self._portfolio.can_reserve(asset, amount):
            return self._reject(order, "insufficient_balance", now_ns)

        # 5. Risk guard
        mid = self._book.mid_price if self._book else None
        reason = self._portfolio.risk_guard.check_order(order, self._spec, mid)
        if reason:
            return self._reject(order, reason, now_ns)

        # 6. Reserve
        self._portfolio.reserve(asset, amount)
        order._reserved_asset = asset
        order._reserved_amount = amount

        # 7. Max open orders check
        if len([o for o in self._orders.values() if o.is_open]) >= self._config.max_open_orders:
            self._portfolio.release(asset, amount)
            return self._reject(order, "max_open_orders_reached", now_ns)

        # 8. Latency queue or direct accept
        if self._latency_model.total_insert_ns > 0:
            order.status = OrderStatus.PENDING_SUBMIT
            due_ns = now_ns + self._latency_model.total_insert_ns
            self._inflight.append((due_ns, "accept", order))
        else:
            order.status = OrderStatus.OPEN
            self._orders[order.order_id] = order

        return OrderAccepted(
            event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
            order_id=order.order_id,
            side=order.side.value, order_type=order.order_type.value,
            price=order.price, quantity=order.quantity,
            source_bot=order.source_bot,
        )

    def _cancel_order_impl(self, order_id: str, now_ns: int) -> Optional[EngineEvent]:
        order = self._orders.get(order_id)
        if order is None:
            return None
        if order.is_terminal:
            return None

        order.status = OrderStatus.CANCELED
        order.updated_at_ns = now_ns
        self._portfolio.release(order._reserved_asset, order._reserved_amount)
        del self._orders[order_id]
        self._last_fill_ns.pop(order_id, None)

        return OrderCanceled(
            event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
            order_id=order_id, source_bot=order.source_bot,
        )

    def _process_inflight(self, now_ns: int) -> List[EngineEvent]:
        events: List[EngineEvent] = []
        still_inflight = []
        for (due_ns, action, order) in self._inflight:
            if due_ns <= now_ns:
                if action == "accept":
                    order.status = OrderStatus.OPEN
                    self._orders[order.order_id] = order
                    events.append(OrderAccepted(
                        event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                        order_id=order.order_id, side=order.side.value,
                        order_type=order.order_type.value,
                        price=order.price, quantity=order.quantity,
                        source_bot=order.source_bot,
                    ))
            else:
                still_inflight.append((due_ns, action, order))
        self._inflight = still_inflight
        return events

    def _match_orders(self, now_ns: int) -> List[EngineEvent]:
        events: List[EngineEvent] = []
        if self._book is None:
            return events

        min_gap_ns = self._config.latency_ms * 1_000_000

        for order in list(self._orders.values()):
            if order.is_terminal:
                continue
            if order.fill_count >= self._config.max_fills_per_order:
                continue

            # Time gate
            last_fill_ns = self._last_fill_ns.get(order.order_id, 0)
            if last_fill_ns > 0 and (now_ns - last_fill_ns) < min_gap_ns:
                continue

            decision = self._fill_model.evaluate(order, self._book, now_ns)
            if decision.fill_quantity <= _ZERO:
                continue

            fill_qty = decision.fill_quantity

            # Liquidity consumption tracking (Nautilus option)
            if self._config.liquidity_consumption:
                level = decision.fill_price
                consumed_so_far = self._consumed.get(level, _ZERO)
                book_size = self._book_size_at(level, order.side)
                available = max(_ZERO, book_size - consumed_so_far)
                fill_qty = min(fill_qty, available)
                if fill_qty <= _ZERO:
                    continue
                self._consumed[level] = consumed_so_far + fill_qty

            fill_notional = fill_qty * decision.fill_price
            fee = self._fee_model.compute(fill_notional, decision.is_maker)

            pos_event = self._portfolio.settle_fill(
                instrument_id=self._iid,
                side=order.side,
                quantity=fill_qty,
                price=decision.fill_price,
                fee=fee,
                source_bot=order.source_bot,
                now_ns=now_ns,
                spec=self._spec,
                leverage=self._leverage,
            )

            order.filled_quantity += fill_qty
            order.filled_notional += fill_notional
            order.cumulative_fee += fee
            order.fill_count += 1
            order.updated_at_ns = now_ns
            self._last_fill_ns[order.order_id] = now_ns

            from controllers.paper_engine_v2.types import OrderFilled
            events.append(OrderFilled(
                event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                order_id=order.order_id,
                fill_price=decision.fill_price,
                fill_quantity=fill_qty,
                fee=fee, is_maker=decision.is_maker,
                remaining_quantity=order.remaining_quantity,
                source_bot=order.source_bot,
            ))
            events.append(pos_event)

            if order.remaining_quantity <= self._spec.size_increment + _EPS:
                order.status = OrderStatus.FILLED
                self._portfolio.release(order._reserved_asset, order._reserved_amount)
                del self._orders[order.order_id]
            else:
                order.status = OrderStatus.PARTIALLY_FILLED

        return events

    def _book_size_at(self, price: Decimal, side: OrderSide) -> Decimal:
        """Get visible book size at a price level."""
        if self._book is None:
            return _ZERO
        levels = self._book.asks if side == OrderSide.BUY else self._book.bids
        for lv in levels:
            if lv.price == price:
                return lv.size
        return _ZERO

    def _prune_terminal(self, now_ns: int) -> None:
        cutoff_ns = now_ns - int(self._config.prune_terminal_after_s * 1_000_000_000)
        to_remove = [
            oid for oid, o in self._orders.items()
            if o.is_terminal and o.updated_at_ns < cutoff_ns
        ]
        for oid in to_remove:
            del self._orders[oid]
            self._last_fill_ns.pop(oid, None)

    def _compute_reserve(self, order: PaperOrder) -> Tuple[str, Decimal]:
        """Compute reserve asset and amount.

        Spot BUY: reserve full notional in quote.
        Spot SELL: reserve quantity in base.
        Perp: reserve margin only (LeveragedMarginModel).
        """
        iid = self._spec.instrument_id
        if iid.is_perp:
            margin = self._spec.compute_margin_init(order.quantity, order.price, self._leverage)
            return (iid.quote_asset, margin)
        if order.side == OrderSide.BUY:
            return (iid.quote_asset, order.quantity * order.price)
        return (iid.base_asset, order.quantity)

    def _would_cross(self, order: PaperOrder) -> bool:
        if self._book is None:
            return False
        if order.side == OrderSide.BUY:
            ba = self._book.best_ask
            return ba is not None and order.price >= ba.price
        bb = self._book.best_bid
        return bb is not None and order.price <= bb.price

    def _reject(self, order: PaperOrder, reason: str, now_ns: int) -> OrderRejected:
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason
        order.updated_at_ns = now_ns
        return OrderRejected(
            event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
            order_id=order.order_id, reason=reason, source_bot=order.source_bot,
        )
