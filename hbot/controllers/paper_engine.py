from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from types import MethodType
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)

try:
    from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
    from hummingbot.connector.connector_base import ConnectorBase
    from hummingbot.core.event.events import (
        BuyOrderCompletedEvent,
        BuyOrderCreatedEvent,
        MarketEvent,
        MarketOrderFailureEvent,
        OrderCancelledEvent,
        OrderFilledEvent,
        SellOrderCompletedEvent,
        SellOrderCreatedEvent,
    )
    from hummingbot.core.utils.estimate_fee import build_trade_fee
    _HAS_FRAMEWORK_EVENTS = True
except Exception:  # pragma: no cover - local fallback for unit tests
    _HAS_FRAMEWORK_EVENTS = False
    class _EnumValue:
        def __init__(self, value: int, name: str):
            self.value = value
            self.name = name

    class OrderType:
        LIMIT = _EnumValue(1, "LIMIT")
        LIMIT_MAKER = _EnumValue(2, "LIMIT_MAKER")
        MARKET = _EnumValue(3, "MARKET")

    class PriceType:
        MidPrice = _EnumValue(1, "MidPrice")
        BestBid = _EnumValue(2, "BestBid")
        BestAsk = _EnumValue(3, "BestAsk")

    class TradeType:
        BUY = _EnumValue(1, "BUY")
        SELL = _EnumValue(2, "SELL")

    class MarketEvent:
        OrderCancelled = _EnumValue(106, "OrderCancelled")
        BuyOrderCreated = _EnumValue(200, "BuyOrderCreated")
        SellOrderCreated = _EnumValue(201, "SellOrderCreated")
        OrderFilled = _EnumValue(107, "OrderFilled")
        BuyOrderCompleted = _EnumValue(202, "BuyOrderCompleted")
        SellOrderCompleted = _EnumValue(203, "SellOrderCompleted")
        OrderFailure = _EnumValue(198, "OrderFailure")
    class ConnectorBase:
        pass


try:
    from services.common.utils import to_decimal
except Exception:  # pragma: no cover - standalone test fallback
    def to_decimal(value: Any) -> Decimal:
        return Decimal(str(value))

try:
    from services.common.exchange_profiles import resolve_profile
except Exception:  # pragma: no cover - standalone test fallback
    resolve_profile = None


def _canonical_connector_name(connector_name: str) -> str:
    if not str(connector_name).endswith("_paper_trade"):
        return connector_name
    if resolve_profile is not None:
        try:
            profile = resolve_profile(connector_name)
            if isinstance(profile, dict):
                required = profile.get("requires_paper_trade_exchange")
                if isinstance(required, str) and required:
                    return required
        except Exception:
            pass
    return connector_name[:-12]


@dataclass
class PaperEngineConfig:
    enabled: bool = True
    seed: int = 7
    latency_ms: int = 150
    queue_participation: Decimal = Decimal("0.35")
    slippage_bps: Decimal = Decimal("1.0")
    adverse_selection_bps: Decimal = Decimal("1.5")
    min_partial_fill_ratio: Decimal = Decimal("0.15")
    max_partial_fill_ratio: Decimal = Decimal("0.85")
    max_fills_per_order: int = 8
    maker_fee_bps: Decimal = Decimal("2.0")
    taker_fee_bps: Decimal = Decimal("10.0")


@dataclass
class PaperOrder:
    order_id: str
    trading_pair: str
    trade_type: Any
    order_type: Any
    amount: Decimal
    price: Decimal
    creation_timestamp: float
    base_asset: str
    quote_asset: str
    reserved_base: Decimal = Decimal("0")
    reserved_quote: Decimal = Decimal("0")
    executed_amount_base: Decimal = Decimal("0")
    executed_amount_quote: Decimal = Decimal("0")
    cumulative_fee_paid_quote: Decimal = Decimal("0")
    fee_asset: str = ""
    current_state: str = "OPEN"
    last_update_timestamp: float = 0.0
    fill_count: int = 0
    max_fills: int = 8
    crossed_at_creation: bool = False

    @property
    def client_order_id(self) -> str:
        return self.order_id

    @property
    def is_open(self) -> bool:
        return self.current_state in {"OPEN", "PARTIALLY_FILLED"}

    @property
    def is_done(self) -> bool:
        return self.current_state in {"FILLED", "CANCELED", "FAILED"}

    @property
    def is_filled(self) -> bool:
        return self.current_state == "FILLED"

    @property
    def average_executed_price(self) -> Decimal:
        if self.executed_amount_base <= 0:
            return self.price
        return self.executed_amount_quote / self.executed_amount_base

    @property
    def cum_fees_quote(self) -> Decimal:
        return self.cumulative_fee_paid_quote

    @property
    def cum_fees_base(self) -> Decimal:
        if self.fee_asset == self.base_asset and self.average_executed_price > 0:
            return self.cumulative_fee_paid_quote / self.average_executed_price
        return Decimal("0")

    def to_json(self) -> Dict[str, str]:
        return {
            "order_id": self.order_id,
            "trading_pair": self.trading_pair,
            "state": self.current_state,
            "executed_amount_base": str(self.executed_amount_base),
            "executed_amount_quote": str(self.executed_amount_quote),
        }


class _OrderTrackerShim:
    _PRUNE_INTERVAL = 60.0

    def __init__(self):
        self._orders: Dict[str, PaperOrder] = {}
        self._last_prune_ts: float = 0.0

    def track(self, order: PaperOrder) -> None:
        self._orders[order.order_id] = order

    def fetch_order(self, client_order_id: str) -> Optional[PaperOrder]:
        return self._orders.get(client_order_id)

    def remove(self, client_order_id: str) -> None:
        self._orders.pop(client_order_id, None)

    def iter_open(self) -> Iterable[PaperOrder]:
        for order in list(self._orders.values()):
            if order.is_open:
                yield order

    def prune_done(self, now_ts: float) -> int:
        """Remove completed orders older than 60 seconds. Returns count removed."""
        if now_ts - self._last_prune_ts < self._PRUNE_INTERVAL:
            return 0
        self._last_prune_ts = now_ts
        cutoff = now_ts - 60.0
        to_remove = [
            oid for oid, order in self._orders.items()
            if order.is_done and order.last_update_timestamp < cutoff
        ]
        for oid in to_remove:
            del self._orders[oid]
        return len(to_remove)


@dataclass
class FillDecision:
    fill_qty: Decimal
    fill_price: Decimal
    is_taker: bool
    queue_delay_ms: int


@dataclass
class PaperLedger:
    balances: Dict[str, Decimal]
    reserved: Dict[str, Decimal] = field(default_factory=dict)

    def total(self, asset: str) -> Decimal:
        return self.balances.get(asset, Decimal("0"))

    def available(self, asset: str) -> Decimal:
        return self.total(asset) - self.reserved.get(asset, Decimal("0"))

    def reserve(self, asset: str, amount: Decimal) -> bool:
        amount = max(Decimal("0"), amount)
        if self.available(asset) + Decimal("1e-12") < amount:
            return False
        self.reserved[asset] = self.reserved.get(asset, Decimal("0")) + amount
        return True

    def release(self, asset: str, amount: Decimal) -> None:
        amount = max(Decimal("0"), amount)
        current = self.reserved.get(asset, Decimal("0"))
        self.reserved[asset] = max(Decimal("0"), current - amount)

    def credit(self, asset: str, amount: Decimal) -> None:
        self.balances[asset] = self.total(asset) + amount

    def debit(self, asset: str, amount: Decimal) -> bool:
        if self.available(asset) + Decimal("1e-12") < amount:
            return False
        self.balances[asset] = self.total(asset) - amount
        return True


class DepthFillModel:
    def __init__(self, cfg: PaperEngineConfig):
        self._cfg = cfg

    def _top(self, book: Any, side: Any) -> Tuple[Decimal, Decimal]:
        try:
            if side == TradeType.BUY:
                entry = next(iter(book.ask_entries()), None)
            else:
                entry = next(iter(book.bid_entries()), None)
            if entry is None:
                return Decimal("0"), Decimal("0")
            return to_decimal(getattr(entry, "price", 0)), to_decimal(getattr(entry, "amount", 0))
        except Exception:
            return Decimal("0"), Decimal("0")

    def evaluate(self, order: PaperOrder, book: Any, now_ts: float) -> FillDecision:
        top_price, top_size = self._top(book, order.trade_type)
        remaining = max(Decimal("0"), order.amount - order.executed_amount_base)
        if top_price <= 0 or remaining <= 0:
            return FillDecision(fill_qty=Decimal("0"), fill_price=order.price, is_taker=False, queue_delay_ms=0)

        queue_factor = max(Decimal("0.05"), min(Decimal("1"), self._cfg.queue_participation))
        is_touchable = (order.trade_type == TradeType.BUY and order.price >= top_price) or (
            order.trade_type == TradeType.SELL and order.price <= top_price
        )

        # LIMIT_MAKER: always passive maker (queue simulation at limit price).
        # Preserves original behavior — fills gradually without requiring
        # the market to touch the order price.
        if order.order_type == OrderType.LIMIT_MAKER and not is_touchable:
            queue_delay_ms = int(max(0, self._cfg.latency_ms) * 1.5)
            max_partial = top_size * queue_factor if top_size > 0 else remaining * self._cfg.max_partial_fill_ratio
            partial_cap = remaining * self._cfg.max_partial_fill_ratio
            partial_floor = remaining * self._cfg.min_partial_fill_ratio
            fill_qty = min(remaining, max_partial, partial_cap)
            if fill_qty <= 0:
                return FillDecision(fill_qty=Decimal("0"), fill_price=order.price, is_taker=False, queue_delay_ms=queue_delay_ms)
            fill_qty = max(fill_qty, min(remaining, partial_floor))
            return FillDecision(fill_qty=fill_qty, fill_price=order.price, is_taker=False, queue_delay_ms=queue_delay_ms)

        # Resting LIMIT order: was placed without crossing the spread.
        # When the market moves to touch the order price, it's a maker fill
        # (the order was sitting in the book, incoming flow matched it).
        is_resting_limit = not order.crossed_at_creation and order.order_type != OrderType.LIMIT_MAKER
        if (is_resting_limit or order.order_type == OrderType.LIMIT_MAKER) and is_touchable:
            queue_delay_ms = int(max(0, self._cfg.latency_ms) * 1.5)
            max_partial = top_size * queue_factor if top_size > 0 else remaining * self._cfg.max_partial_fill_ratio
            partial_cap = remaining * self._cfg.max_partial_fill_ratio
            partial_floor = remaining * self._cfg.min_partial_fill_ratio
            fill_qty = min(remaining, max_partial, partial_cap)
            if fill_qty <= 0:
                return FillDecision(fill_qty=Decimal("0"), fill_price=order.price, is_taker=False, queue_delay_ms=queue_delay_ms)
            fill_qty = max(fill_qty, min(remaining, partial_floor))
            return FillDecision(fill_qty=fill_qty, fill_price=order.price, is_taker=False, queue_delay_ms=queue_delay_ms)

        # Resting LIMIT that market hasn't reached yet — no fill.
        if is_resting_limit and not is_touchable:
            return FillDecision(fill_qty=Decimal("0"), fill_price=order.price, is_taker=False, queue_delay_ms=0)

        # Crossing order (crossed_at_creation=True): taker fill with slippage.
        if is_touchable:
            max_fill = top_size * queue_factor if top_size > 0 else remaining
            fill_qty = min(remaining, max_fill)
            if fill_qty <= 0:
                return FillDecision(fill_qty=Decimal("0"), fill_price=top_price, is_taker=True, queue_delay_ms=0)
            bps = self._cfg.slippage_bps + self._cfg.adverse_selection_bps
            slippage_mult = bps / Decimal("10000")
            if order.trade_type == TradeType.BUY:
                fill_price = top_price * (Decimal("1") + slippage_mult)
            else:
                fill_price = top_price * (Decimal("1") - slippage_mult)
            return FillDecision(fill_qty=fill_qty, fill_price=fill_price, is_taker=True, queue_delay_ms=max(0, self._cfg.latency_ms))

        return FillDecision(fill_qty=Decimal("0"), fill_price=order.price, is_taker=False, queue_delay_ms=0)


class PaperExecutionAdapter(ConnectorBase):
    _FINAL_SWEEP_REMAINING_PCT = Decimal("0.02")
    _MIN_REFRESH_INTERVAL_S = 1.0

    def __init__(
        self,
        connector_name: str,
        trading_pair: str,
        paper_connector: Any,
        market_connector: Any,
        config: PaperEngineConfig,
        time_fn: Optional[Callable[[], float]] = None,
        on_fill: Optional[Callable[[Any], None]] = None,
    ):
        self.connector_name = connector_name
        self.trading_pair = trading_pair
        self._paper_connector = paper_connector
        self._market_connector = market_connector
        self._config = config
        self._time = time_fn or time.time
        self._on_fill = on_fill
        self._listeners: Dict[Any, List[Callable[..., Any]]] = {}
        base_asset, quote_asset = trading_pair.split("-")
        self._base_asset = base_asset
        self._quote_asset = quote_asset
        initial_base = self._safe_balance(paper_connector, base_asset)
        initial_quote = self._safe_balance(paper_connector, quote_asset)
        if initial_base <= 0 and market_connector is not None:
            initial_base = self._safe_balance(market_connector, base_asset)
        if initial_quote <= 0 and market_connector is not None:
            initial_quote = self._safe_balance(market_connector, quote_asset)
        self._ledger = PaperLedger(
            balances={
                base_asset: initial_base,
                quote_asset: initial_quote,
            }
        )
        self._order_tracker = _OrderTrackerShim()
        self._fill_model = DepthFillModel(config)
        self._paper_reject_count = 0
        self._paper_fill_count = 0
        self._paper_total_queue_delay_ms = 0
        self._dropped_relay_count = 0
        self._last_refresh_open_orders_ts: float = 0.0

    @property
    def paper_stats(self) -> Dict[str, Decimal]:
        avg_delay = Decimal("0")
        if self._paper_fill_count > 0:
            avg_delay = to_decimal(self._paper_total_queue_delay_ms) / Decimal(self._paper_fill_count)
        return {
            "paper_fill_count": Decimal(self._paper_fill_count),
            "paper_reject_count": Decimal(self._paper_reject_count),
            "paper_avg_queue_delay_ms": avg_delay,
            "paper_dropped_relay_count": Decimal(self._dropped_relay_count),
        }

    @property
    def ready(self) -> bool:
        return bool(getattr(self._market_connector, "ready", True))

    @property
    def trading_rules(self):
        rules = getattr(self._market_connector, "trading_rules", None) or getattr(self._paper_connector, "trading_rules", None)
        if not isinstance(rules, dict):
            rules = {}
        if self.trading_pair not in rules:
            rules[self.trading_pair] = SimpleNamespace(
                trading_pair=self.trading_pair,
                min_order_size=Decimal("0"),
                min_base_amount=Decimal("0"),
                min_amount=Decimal("0"),
                min_notional_size=Decimal("0"),
                min_notional=Decimal("0"),
                min_order_value=Decimal("0"),
                min_base_amount_increment=Decimal("0"),
                min_order_size_increment=Decimal("0"),
                amount_step=Decimal("0"),
                min_price_increment=Decimal("0"),
                min_price_tick_size=Decimal("0"),
                price_step=Decimal("0"),
                min_price_step=Decimal("0"),
            )
        return rules

    def add_listener(self, event_tag: Any, listener: Callable[..., Any]) -> None:
        self._listeners.setdefault(event_tag, []).append(listener)

    def remove_listener(self, event_tag: Any, listener: Callable[..., Any]) -> None:
        listeners = self._listeners.get(event_tag, [])
        self._listeners[event_tag] = [item for item in listeners if item != listener]

    def trigger_event(self, event_tag: Any, event: Any) -> None:
        tag_value = getattr(event_tag, "value", event_tag)
        # Fire to local listeners (V2 executors register here).
        listeners = list(self._listeners.get(event_tag, []))
        if tag_value != event_tag:
            listeners.extend(self._listeners.get(tag_value, []))
        for listener in listeners:
            try:
                listener(tag_value, self, event)
            except TypeError:
                listener(event)
        # Also fire through the paper_connector so the strategy's
        # EventForwarder receives it → controller.did_fill_order().
        self._relay_to_paper_connector(event_tag, tag_value, event)

    def _relay_to_paper_connector(self, event_tag: Any, tag_value: Any, event: Any) -> None:
        if not _HAS_FRAMEWORK_EVENTS:
            return
        pc = self._paper_connector
        if pc is None:
            return
        trigger = getattr(pc, "trigger_event", None) or getattr(pc, "c_trigger_event", None)
        if trigger is None:
            return
        # Different HB builds accept either enum tags or integer tags.
        try:
            trigger(event_tag, event)
            return
        except Exception:
            pass
        try:
            trigger(tag_value, event)
        except Exception:
            self._dropped_relay_count += 1
            order_id = getattr(event, "order_id", "?")
            logger.error("Fill event relay to paper_connector failed for order %s", order_id, exc_info=True)

    def get_balance(self, asset: str) -> Decimal:
        return self._ledger.total(asset)

    def get_available_balance(self, asset: str) -> Decimal:
        return self._ledger.available(asset)

    def quantize_order_amount(self, trading_pair: str, amount: Decimal) -> Decimal:
        if hasattr(self._market_connector, "quantize_order_amount"):
            return to_decimal(self._market_connector.quantize_order_amount(trading_pair, amount))
        return amount

    def quantize_order_price(self, trading_pair: str, price: Decimal) -> Decimal:
        if hasattr(self._market_connector, "quantize_order_price"):
            return to_decimal(self._market_connector.quantize_order_price(trading_pair, price))
        return price

    def _rule_decimal(self, trading_pair: str, candidates: List[str], default: Decimal = Decimal("0")) -> Decimal:
        try:
            rule = self.trading_rules.get(trading_pair)
        except Exception:
            rule = None
        if rule is None:
            return default
        values: List[Decimal] = []
        for name in candidates:
            raw = getattr(rule, name, None)
            if raw is None:
                continue
            val = to_decimal(raw)
            if val > 0:
                values.append(val)
        if not values:
            return default
        return max(values)

    def _min_fill_amount(self, trading_pair: str) -> Decimal:
        return self._rule_decimal(
            trading_pair,
            [
                "min_base_amount_increment",
                "min_order_size_increment",
                "amount_step",
                "min_order_size",
                "min_base_amount",
                "min_amount",
            ],
            default=Decimal("0"),
        )

    def _min_fill_notional(self, trading_pair: str) -> Decimal:
        return self._rule_decimal(
            trading_pair,
            [
                "min_notional_size",
                "min_notional",
                "min_order_value",
            ],
            default=Decimal("0"),
        )

    def get_price_by_type(self, trading_pair: str, price_type: Any = PriceType.MidPrice):
        self.refresh_open_orders()
        return self._market_connector.get_price_by_type(trading_pair, price_type)

    def get_order_book(self, *args):
        trading_pair = self.trading_pair
        if len(args) == 1:
            trading_pair = args[0]
        elif len(args) >= 2:
            trading_pair = args[1]
        book = self._try_get_order_book(self._market_connector, trading_pair)
        if book is None:
            book = self._try_get_order_book(self._paper_connector, trading_pair)
        if book is None:
            raise RuntimeError(f"no order book available for {trading_pair}")
        return book

    @staticmethod
    def _try_get_order_book(connector: Any, trading_pair: str) -> Any:
        if connector is None:
            return None
        try:
            book = connector.get_order_book(trading_pair)
            if book is None:
                return None
            best_ask = next(iter(book.ask_entries()), None)
            best_bid = next(iter(book.bid_entries()), None)
            if best_ask is not None or best_bid is not None:
                return book
        except Exception:
            pass
        return None

    def cancel(self, trading_pair: str, client_order_id: str):
        order = self._order_tracker.fetch_order(client_order_id)
        if order is None or not order.is_open:
            return False
        order.current_state = "CANCELED"
        order.last_update_timestamp = self._time()
        if order.trade_type == TradeType.BUY:
            self._ledger.release(order.quote_asset, order.reserved_quote)
        else:
            self._ledger.release(order.base_asset, order.reserved_base)
        if _HAS_FRAMEWORK_EVENTS:
            cancel_event = OrderCancelledEvent(
                timestamp=order.last_update_timestamp,
                order_id=order.order_id,
            )
        else:
            cancel_event = SimpleNamespace(order_id=order.order_id, timestamp=order.last_update_timestamp)
        self.trigger_event(MarketEvent.OrderCancelled, cancel_event)
        return True

    def buy(self, trading_pair: str, amount: Decimal, order_type: Any, price: Decimal, *args, **kwargs) -> str:
        return self._submit_order(trading_pair, amount, order_type, TradeType.BUY, price)

    def sell(self, trading_pair: str, amount: Decimal, order_type: Any, price: Decimal, *args, **kwargs) -> str:
        return self._submit_order(trading_pair, amount, order_type, TradeType.SELL, price)

    async def _update_orders_with_error_handler(self, orders: List[PaperOrder], error_handler: Optional[Callable[..., Any]] = None):
        self.refresh_open_orders(force=True)
        return None

    async def _handle_update_error_for_lost_order(self, *args, **kwargs):
        return None

    def refresh_open_orders(self, force: bool = False) -> None:
        now_ts = self._time()
        if not force and self._last_refresh_open_orders_ts > 0:
            if (now_ts - self._last_refresh_open_orders_ts) < self._MIN_REFRESH_INTERVAL_S:
                return
        self._last_refresh_open_orders_ts = now_ts
        self._order_tracker.prune_done(now_ts)
        try:
            book = self.get_order_book(self.trading_pair)
        except Exception:
            return
        for order in list(self._order_tracker.iter_open()):
            self._apply_fill(order, book, now_ts)

    def _submit_order(self, trading_pair: str, amount: Decimal, order_type: Any, side: Any, price: Decimal) -> str:
        now_ts = self._time()
        amount = max(Decimal("0"), to_decimal(amount))
        if amount <= 0:
            raise ValueError("amount must be positive")
        price = self._resolve_price(side, price)
        if price <= 0:
            self._paper_reject_count += 1
            oid = self._next_order_id(side)
            self.trigger_event(MarketEvent.OrderFailure, SimpleNamespace(order_id=oid, error_message="invalid_price"))
            return oid

        quantized_price = self.quantize_order_price(trading_pair, to_decimal(price))
        try:
            book = self.get_order_book(trading_pair)
            if side == TradeType.BUY:
                ask_entry = next(iter(book.ask_entries()), None)
                top_price = to_decimal(getattr(ask_entry, "price", 0)) if ask_entry else Decimal("0")
                crossed = top_price > 0 and quantized_price >= top_price
            else:
                bid_entry = next(iter(book.bid_entries()), None)
                top_price = to_decimal(getattr(bid_entry, "price", 0)) if bid_entry else Decimal("0")
                crossed = top_price > 0 and quantized_price <= top_price
        except Exception:
            crossed = False

        order = PaperOrder(
            order_id=self._next_order_id(side),
            trading_pair=trading_pair,
            trade_type=side,
            order_type=order_type,
            amount=self.quantize_order_amount(trading_pair, amount),
            price=quantized_price,
            creation_timestamp=now_ts,
            base_asset=self._base_asset,
            quote_asset=self._quote_asset,
            fee_asset=self._quote_asset,
            last_update_timestamp=now_ts,
            max_fills=max(1, int(self._config.max_fills_per_order)),
            crossed_at_creation=crossed,
        )

        if not self._reserve_for_order(order):
            self._paper_reject_count += 1
            order.current_state = "FAILED"
            self._order_tracker.track(order)
            self.trigger_event(MarketEvent.OrderFailure, SimpleNamespace(order_id=order.order_id, error_message="insufficient_balance"))
            return order.order_id

        self._order_tracker.track(order)
        if _HAS_FRAMEWORK_EVENTS:
            evt_cls = BuyOrderCreatedEvent if side == TradeType.BUY else SellOrderCreatedEvent
            created_event = evt_cls(
                timestamp=now_ts,
                type=order.order_type,
                trading_pair=trading_pair,
                amount=order.amount,
                price=order.price,
                order_id=order.order_id,
                creation_timestamp=order.creation_timestamp,
                exchange_order_id=None,
                leverage=1,
                position="NIL",
            )
        else:
            created_event = SimpleNamespace(
                order_id=order.order_id,
                trading_pair=trading_pair,
                amount=order.amount,
                price=order.price,
                timestamp=now_ts,
                creation_timestamp=now_ts,
                type=order.order_type,
                leverage=1,
                position="NIL",
                exchange_order_id=None,
                _asdict=lambda: {
                    "order_id": str(order.order_id),
                    "trading_pair": str(trading_pair),
                    "amount": str(order.amount),
                    "price": str(order.price),
                    "timestamp": float(now_ts),
                    "creation_timestamp": float(now_ts),
                },
            )
        if side == TradeType.BUY:
            self.trigger_event(MarketEvent.BuyOrderCreated, created_event)
        else:
            self.trigger_event(MarketEvent.SellOrderCreated, created_event)
        self.refresh_open_orders(force=True)
        return order.order_id

    def _reserve_for_order(self, order: PaperOrder) -> bool:
        if order.trade_type == TradeType.BUY:
            reserve_quote = order.amount * order.price
            if self._ledger.reserve(order.quote_asset, reserve_quote):
                order.reserved_quote = reserve_quote
                return True
            return False
        if self._ledger.reserve(order.base_asset, order.amount):
            order.reserved_base = order.amount
            return True
        return False

    def _apply_fill(self, order: PaperOrder, book: Any, now_ts: float) -> None:
        decision = self._fill_model.evaluate(order, book, now_ts)
        if decision.fill_qty <= 0:
            return
        remaining = max(Decimal("0"), order.amount - order.executed_amount_base)
        if remaining <= 0:
            return
        fill_qty = min(decision.fill_qty, remaining)
        if order.fill_count >= max(1, int(order.max_fills)) - 1:
            # Final fill on capped fill count: sweep remaining quantity.
            fill_qty = remaining
        fill_qty = self.quantize_order_amount(order.trading_pair, fill_qty)
        # If quantization produces dust, close the order in a single final sweep.
        if fill_qty <= 0:
            fill_qty = remaining
        min_fill_amount = self._min_fill_amount(order.trading_pair)
        min_fill_notional = self._min_fill_notional(order.trading_pair)
        min_fill_qty = max(min_fill_amount, Decimal("1e-10"))
        if fill_qty < remaining and fill_qty < min_fill_qty:
            return
        remaining_after_fill = max(Decimal("0"), remaining - fill_qty)
        if remaining_after_fill > 0:
            remaining_notional = remaining_after_fill * max(Decimal("0"), order.price)
            remaining_ratio = remaining_after_fill / order.amount if order.amount > 0 else Decimal("0")
            if (
                (min_fill_amount > 0 and remaining_after_fill <= min_fill_amount)
                or (min_fill_notional > 0 and remaining_notional <= min_fill_notional)
                or (remaining_ratio <= self._FINAL_SWEEP_REMAINING_PCT)
                or (remaining_after_fill <= Decimal("1e-12"))
            ):
                fill_qty = remaining
        if fill_qty <= 0:
            return
        fill_price = self.quantize_order_price(order.trading_pair, decision.fill_price)
        fill_quote = fill_qty * fill_price
        fee_bps = self._config.taker_fee_bps if decision.is_taker else self._config.maker_fee_bps
        fee_rate = max(Decimal("0"), fee_bps) / Decimal("10000")
        fee_quote = fill_quote * fee_rate

        if order.trade_type == TradeType.BUY:
            self._ledger.release(order.quote_asset, min(order.reserved_quote, fill_quote))
            self._ledger.credit(order.base_asset, fill_qty)
            self._ledger.debit(order.quote_asset, fill_quote + fee_quote)
            order.reserved_quote = max(Decimal("0"), order.reserved_quote - fill_quote)
        else:
            self._ledger.release(order.base_asset, min(order.reserved_base, fill_qty))
            self._ledger.debit(order.base_asset, fill_qty)
            self._ledger.credit(order.quote_asset, fill_quote - fee_quote)
            order.reserved_base = max(Decimal("0"), order.reserved_base - fill_qty)

        order.executed_amount_base += fill_qty
        order.executed_amount_quote += fill_quote
        order.cumulative_fee_paid_quote += fee_quote
        order.last_update_timestamp = now_ts
        order.fill_count += 1
        order.current_state = "FILLED" if order.executed_amount_base >= order.amount else "PARTIALLY_FILLED"

        self._paper_fill_count += 1
        self._paper_total_queue_delay_ms += decision.queue_delay_ms

        fill_event = self._build_fill_event(order, fill_price, fill_qty, fee_quote, now_ts, decision.is_taker)
        self.trigger_event(MarketEvent.OrderFilled, fill_event)
        if callable(self._on_fill):
            try:
                self._on_fill(fill_event)
            except Exception:
                logger.error("paper on_fill callback failed for order %s", order.order_id, exc_info=True)

        if order.current_state == "FILLED":
            completed_event = self._build_completed_event(order, now_ts)
            if order.trade_type == TradeType.BUY:
                self.trigger_event(MarketEvent.BuyOrderCompleted, completed_event)
            else:
                self.trigger_event(MarketEvent.SellOrderCompleted, completed_event)

    def _build_fill_event(self, order: PaperOrder, fill_price: Decimal, fill_qty: Decimal,
                          fee_quote: Decimal, now_ts: float, is_taker: bool) -> Any:
        if _HAS_FRAMEWORK_EVENTS:
            try:
                trade_fee = build_trade_fee(
                    exchange=_canonical_connector_name(self.connector_name),
                    is_maker=not is_taker,
                    base_currency=order.base_asset,
                    quote_currency=order.quote_asset,
                    order_type=order.order_type,
                    order_side=order.trade_type,
                    amount=fill_qty,
                    price=fill_price,
                )
                return OrderFilledEvent(
                    timestamp=now_ts,
                    order_id=order.order_id,
                    trading_pair=order.trading_pair,
                    trade_type=order.trade_type,
                    order_type=order.order_type,
                    price=fill_price,
                    amount=fill_qty,
                    trade_fee=trade_fee,
                    exchange_trade_id=f"paper-{uuid4().hex[:12]}",
                )
            except Exception:
                logger.warning("Framework fill event construction failed for %s, using fallback", order.order_id, exc_info=True)
        fee_obj = SimpleNamespace(
            fee_amount_in_token=lambda *args, **kwargs: fee_quote,
            is_maker=not is_taker,
        )
        fallback = SimpleNamespace(
            order_id=order.order_id,
            timestamp=now_ts,
            price=fill_price,
            amount=fill_qty,
            trade_type=order.trade_type,
            order_type=order.order_type,
            trading_pair=order.trading_pair,
            trade_fee=fee_obj,
            _asdict=lambda: {
                "order_id": str(order.order_id),
                "timestamp": float(now_ts),
                "price": str(fill_price),
                "amount": str(fill_qty),
                "trading_pair": str(order.trading_pair),
            },
        )
        return fallback

    @staticmethod
    def _build_completed_event(order: PaperOrder, now_ts: float) -> Any:
        if _HAS_FRAMEWORK_EVENTS:
            try:
                cls = BuyOrderCompletedEvent if order.trade_type == TradeType.BUY else SellOrderCompletedEvent
                return cls(
                    timestamp=now_ts,
                    order_id=order.order_id,
                    base_asset=order.base_asset,
                    quote_asset=order.quote_asset,
                    base_asset_amount=order.executed_amount_base,
                    quote_asset_amount=order.executed_amount_quote,
                    order_type=order.order_type,
                )
            except Exception:
                pass
        return SimpleNamespace(
            order_id=order.order_id,
            timestamp=now_ts,
            base_asset=order.base_asset,
            quote_asset=order.quote_asset,
            base_asset_amount=order.executed_amount_base,
            quote_asset_amount=order.executed_amount_quote,
        )

    def _resolve_price(self, side: Any, price: Decimal) -> Decimal:
        try:
            p = to_decimal(price)
            if p.is_nan():
                p = Decimal("0")
        except Exception:
            p = Decimal("0")
        if p > 0:
            return p
        ref_type = PriceType.BestAsk if side == TradeType.BUY else PriceType.BestBid
        try:
            return to_decimal(self._market_connector.get_price_by_type(self.trading_pair, ref_type))
        except Exception:
            return Decimal("0")

    @staticmethod
    def _safe_balance(connector: Any, asset: str) -> Decimal:
        if connector is None:
            return Decimal("0")
        try:
            return to_decimal(connector.get_balance(asset))
        except Exception:
            return Decimal("0")

    @staticmethod
    def _next_order_id(side: Any) -> str:
        prefix = "B" if side == TradeType.BUY else "S"
        return f"paper-{prefix}-{uuid4().hex[:12]}"

    def __getattr__(self, item: str) -> Any:
        # Keep compatibility with the connector surface used by Hummingbot executors.
        return getattr(self._paper_connector, item)


def install_paper_adapter(controller: Any, connector_name: str, trading_pair: str, cfg: PaperEngineConfig) -> Optional[PaperExecutionAdapter]:
    strategy = getattr(controller, "strategy", None) or getattr(controller, "_strategy", None)
    provider = getattr(controller, "market_data_provider", None)
    if strategy is None or provider is None:
        logger.info(
            "paper adapter skip for %s/%s: strategy_or_provider_missing strategy=%s provider=%s",
            connector_name,
            trading_pair,
            strategy is not None,
            provider is not None,
        )
        return None

    connectors = getattr(strategy, "connectors", None)
    if not isinstance(connectors, dict):
        logger.info("paper adapter skip for %s/%s: strategy.connectors missing", connector_name, trading_pair)
        return None

    paper_connector = connectors.get(connector_name)
    canonical_name = _canonical_connector_name(connector_name)
    market_connector = connectors.get(canonical_name)
    if market_connector is None:
        try:
            market_connector = provider.get_connector(canonical_name)
        except Exception:
            market_connector = None

    if paper_connector is None:
        try:
            paper_connector = provider.get_connector(connector_name)
        except Exception:
            paper_connector = market_connector
    if market_connector is None and paper_connector is not None:
        market_connector = paper_connector
    if paper_connector is None or market_connector is None:
        logger.info(
            "paper adapter skip for %s/%s: paper_connector=%s market_connector=%s available=%s canonical=%s",
            connector_name,
            trading_pair,
            paper_connector is not None,
            market_connector is not None,
            ",".join(sorted(connectors.keys())),
            canonical_name,
        )
        return None

    adapter = PaperExecutionAdapter(
        connector_name=connector_name,
        trading_pair=trading_pair,
        paper_connector=paper_connector,
        market_connector=market_connector,
        config=cfg,
        time_fn=lambda: float(provider.time()),
        on_fill=getattr(controller, "did_fill_order", None),
    )
    if not _install_native_connector_delegation(paper_connector=paper_connector, adapter=adapter):
        if not _install_strategy_order_delegation(
            strategy=strategy,
            connector_name=connector_name,
            adapter=adapter,
        ):
            logger.warning(
                "paper adapter delegation patch failed for %s/%s; keeping legacy replacement mode",
                connector_name,
                trading_pair,
            )
            connectors[connector_name] = adapter
    return adapter


def _install_native_connector_delegation(paper_connector: Any, adapter: PaperExecutionAdapter) -> bool:
    """
    Keep the native PaperTradeExchange instance in place and monkey-patch selected execution
    methods to delegate to PaperExecutionAdapter. This preserves Hummingbot-native event wiring
    and fill accounting paths while using internal fill simulation.
    """
    if paper_connector is None:
        return False
    if getattr(paper_connector, "_epp_internal_paper_delegate_installed", False):
        return True

    originals = {}

    def _capture(name: str):
        originals[name] = getattr(paper_connector, name, None)

    for method_name in (
        "buy",
        "sell",
        "cancel",
        "get_order_book",
        "get_price_by_type",
        "get_balance",
        "get_available_balance",
        "quantize_order_amount",
        "quantize_order_price",
    ):
        _capture(method_name)

    def _delegate_buy(self, trading_pair, amount, order_type, price, *args, **kwargs):
        return adapter.buy(trading_pair, amount, order_type, price, *args, **kwargs)

    def _delegate_sell(self, trading_pair, amount, order_type, price, *args, **kwargs):
        return adapter.sell(trading_pair, amount, order_type, price, *args, **kwargs)

    def _delegate_cancel(self, trading_pair, client_order_id, *args, **kwargs):
        return adapter.cancel(trading_pair, client_order_id)

    def _delegate_get_order_book(self, trading_pair, *args, **kwargs):
        return adapter.get_order_book(trading_pair)

    def _delegate_get_price_by_type(self, trading_pair, price_type=PriceType.MidPrice, *args, **kwargs):
        return adapter.get_price_by_type(trading_pair, price_type)

    def _delegate_get_balance(self, asset, *args, **kwargs):
        return adapter.get_balance(asset)

    def _delegate_get_available_balance(self, asset, *args, **kwargs):
        return adapter.get_available_balance(asset)

    def _delegate_quantize_amount(self, trading_pair, amount, *args, **kwargs):
        return adapter.quantize_order_amount(trading_pair, amount)

    def _delegate_quantize_price(self, trading_pair, price, *args, **kwargs):
        return adapter.quantize_order_price(trading_pair, price)

    try:
        paper_connector.buy = MethodType(_delegate_buy, paper_connector)
        paper_connector.sell = MethodType(_delegate_sell, paper_connector)
        paper_connector.cancel = MethodType(_delegate_cancel, paper_connector)
        paper_connector.get_order_book = MethodType(_delegate_get_order_book, paper_connector)
        paper_connector.get_price_by_type = MethodType(_delegate_get_price_by_type, paper_connector)
        paper_connector.get_balance = MethodType(_delegate_get_balance, paper_connector)
        paper_connector.get_available_balance = MethodType(_delegate_get_available_balance, paper_connector)
        paper_connector.quantize_order_amount = MethodType(_delegate_quantize_amount, paper_connector)
        paper_connector.quantize_order_price = MethodType(_delegate_quantize_price, paper_connector)

        # V2 executor compatibility: keep native connector instance, provide adapter internals.
        paper_connector._order_tracker = adapter._order_tracker
        paper_connector._epp_internal_paper_adapter = adapter
        paper_connector._epp_internal_paper_delegate_originals = originals
        paper_connector._epp_internal_paper_delegate_installed = True
        return True
    except Exception:
        logger.error("failed to install native paper connector delegation", exc_info=True)
        try:
            for name, original in originals.items():
                if original is not None:
                    setattr(paper_connector, name, original)
        except Exception:
            pass
        return False


def install_paper_adapter_on_connector(paper_connector: Any, adapter: PaperExecutionAdapter) -> bool:
    return _install_native_connector_delegation(paper_connector=paper_connector, adapter=adapter)


def install_paper_adapter_on_strategy(strategy: Any, connector_name: str, adapter: PaperExecutionAdapter) -> bool:
    return _install_strategy_order_delegation(strategy=strategy, connector_name=connector_name, adapter=adapter)


def _install_strategy_order_delegation(strategy: Any, connector_name: str, adapter: PaperExecutionAdapter) -> bool:
    """
    Fallback for Cython connectors with read-only methods: keep native connector in place and
    patch strategy buy/sell/cancel dispatch to route this connector through PaperExecutionAdapter.
    """
    if strategy is None:
        return False
    if getattr(strategy, "_epp_internal_paper_order_delegate_installed", False) is False:
        original_buy = getattr(strategy, "buy", None)
        original_sell = getattr(strategy, "sell", None)
        original_cancel = getattr(strategy, "cancel", None)
        if not callable(original_buy) or not callable(original_sell) or not callable(original_cancel):
            return False

        def _patched_buy(self, conn_name, trading_pair, amount, order_type, price=Decimal("NaN"), position_action=None):
            adapters = getattr(self, "_epp_internal_paper_adapters", {})
            delegate = adapters.get(conn_name)
            if delegate is not None:
                return delegate.buy(trading_pair, amount, order_type, price, position_action=position_action)
            return original_buy(conn_name, trading_pair, amount, order_type, price, position_action=position_action)

        def _patched_sell(self, conn_name, trading_pair, amount, order_type, price=Decimal("NaN"), position_action=None):
            adapters = getattr(self, "_epp_internal_paper_adapters", {})
            delegate = adapters.get(conn_name)
            if delegate is not None:
                return delegate.sell(trading_pair, amount, order_type, price, position_action=position_action)
            return original_sell(conn_name, trading_pair, amount, order_type, price, position_action=position_action)

        def _patched_cancel(self, conn_name, trading_pair, order_id):
            adapters = getattr(self, "_epp_internal_paper_adapters", {})
            delegate = adapters.get(conn_name)
            if delegate is not None:
                return delegate.cancel(trading_pair, order_id)
            return original_cancel(conn_name, trading_pair, order_id)

        try:
            strategy.buy = MethodType(_patched_buy, strategy)
            strategy.sell = MethodType(_patched_sell, strategy)
            strategy.cancel = MethodType(_patched_cancel, strategy)
            strategy._epp_internal_paper_order_delegate_installed = True
        except Exception:
            logger.error("failed to install strategy-level order delegation", exc_info=True)
            return False

    adapters = getattr(strategy, "_epp_internal_paper_adapters", None)
    if not isinstance(adapters, dict):
        adapters = {}
        strategy._epp_internal_paper_adapters = adapters
    adapters[connector_name] = adapter
    return True


def enable_framework_paper_compat_fallbacks() -> None:
    """
    Last-resort compatibility shims for HB builds where PaperTradeExchange does not
    expose `trading_rules` / `_order_tracker` in the shape V2 executors require.
    """
    # 1) MarketDataProvider in some builds cannot resolve "*_paper_trade" as a
    # real connector module for non-trading connectors. Map to canonical name.
    try:
        from hummingbot.data_feed.market_data_provider import MarketDataProvider as _MDP
    except Exception:
        _MDP = None
    if _MDP is not None and not getattr(_MDP, "_epp_paper_create_fallback_enabled", False):
        try:
            _orig_create_non_trading = _MDP._create_non_trading_connector

            def _safe_create_non_trading(self, connector_name: str):
                canonical_name = _canonical_connector_name(connector_name)
                return _orig_create_non_trading(self, canonical_name)

            _MDP._create_non_trading_connector = _safe_create_non_trading
            _MDP._epp_paper_create_fallback_enabled = True
        except Exception:
            pass

    # 2) V2 executor trading-rules fallback. Avoid mutating PaperTradeExchange
    # class directly (immutable Cython type in some HB builds).
    try:
        from hummingbot.strategy_v2.executors.executor_base import ExecutorBase as _ExecutorBase
    except Exception:
        _ExecutorBase = None
    if _ExecutorBase is not None and not getattr(_ExecutorBase, "_epp_trading_rules_fallback_enabled", False):
        _orig_get_trading_rules = _ExecutorBase.get_trading_rules

        def _extract_rule(obj, trading_pair: str):
            if obj is None:
                return None
            try:
                for attr in ("trading_rules", "_trading_rules"):
                    rules = getattr(obj, attr, None)
                    if isinstance(rules, dict) and trading_pair in rules:
                        return rules[trading_pair]
            except Exception:
                return None
            return None

        def _safe_get_trading_rules(self, connector_name: str, trading_pair: str):
            connector = self.connectors.get(connector_name)
            direct = _extract_rule(connector, trading_pair)
            if direct is not None:
                return direct

            canonical_name = _canonical_connector_name(connector_name)
            canonical_connector = self.connectors.get(canonical_name)
            canonical = _extract_rule(canonical_connector, trading_pair)
            if canonical is not None:
                return canonical

            try:
                provider = getattr(self.strategy, "market_data_provider", None)
                if provider is not None:
                    runtime = provider.get_connector(canonical_name)
                    runtime_rule = _extract_rule(runtime, trading_pair)
                    if runtime_rule is not None:
                        return runtime_rule
            except Exception:
                pass

            for attr in ("_exchange", "exchange", "_connector", "connector", "_real_connector", "_client"):
                wrapped = getattr(connector, attr, None) if connector is not None else None
                wrapped_rule = _extract_rule(wrapped, trading_pair)
                if wrapped_rule is not None:
                    return wrapped_rule

            # Never hard crash controller loop; keep executor creation alive.
            return SimpleNamespace(
                trading_pair=trading_pair,
                min_order_size=Decimal("0"),
                min_base_amount=Decimal("0"),
                min_amount=Decimal("0"),
                min_notional_size=Decimal("0"),
                min_notional=Decimal("0"),
                min_order_value=Decimal("0"),
                min_base_amount_increment=Decimal("0"),
                min_order_size_increment=Decimal("0"),
                amount_step=Decimal("0"),
                min_price_increment=Decimal("0"),
                min_price_tick_size=Decimal("0"),
                price_step=Decimal("0"),
                min_price_step=Decimal("0"),
            )

        _ExecutorBase.get_trading_rules = _safe_get_trading_rules
        _ExecutorBase._epp_trading_rules_fallback_enabled = True

    # 3) In-flight lookup fallback.
    if _ExecutorBase is not None and not getattr(_ExecutorBase, "_epp_inflight_fallback_enabled", False):
        _orig_get_in_flight_order = _ExecutorBase.get_in_flight_order

        def _safe_get_in_flight_order(self, connector_name: str, order_id: str):
            connector = self.connectors.get(connector_name)
            if connector is None:
                return _orig_get_in_flight_order(self, connector_name, order_id)
            tracker = getattr(connector, "_order_tracker", None)
            if tracker is None:
                return None
            try:
                return tracker.fetch_order(client_order_id=order_id)
            except Exception:
                return None

        _ExecutorBase.get_in_flight_order = _safe_get_in_flight_order
        _ExecutorBase._epp_inflight_fallback_enabled = True
