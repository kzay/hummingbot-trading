"""HB event firing and EventSubscriber protocol for the paper engine bridge.

Extracted from hb_bridge.py (DEBT-3). The ``fire_hb_events`` entry point
receives ``bridge_state`` as a parameter to avoid circular imports.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Protocol

from controllers.paper_engine_v2.desk import PaperDesk
from controllers.paper_engine_v2.types import (
    EngineEvent,
    OrderCanceled,
    OrderFilled,
    OrderRejected,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EventSubscriber protocol (Phase 5: clean decoupled event routing)
# ---------------------------------------------------------------------------

class EventSubscriber(Protocol):
    """Adapter-style subscriber that receives desk engine events.

    Implement this protocol to receive events from the bridge without
    relying on HB monkey-patching. Useful for:
    - Testing without HB (inject a TestSubscriber)
    - Custom loggers / analytics subscribers
    - Future non-HB connectors

    The bridge calls on_fill / on_cancel / on_reject for each event.
    Implementations should never raise; errors are caught and logged.
    """

    def on_fill(self, event: OrderFilled, connector_name: str) -> None: ...
    def on_cancel(self, event: OrderCanceled, connector_name: str) -> None: ...
    def on_reject(self, event: OrderRejected, connector_name: str) -> None: ...


_EVENT_SUBSCRIBERS: List[EventSubscriber] = []


def register_event_subscriber(subscriber: EventSubscriber) -> None:
    """Register a subscriber to receive desk events via clean protocol."""
    _EVENT_SUBSCRIBERS.append(subscriber)


def unregister_event_subscriber(subscriber: EventSubscriber) -> None:
    """Remove a previously registered subscriber."""
    try:
        _EVENT_SUBSCRIBERS.remove(subscriber)
    except ValueError:
        pass


def _dispatch_to_subscribers(event: EngineEvent, connector_name: str) -> None:
    """Dispatch a desk event to all registered EventSubscribers."""
    if not _EVENT_SUBSCRIBERS:
        return
    for sub in _EVENT_SUBSCRIBERS:
        try:
            if isinstance(event, OrderFilled):
                sub.on_fill(event, connector_name)
            elif isinstance(event, OrderCanceled):
                sub.on_cancel(event, connector_name)
            elif isinstance(event, OrderRejected):
                sub.on_reject(event, connector_name)
        except Exception as exc:
            logger.warning("EventSubscriber %s error: %s", type(sub).__name__, exc)


def _find_controller_for_connector(strategy: Any, connector_name: str) -> Any:
    """Find the controller that owns this connector_name."""
    controllers = getattr(strategy, "controllers", {})
    for _, ctrl in controllers.items():
        cfg = getattr(ctrl, "config", None)
        if cfg and str(getattr(cfg, "connector_name", "")) == connector_name:
            return ctrl
    return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _realized_pnl_delta_quote(controller: Any, before_value: float) -> float:
    """Compute realized PnL delta from controller state before/after fill handling."""
    if controller is None:
        return 0.0
    after_value = _safe_float(getattr(controller, "_realized_pnl_today", before_value), before_value)
    return after_value - before_value


def _fire_hb_events(strategy: Any, connector_name: str, event: Any, bridge_state: Any) -> None:
    """Convert v2 event to HB event and fire on the correct controller.

    The controller's did_fill_order() writes to fills.csv and updates
    minute.csv — this is what Grafana reads. Without this, fills are
    invisible to the dashboard regardless of paper/live mode.

    Phase 5: Dispatches to registered EventSubscribers FIRST (clean path),
    then falls through to the legacy HB monkey-patch path.
    """
    if event is None:
        return

    _dispatch_to_subscribers(event, connector_name)

    try:
        if isinstance(event, OrderFilled):
            _fire_fill_event(strategy, connector_name, event, bridge_state)
        elif isinstance(event, OrderCanceled):
            _fire_cancel_event(strategy, connector_name, event)
        elif isinstance(event, OrderRejected):
            _fire_reject_event(strategy, connector_name, event)
    except Exception as exc:
        logger.warning("HB event fire failed: %s", exc, exc_info=True)


def _fire_fill_event(strategy: Any, connector_name: str, fill_event: OrderFilled, bridge_state: Any) -> None:
    """Fire fill event directly to the controller's did_fill_order().

    This is the critical path: controller.did_fill_order() writes to
    fills.csv, updates daily counters, and feeds Grafana.
    """
    try:
        from hummingbot.core.event.events import OrderFilledEvent as HBOrderFilledEvent  # type: ignore
        from hummingbot.core.data_type.common import TradeType  # type: ignore

        trade_type = TradeType.BUY  # default
        side_hint = ""
        bridges = getattr(strategy, "_paper_desk_v2_bridges", {})
        bridge = bridges.get(connector_name)
        if bridge:
            _desk: PaperDesk = bridge["desk"]
            for key, engine in _desk._engines.items():
                side_str = engine.get_order_side(fill_event.order_id)
                if side_str:
                    side_hint = str(side_str).strip().lower()
                    trade_type = TradeType.BUY if side_hint == "buy" else TradeType.SELL
                    break
        if not side_hint:
            runtime_orders = getattr(strategy, "_paper_exchange_runtime_orders", None)
            if isinstance(runtime_orders, dict):
                for bucket in runtime_orders.values():
                    if not isinstance(bucket, dict):
                        continue
                    runtime_order = bucket.get(fill_event.order_id)
                    if runtime_order is None:
                        continue
                    runtime_side = str(getattr(runtime_order, "trade_type", "")).strip().lower()
                    if runtime_side in {"buy", "sell"}:
                        side_hint = runtime_side
                        break
        if side_hint in {"buy", "sell"}:
            trade_type = TradeType.BUY if side_hint == "buy" else TradeType.SELL

        now = time.time()

        try:
            from hummingbot.core.event.events import TradeFee, TokenAmount
            fee = TradeFee(
                percent=Decimal("0"),
                flat_fees=[TokenAmount(fill_event.instrument_id.quote_asset, fill_event.fee)],
            )
        except Exception:
            fee = SimpleNamespace(
                percent=Decimal("0"),
                flat_fees=[],
                fee_amount_in_token=lambda *a, **k: fill_event.fee,
                is_maker=fill_event.is_maker,
            )

        hb_fill = HBOrderFilledEvent(
            timestamp=now,
            order_id=fill_event.order_id,
            trading_pair=fill_event.instrument_id.trading_pair,
            trade_type=trade_type,
            order_type=None,
            price=fill_event.fill_price,
            amount=fill_event.fill_quantity,
            trade_fee=fee,
        )
        try:
            setattr(hb_fill, "position_action", str(getattr(fill_event, "position_action", "auto") or "auto"))
        except Exception:
            pass

        controller = _find_controller_for_connector(strategy, connector_name)
        realized_before = _safe_float(getattr(controller, "_realized_pnl_today", 0.0), 0.0)
        if controller and hasattr(controller, "did_fill_order"):
            try:
                controller.did_fill_order(hb_fill)
            except Exception as exc:
                logger.warning("Controller did_fill_order failed: %s", exc, exc_info=True)
        realized_pnl_quote = _realized_pnl_delta_quote(controller, realized_before)

        # Publish fill to hb.bot_telemetry.v1 via Redis so the event_store
        # service ingests paper fills the same way it ingests live fills.
        # Falls back to direct JSONL write when Redis is unavailable.
        try:
            instance_name = str(getattr(getattr(controller, "config", None), "instance_name", "") or "")
            controller_id = str(getattr(controller, "id", "") or getattr(controller, "controller_id", "") or "")
            is_maker_val = bool(getattr(fill_event, "is_maker", False))
            side_str = "buy" if trade_type == TradeType.BUY else "sell"

            from datetime import datetime, timezone as _tz
            from pathlib import Path
            import json as _json
            import os as _os
            import uuid as _uuid_mod

            _redis_published = False
            try:
                _r = bridge_state.get_redis()
                if _r is not None:
                    _payload = {
                        "event_id": str(_uuid_mod.uuid4()),
                        "event_type": "bot_fill",
                        "event_version": "v1",
                        "schema_version": "1.0",
                        "ts_utc": datetime.now(_tz.utc).isoformat(),
                        "producer": "hb.paper_engine_v2",
                        "instance_name": instance_name,
                        "controller_id": controller_id,
                        "connector_name": str(connector_name),
                        "trading_pair": str(fill_event.instrument_id.trading_pair),
                        "side": side_str,
                        "price": float(fill_event.fill_price),
                        "amount_base": float(fill_event.fill_quantity),
                        "notional_quote": float(fill_event.fill_price * fill_event.fill_quantity),
                        "fee_quote": float(fill_event.fee),
                        "order_id": str(fill_event.order_id),
                        "accounting_source": "paper_desk_v2",
                        "is_maker": is_maker_val,
                        "realized_pnl_quote": float(realized_pnl_quote),
                        "bot_state": "",
                        "correlation_id": str(getattr(fill_event, "event_id", "") or ""),
                    }
                    _r.xadd(
                        "hb.bot_telemetry.v1",
                        {"payload": _json.dumps(_payload)},
                        maxlen=100_000,
                        approximate=True,
                    )
                    _redis_published = True
            except Exception:
                logger.debug("Paper fill telemetry publish failed for order %s", fill_event.order_id, exc_info=True)

            if not _redis_published:
                root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
                out_dir = root / "reports" / "event_store"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / f"events_{datetime.now(_tz.utc).strftime('%Y%m%d')}.jsonl"
                envelope = {
                    "event_id": str(_uuid_mod.uuid4()),
                    "event_type": "bot_fill",
                    "event_version": "v1",
                    "ts_utc": datetime.now(_tz.utc).isoformat(),
                    "producer": "hb.paper_engine_v2",
                    "instance_name": instance_name,
                    "controller_id": controller_id,
                    "connector_name": str(connector_name),
                    "trading_pair": str(fill_event.instrument_id.trading_pair),
                    "correlation_id": str(getattr(fill_event, "event_id", "") or ""),
                    "stream": "local.paper_engine_v2.fallback",
                    "stream_entry_id": "",
                    "accounting_source": "paper_desk_v2",
                    "payload": {
                        "order_id": str(fill_event.order_id),
                        "side": side_str,
                        "price": float(fill_event.fill_price),
                        "amount_base": float(fill_event.fill_quantity),
                        "fee_quote": float(fill_event.fee),
                        "is_maker": is_maker_val,
                        "realized_pnl_quote": float(realized_pnl_quote),
                    },
                    "ingest_ts_utc": datetime.now(_tz.utc).isoformat(),
                    "schema_validation_status": "ok",
                }
                with out_path.open("a", encoding="utf-8") as f:
                    f.write(_json.dumps(envelope, ensure_ascii=True) + "\n")
        except Exception:
            pass

        if hasattr(strategy, "did_fill_order"):
            try:
                strategy.did_fill_order(hb_fill)
            except Exception:
                pass

    except Exception as exc:
        logger.warning("Fill event fire failed: %s", exc, exc_info=True)


def _fire_cancel_event(strategy: Any, connector_name: str, cancel_event: OrderCanceled) -> None:
    """Fire cancel event to controller."""
    try:
        from hummingbot.core.event.events import OrderCancelledEvent as HBCancelEvent
        hb_cancel = HBCancelEvent(
            timestamp=time.time(),
            order_id=cancel_event.order_id,
        )
        controller = _find_controller_for_connector(strategy, connector_name)
        if controller and hasattr(controller, "did_cancel_order"):
            controller.did_cancel_order(hb_cancel)
    except Exception as exc:
        logger.debug("Cancel event fire failed: %s", exc)


def _fire_reject_event(strategy: Any, connector_name: str, reject_event: OrderRejected) -> None:
    """Fire reject event to controller."""
    try:
        from hummingbot.core.event.events import MarketOrderFailureEvent as HBFailEvent
        hb_fail = HBFailEvent(
            timestamp=time.time(),
            order_id=reject_event.order_id,
            order_type=None,
            error_message=reject_event.reason,
        )
        controller = _find_controller_for_connector(strategy, connector_name)
        if controller and hasattr(controller, "did_fail_order"):
            controller.did_fail_order(hb_fail)
    except Exception as exc:
        logger.debug("Reject event fire failed: %s", exc)
