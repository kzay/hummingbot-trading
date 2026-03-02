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
    order_status_transition,
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
    price_protection_points: int = 0     # 0 disables protection
    margin_model_type: str = "leveraged"  # "leveraged"|"standard"


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
        self._order_sides: Dict[str, str] = {}  # order_id → side value (kept after fill for event routing)
        # liquidity consumption tracking
        self._consumed: Dict[Decimal, Decimal] = {}
        # cancel intents waiting for cancel-latency confirmation
        self._pending_cancel_ids: set[str] = set()
        # contingent children parked until parent fill condition is met
        self._parked_contingent: Dict[str, PaperOrder] = {}
        self._contingent_children: Dict[str, List[str]] = {}

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
        for oid in list(self._parked_contingent.keys()):
            parked = self._parked_contingent.pop(oid)
            parked.status = OrderStatus.CANCELED
            events.append(OrderCanceled(
                event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                order_id=oid, source_bot=parked.source_bot,
            ))
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

    def get_order_side(self, order_id: str) -> Optional[str]:
        """Return the side ('buy'/'sell') of an order, even after it was filled and removed."""
        return self._order_sides.get(order_id)

    def force_reduce(self, side: OrderSide, quantity: Decimal, now_ns: int, source_bot: str = "risk_engine") -> List[EngineEvent]:
        """Force a taker reduction fill outside normal order checks.

        Used by liquidation logic when risk engine requests immediate size
        reduction. This bypasses order admission checks and reserves.
        """
        events: List[EngineEvent] = []
        if self._book is None or quantity <= _ZERO:
            return events
        top = self._book.best_ask if side == OrderSide.BUY else self._book.best_bid
        if top is None or top.price <= _ZERO:
            return events
        fill_qty = min(quantity, max(_ZERO, top.size))
        if fill_qty <= _ZERO:
            return events
        fill_notional = fill_qty * top.price
        fee = self._fee_model.compute(fill_notional, is_maker=False)
        pos_event = self._portfolio.settle_fill(
            instrument_id=self._iid,
            side=side,
            quantity=fill_qty,
            price=top.price,
            fee=fee,
            source_bot=source_bot,
            now_ns=now_ns,
            spec=self._spec,
            leverage=self._leverage,
        )
        synthetic_id = f"forced_liq_{now_ns}_{len(self._order_sides)}"
        self._order_sides[synthetic_id] = side.value
        from controllers.paper_engine_v2.types import OrderFilled
        events.append(OrderFilled(
            event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
            order_id=synthetic_id,
            fill_price=top.price,
            fill_quantity=fill_qty,
            fee=fee, is_maker=False,
            remaining_quantity=_ZERO,
            source_bot=source_bot,
        ))
        events.append(pos_event)
        return events

    # -- Internal ----------------------------------------------------------

    def _submit_order_impl(self, order: PaperOrder, now_ns: int) -> EngineEvent:
        market_probe = order.order_type == PaperOrderType.MARKET
        if market_probe:
            best_bid = getattr(getattr(self._book, "best_bid", None), "price", "")
            best_ask = getattr(getattr(self._book, "best_ask", None), "price", "")
            logger.warning(
                "MATCH_ENGINE_PROBE stage=submit_start instrument=%s order_id=%s side=%s qty=%s price=%s has_book=%s best_bid=%s best_ask=%s",
                self._iid.key,
                order.order_id,
                order.side.value,
                str(order.quantity),
                str(order.price),
                str(self._book is not None),
                str(best_bid),
                str(best_ask),
            )

        def _reject_with_probe(reason: str) -> OrderRejected:
            if market_probe:
                logger.warning(
                    "MATCH_ENGINE_PROBE stage=submit_reject instrument=%s order_id=%s reason=%s",
                    self._iid.key,
                    order.order_id,
                    reason,
                )
            return self._reject(order, reason, now_ns)

        # 1. Quantize
        order.price = self._spec.quantize_price(order.price, order.side.value)
        order.quantity = self._spec.quantize_size(order.quantity)

        # 2. Spec validation
        reject = self._spec.validate_order(order.price, order.quantity)
        if reject:
            return _reject_with_probe(reject)

        # 2b. Strict reduce-only checks.
        if order.reduce_only:
            reason = self._reduce_only_violation(order)
            if reason:
                return _reject_with_probe(reason)

        # 2c. Park contingent orders (OTO-style): accepted now, activated later.
        parent_id = (order.contingent_parent_order_id or "").strip()
        if parent_id:
            mode = (order.contingent_trigger_mode or "partial").strip().lower()
            if mode not in {"partial", "full"}:
                return _reject_with_probe("invalid_contingent_trigger_mode")
            order.status = OrderStatus.PENDING_SUBMIT
            self._parked_contingent[order.order_id] = order
            self._contingent_children.setdefault(parent_id, []).append(order.order_id)
            self._order_sides[order.order_id] = order.side.value
            if market_probe:
                logger.warning(
                    "MATCH_ENGINE_PROBE stage=submit_accepted_parked instrument=%s order_id=%s",
                    self._iid.key,
                    order.order_id,
                )
            return OrderAccepted(
                event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                order_id=order.order_id,
                side=order.side.value, order_type=order.order_type.value,
                price=order.price, quantity=order.quantity,
                source_bot=order.source_bot,
            )

        # 3. LIMIT_MAKER cross check
        if order.order_type == PaperOrderType.LIMIT_MAKER and self._book:
            if self._would_cross(order):
                if self._config.reject_crossed_maker:
                    return _reject_with_probe("limit_maker_would_cross")
                order.crossed_at_creation = True

        # 4. Reserve check
        asset, amount = self._compute_reserve(order)
        if not self._portfolio.can_reserve(asset, amount):
            return _reject_with_probe("insufficient_balance")

        # 5. Risk guard
        mid = self._book.mid_price if self._book else None
        reason = self._portfolio.risk_guard.check_order(order, self._spec, mid)
        if reason:
            return _reject_with_probe(reason)

        # 6. Max open orders check (before reserve to avoid leaking)
        if len([o for o in self._orders.values() if o.is_open]) >= self._config.max_open_orders:
            return _reject_with_probe("max_open_orders_reached")

        # 7. Reserve (only after all pre-checks pass)
        self._portfolio.reserve(asset, amount)
        order._reserved_asset = asset
        order._reserved_amount = amount

        # 8. Latency queue or direct accept (state machine transition)
        if self._latency_model.total_insert_ns > 0:
            # Order starts as PENDING_SUBMIT (already set by caller/conftest).
            # If it isn't, set it — this is an idempotent no-op for the state machine.
            if order.status != OrderStatus.PENDING_SUBMIT:
                order.status = order_status_transition(order.status, OrderStatus.PENDING_SUBMIT)
            due_ns = now_ns + self._latency_model.total_insert_ns
            self._inflight.append((due_ns, "accept", order))
        else:
            order.status = order_status_transition(order.status, OrderStatus.OPEN)
            self._orders[order.order_id] = order
            self._order_sides[order.order_id] = order.side.value

        if market_probe:
            logger.warning(
                "MATCH_ENGINE_PROBE stage=submit_accepted instrument=%s order_id=%s status=%s open_orders=%d inflight=%d reserved_asset=%s reserved_amount=%s",
                self._iid.key,
                order.order_id,
                order.status.value,
                len(self._orders),
                len(self._inflight),
                str(order._reserved_asset),
                str(order._reserved_amount),
            )

        return OrderAccepted(
            event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
            order_id=order.order_id,
            side=order.side.value, order_type=order.order_type.value,
            price=order.price, quantity=order.quantity,
            source_bot=order.source_bot,
        )

    def _cancel_order_impl(self, order_id: str, now_ns: int) -> Optional[EngineEvent]:
        # Handle cancel request while still in insert latency queue.
        for _, action, inflight_order in self._inflight:
            if action == "accept" and inflight_order.order_id == order_id:
                try:
                    inflight_order.status = order_status_transition(inflight_order.status, OrderStatus.CANCELED)
                except ValueError:
                    pass
                inflight_order.updated_at_ns = now_ns
                if inflight_order._reserved_amount > _ZERO:
                    self._portfolio.release(inflight_order._reserved_asset, inflight_order._reserved_amount)
                    inflight_order._reserved_amount = _ZERO
                return OrderCanceled(
                    event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                    order_id=order_id, source_bot=inflight_order.source_bot,
                )

        order = self._orders.get(order_id)
        if order is None:
            parked = self._parked_contingent.pop(order_id, None)
            if parked is None:
                return None
            parked.status = OrderStatus.CANCELED
            parked.updated_at_ns = now_ns
            return OrderCanceled(
                event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                order_id=order_id, source_bot=parked.source_bot,
            )
        if order.is_terminal:
            return None
        if order_id in self._pending_cancel_ids:
            return None

        # When cancel latency is enabled, cancellation is acknowledged later.
        # This allows realistic cancel/fill race behavior.
        if self._latency_model.total_cancel_ns > 0:
            due_ns = now_ns + self._latency_model.total_cancel_ns
            self._inflight.append((due_ns, "cancel", order))
            self._pending_cancel_ids.add(order_id)
            return None

        try:
            order.status = order_status_transition(order.status, OrderStatus.CANCELED)
        except ValueError:
            # Non-cancellable terminal state — return None silently.
            return None
        order.updated_at_ns = now_ns

        # Reserve release — safety check to avoid double-release
        if order._reserved_amount > _ZERO:
            self._portfolio.release(order._reserved_asset, order._reserved_amount)
            order._reserved_amount = _ZERO

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
                    try:
                        order.status = order_status_transition(order.status, OrderStatus.OPEN)
                    except ValueError:
                        # Order was canceled while in latency queue; release reserve.
                        if order._reserved_amount > _ZERO:
                            self._portfolio.release(order._reserved_asset, order._reserved_amount)
                            order._reserved_amount = _ZERO
                        continue
                    self._orders[order.order_id] = order
                    self._order_sides[order.order_id] = order.side.value
                    events.append(OrderAccepted(
                        event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                        order_id=order.order_id, side=order.side.value,
                        order_type=order.order_type.value,
                        price=order.price, quantity=order.quantity,
                        source_bot=order.source_bot,
                    ))
                elif action == "cancel":
                    self._pending_cancel_ids.discard(order.order_id)
                    live = self._orders.get(order.order_id)
                    if live is None or live.is_terminal:
                        continue
                    try:
                        live.status = order_status_transition(live.status, OrderStatus.CANCELED)
                    except ValueError:
                        continue
                    live.updated_at_ns = now_ns
                    if live._reserved_amount > _ZERO:
                        self._portfolio.release(live._reserved_asset, live._reserved_amount)
                        live._reserved_amount = _ZERO
                    del self._orders[live.order_id]
                    self._last_fill_ns.pop(live.order_id, None)
                    events.append(OrderCanceled(
                        event_id=_uuid(), timestamp_ns=now_ns, instrument_id=self._iid,
                        order_id=live.order_id, source_bot=live.source_bot,
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
                if order.order_type == PaperOrderType.MARKET:
                    best_bid = getattr(getattr(self._book, "best_bid", None), "price", "")
                    best_ask = getattr(getattr(self._book, "best_ask", None), "price", "")
                    logger.warning(
                        "MATCH_ENGINE_PROBE stage=tick_no_fill instrument=%s order_id=%s qty=%s best_bid=%s best_ask=%s",
                        self._iid.key,
                        order.order_id,
                        str(order.remaining_quantity),
                        str(best_bid),
                        str(best_ask),
                    )
                continue

            fill_qty = decision.fill_quantity
            # Price-protection bands are designed for resting orders; applying them to
            # market orders can deadlock derisk flows under realistic slippage models.
            if order.order_type != PaperOrderType.MARKET and self._violates_price_protection(order.side, decision.fill_price):
                if order.order_type == PaperOrderType.MARKET:
                    logger.warning(
                        "MATCH_ENGINE_PROBE stage=tick_price_protection_block instrument=%s order_id=%s fill_price=%s",
                        self._iid.key,
                        order.order_id,
                        str(decision.fill_price),
                    )
                continue

            # Liquidity consumption tracking (Nautilus option)
            if self._config.liquidity_consumption and order.order_type != PaperOrderType.MARKET:
                level = decision.fill_price
                consumed_so_far = self._consumed.get(level, _ZERO)
                book_size = self._book_size_at(level, order.side)
                available = max(_ZERO, book_size - consumed_so_far)
                fill_qty = min(fill_qty, available)
                if fill_qty <= _ZERO:
                    if order.order_type == PaperOrderType.MARKET:
                        logger.warning(
                            "MATCH_ENGINE_PROBE stage=tick_no_fill_after_liquidity instrument=%s order_id=%s level=%s",
                            self._iid.key,
                            order.order_id,
                            str(level),
                        )
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

            # Resize reserve to remaining quantity (prevents over-reserving on partial fills).
            try:
                remaining = order.remaining_quantity
                if remaining < _ZERO:
                    remaining = _ZERO
                # Compute what reserve should be for *remaining* order quantity.
                tmp = PaperOrder(
                    order_id=order.order_id,
                    instrument_id=order.instrument_id,
                    side=order.side,
                    order_type=order.order_type,
                    price=order.price,
                    quantity=remaining,
                    status=order.status,
                    created_at_ns=order.created_at_ns,
                    updated_at_ns=order.updated_at_ns,
                    source_bot=order.source_bot,
                )
                new_asset, new_amt = self._compute_reserve(tmp)
                if new_asset == order._reserved_asset:
                    new_amt = max(_ZERO, new_amt)
                    curr = max(_ZERO, order._reserved_amount)
                    if new_amt > curr:
                        self._portfolio.reserve(new_asset, new_amt - curr)
                    elif new_amt < curr:
                        self._portfolio.release(new_asset, curr - new_amt)
                    order._reserved_amount = new_amt
                # If asset mismatches (shouldn't happen), keep existing reserve.
            except Exception:
                pass

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
            if order.order_type == PaperOrderType.MARKET:
                logger.warning(
                    "MATCH_ENGINE_PROBE stage=tick_filled instrument=%s order_id=%s fill_qty=%s fill_price=%s remaining=%s",
                    self._iid.key,
                    order.order_id,
                    str(fill_qty),
                    str(decision.fill_price),
                    str(order.remaining_quantity),
                )
            events.append(pos_event)

            if order.remaining_quantity <= self._spec.size_increment + _EPS:
                order.status = order_status_transition(order.status, OrderStatus.FILLED)
                # Final reserve release
                if order._reserved_amount > _ZERO:
                    self._portfolio.release(order._reserved_asset, order._reserved_amount)
                    order._reserved_amount = _ZERO
                del self._orders[order.order_id]
            else:
                order.status = order_status_transition(order.status, OrderStatus.PARTIALLY_FILLED)
            events.extend(self._activate_contingent_children(order.order_id, now_ns))

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
            lev = self._leverage if self._config.margin_model_type.lower() == "leveraged" else 1
            margin = self._spec.compute_margin_init(order.quantity, order.price, lev)
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

    def _reduce_only_violation(self, order: PaperOrder) -> str:
        pos = self._portfolio.get_position(self._iid)
        qty = pos.quantity if pos is not None else _ZERO
        if order.side == OrderSide.BUY:
            if qty >= _ZERO:
                return "reduce_only_no_short_position"
            if order.quantity > abs(qty) + _EPS:
                return "reduce_only_exceeds_position"
            return ""
        if qty <= _ZERO:
            return "reduce_only_no_long_position"
        if order.quantity > qty + _EPS:
            return "reduce_only_exceeds_position"
        return ""

    def _violates_price_protection(self, side: OrderSide, fill_price: Decimal) -> bool:
        points = max(0, int(self._config.price_protection_points))
        if points <= 0 or self._book is None:
            return False
        band = self._spec.price_increment * Decimal(points)
        if side == OrderSide.BUY:
            top = self._book.best_ask
            if top is None:
                return False
            return fill_price > (top.price + band + _EPS)
        top = self._book.best_bid
        if top is None:
            return False
        return fill_price < (top.price - band - _EPS)

    def _activate_contingent_children(self, parent_order_id: str, now_ns: int) -> List[EngineEvent]:
        out: List[EngineEvent] = []
        child_ids = list(self._contingent_children.get(parent_order_id, []))
        if not child_ids:
            return out
        parent = self._orders.get(parent_order_id)
        parent_is_filled = parent is None
        parent_partially_filled = parent is not None and parent.filled_quantity > _ZERO
        keep_ids: List[str] = []
        for child_id in child_ids:
            child = self._parked_contingent.get(child_id)
            if child is None:
                continue
            mode = (child.contingent_trigger_mode or "partial").strip().lower()
            should_activate = parent_is_filled if mode == "full" else (parent_is_filled or parent_partially_filled)
            if not should_activate:
                keep_ids.append(child_id)
                continue
            child.contingent_parent_order_id = ""
            out.append(self._submit_order_impl(child, now_ns))
            self._parked_contingent.pop(child_id, None)
        if keep_ids:
            self._contingent_children[parent_order_id] = keep_ids
        else:
            self._contingent_children.pop(parent_order_id, None)
        return out
