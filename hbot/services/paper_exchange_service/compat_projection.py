"""Compatibility projection for state and pair snapshots.

Projects PaperDesk internal state into the legacy JSON snapshot formats
consumed by: hb_bridge (order hydration), realtime_ui_api (fallback),
ops_db_writer (open-order ingestion), and promotion-gate scripts.

Critical: DeskStateStore does NOT persist open orders, so this layer
derives the ``orders`` section from live PaperDesk engine state.

Fee defaults for projected orders use the same env vars as
``instrument_registry`` to stay in sync.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

_DEFAULT_MAKER_FEE = float(os.getenv("PAPER_EXCHANGE_DEFAULT_MAKER_FEE_PCT", "0.0002"))
_DEFAULT_TAKER_FEE = float(os.getenv("PAPER_EXCHANGE_DEFAULT_TAKER_FEE_PCT", "0.0006"))

if TYPE_CHECKING:
    from simulation.desk import PaperDesk
    from simulation.types import PaperOrder, PaperPosition

logger = logging.getLogger(__name__)


def _now_utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_json_atomic(path: Path, payload: dict[str, Any], *, retries: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, default=str)
    attempts = max(1, int(retries))
    last_error: Exception | None = None
    for attempt in range(attempts):
        nonce = f"{os.getpid()}-{int(time.time() * 1_000_000)}-{attempt}"
        temp_path = path.with_name(f".{path.name}.{nonce}.tmp")
        try:
            temp_path.write_text(body, encoding="utf-8")
            temp_path.replace(path)
            return
        except Exception as exc:
            last_error = exc
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass  # best-effort temp cleanup — nothing to do if unlink fails
            if isinstance(exc, (PermissionError, FileNotFoundError)) and attempt + 1 < attempts:
                path.parent.mkdir(parents=True, exist_ok=True)
                time.sleep(0.01 * float(attempt + 1))
                continue
            break
    if last_error is not None:
        raise last_error


def _ns_to_ms(ns: int) -> int:
    return max(0, ns // 1_000_000)


@dataclass
class TenantProjectionInput:
    """Everything needed to project one tenant's state."""
    instance_name: str
    connector_name: str
    desk: PaperDesk


def _order_to_snapshot_dict(
    order: PaperOrder,
    instance_name: str,
    connector_name: str,
) -> dict[str, Any]:
    """Project a PaperOrder into the legacy OrderRecord-compatible dict."""
    from simulation.types import PositionAction

    pair = order.instrument_id.trading_pair
    ns_key = f"{instance_name}::{connector_name}::{pair}"
    ns_order_key = f"{ns_key}::{order.order_id}"

    pa = order.position_action
    if isinstance(pa, PositionAction):
        pa_str = pa.value
    else:
        pa_str = str(pa or "auto")

    return {
        "order_id": order.order_id,
        "instance_name": instance_name,
        "connector_name": connector_name,
        "trading_pair": pair,
        "side": order.side.value if hasattr(order.side, "value") else str(order.side),
        "order_type": order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type),
        "amount_base": float(order.quantity),
        "price": float(order.price),
        "time_in_force": "gtc",
        "reduce_only": bool(order.reduce_only),
        "post_only": False,
        "state": _map_order_status(order.status),
        "created_ts_ms": _ns_to_ms(order.created_at_ns),
        "updated_ts_ms": _ns_to_ms(order.updated_at_ns),
        "last_command_event_id": "",
        "last_fill_snapshot_event_id": "",
        "first_fill_ts_ms": 0,
        "last_fill_amount_base": 0.0,
        "filled_base": float(order.filled_quantity),
        "filled_quote": float(order.filled_notional),
        "fill_count": order.fill_count,
        "filled_fee_quote": float(order.cumulative_fee),
        "margin_reserve_quote": 0.0,
        "maker_fee_pct": _DEFAULT_MAKER_FEE,
        "taker_fee_pct": _DEFAULT_TAKER_FEE,
        "leverage": 1.0,
        "margin_mode": "leveraged",
        "funding_rate": 0.0,
        "position_action": pa_str,
        "position_mode": str(order.position_mode or "ONEWAY"),
        "namespace_key": ns_key,
        "namespace_order_key": ns_order_key,
    }


def _map_order_status(status: Any) -> str:
    """Map PE v2 OrderStatus to legacy state strings."""
    s = str(status.value if hasattr(status, "value") else status).lower()
    mapping = {
        "pending_submit": "working",
        "open": "working",
        "partial": "working",
        "filled": "filled",
        "canceled": "cancelled",
        "rejected": "rejected",
        "expired": "cancelled",
    }
    return mapping.get(s, s)


def _position_to_snapshot_dict(
    pos: PaperPosition,
    instance_name: str,
    connector_name: str,
) -> dict[str, Any]:
    """Project a PaperPosition into the legacy PositionRecord-compatible dict."""
    pair = pos.instrument_id.trading_pair
    pos.ensure_leg_consistency()
    pos.sync_derived_fields()

    return {
        "instance_name": instance_name,
        "connector_name": connector_name,
        "trading_pair": pair,
        "position_mode": str(pos.position_mode or "ONEWAY"),
        "long_base": float(pos.long_quantity),
        "long_avg_entry_price": float(pos.long_avg_entry_price),
        "short_base": float(pos.short_quantity),
        "short_avg_entry_price": float(pos.short_avg_entry_price),
        "realized_pnl_quote": float(pos.realized_pnl),
        "funding_paid_quote": float(pos.funding_paid),
        "last_fill_ts_ms": _ns_to_ms(pos.last_fill_at_ns),
        "last_funding_ts_ms": 0,
        "last_funding_rate": 0.0,
        "funding_event_count": 0,
    }


def project_state_snapshot(
    tenants: list[TenantProjectionInput],
    path: Path,
) -> None:
    """Write ``paper_exchange_state_snapshot_latest.json``.

    Includes open orders (derived from live desk engines) and positions
    (from desk portfolio).
    """
    all_orders: dict[str, dict[str, Any]] = {}
    all_positions: dict[str, dict[str, Any]] = {}

    for t in tenants:
        desk = t.desk
        for key, engine in desk._engines.items():
            for order in engine._orders.values():
                d = _order_to_snapshot_dict(order, t.instance_name, t.connector_name)
                all_orders[order.order_id] = d

        for ikey, pos in desk.portfolio._positions.items():
            if pos.quantity == Decimal("0") and pos.long_quantity == Decimal("0") and pos.short_quantity == Decimal("0"):
                continue
            ns_key = f"{t.instance_name}::{t.connector_name}::{pos.instrument_id.trading_pair}"
            all_positions[ns_key] = _position_to_snapshot_dict(pos, t.instance_name, t.connector_name)

    payload: dict[str, Any] = {
        "ts_utc": _now_utc_iso(),
        "orders_total": len(all_orders),
        "orders": all_orders,
        "positions_total": len(all_positions),
        "positions": all_positions,
        "funding_summary": {
            "positions_with_exposure": len(all_positions),
            "funding_events_generated": 0,
            "funding_debit_events": 0,
            "funding_credit_events": 0,
            "funding_paid_quote_total": 0.0,
        },
    }
    _write_json_atomic(path, payload)


def project_pair_snapshot(
    pairs_data: dict[str, dict[str, Any]],
    path: Path,
) -> None:
    """Write ``paper_exchange_pair_snapshot_latest.json``."""
    payload: dict[str, Any] = {
        "ts_utc": _now_utc_iso(),
        "pairs_total": len(pairs_data),
        "pairs": pairs_data,
    }
    _write_json_atomic(path, payload)
