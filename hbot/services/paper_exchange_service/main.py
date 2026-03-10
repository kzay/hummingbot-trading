from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from services.common.canonical_market_state import (
    market_payload_freshness_ts_ms,
    market_payload_order_key,
    parse_canonical_market_state,
)
from services.contracts.event_schemas import (
    AuditEvent,
    PaperExchangeCommandEvent,
    PaperExchangeEvent,
    PaperExchangeHeartbeatEvent,
)
from services.contracts.event_identity import validate_event_identity
from services.contracts.stream_names import (
    AUDIT_STREAM,
    MARKET_DATA_STREAM,
    MARKET_QUOTE_STREAM,
    PAPER_EXCHANGE_COMMAND_STREAM,
    PAPER_EXCHANGE_EVENT_STREAM,
    PAPER_EXCHANGE_HEARTBEAT_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient
from services.paper_exchange_service.order_fsm import (
    ACTIVE_ORDER_STATES as _ACTIVE_ORDER_STATES,
    TERMINAL_ORDER_STATES as _TERMINAL_ORDER_STATES,
    can_transition_state,
    is_immediate_tif,
    resolve_crossing_limit_order_outcome,
)

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def _canonical_connector_name(value: str) -> str:
    raw = str(value or "").strip()
    if not raw.endswith("_paper_trade"):
        return raw
    try:
        from services.common.exchange_profiles import resolve_profile

        profile = resolve_profile(raw)
        if isinstance(profile, dict):
            required_exchange = str(profile.get("requires_paper_trade_exchange", "") or "").strip()
            if required_exchange:
                return required_exchange
    except Exception:
        pass
    return raw[:-12]


def _normalize_connector_name(value: str) -> str:
    return _normalize(_canonical_connector_name(value))


def _csv_set(value: str) -> Set[str]:
    return {_normalize(x) for x in str(value or "").split(",") if _normalize(x)}


def _namespace_base_key(instance_name: str, connector_name: str, trading_pair: str) -> str:
    return (
        f"{_normalize(instance_name)}::"
        f"{_normalize_connector_name(connector_name)}::"
        f"{str(trading_pair or '').strip().upper()}"
    )


def _namespace_order_key(instance_name: str, connector_name: str, trading_pair: str, order_id: str) -> str:
    return f"{_namespace_base_key(instance_name, connector_name, trading_pair)}::{str(order_id or '').strip()}"


def _pair_key(instance_name: str, connector_name: str, trading_pair: str) -> str:
    return _namespace_base_key(instance_name, connector_name, trading_pair)


def _get_pair_snapshot(
    state: "PaperExchangeState",
    instance_name: str,
    connector_name: str,
    trading_pair: str,
) -> Optional["PairSnapshot"]:
    exact = state.pairs.get(_pair_key(instance_name, connector_name, trading_pair))
    shared = state.pairs.get(_pair_key("", connector_name, trading_pair))
    if exact is None:
        return shared
    if shared is None:
        return exact
    return shared if int(shared.freshness_ts_ms) >= int(exact.freshness_ts_ms) else exact


def _resolve_path(path_value: str, root: Path) -> Path:
    path = Path(str(path_value or "").strip() or "reports/verification/paper_exchange_command_journal_latest.json")
    if not path.is_absolute():
        path = root / path
    return path


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _load_command_journal(path: Path) -> Dict[str, Dict[str, object]]:
    payload = _read_json(path)
    commands = payload.get("commands", {})
    if not isinstance(commands, dict):
        return {}
    out: Dict[str, Dict[str, object]] = {}
    for command_event_id, record in commands.items():
        if isinstance(record, dict):
            out[str(command_event_id)] = dict(record)
    return out


def _write_json_atomic(path: Path, payload: Dict[str, object], *, retries: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2)
    attempts = max(1, int(retries))
    last_error: Optional[Exception] = None
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
                pass
            if isinstance(exc, (PermissionError, FileNotFoundError)) and attempt + 1 < attempts:
                path.parent.mkdir(parents=True, exist_ok=True)
                time.sleep(0.01 * float(attempt + 1))
                continue
            break
    if last_error is not None:
        raise last_error


def _persist_command_journal(path: Path, command_results_by_id: Dict[str, Dict[str, object]]) -> None:
    payload = {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "command_count": len(command_results_by_id),
        "commands": command_results_by_id,
    }
    _write_json_atomic(path, payload)


def _load_market_fill_journal(path: Path) -> Dict[str, int]:
    payload = _read_json(path)
    raw_events = payload.get("events", {})
    if not isinstance(raw_events, dict):
        return {}
    out: Dict[str, int] = {}
    for event_id, marker in raw_events.items():
        event_key = str(event_id or "").strip()
        if not event_key:
            continue
        try:
            seq = int(marker)
        except Exception:
            seq = 0
        out[event_key] = max(0, seq)
    return out


def _trim_market_fill_journal(events_by_id: Dict[str, int], max_entries: int) -> None:
    limit = max(1, int(max_entries))
    overflow = len(events_by_id) - limit
    if overflow <= 0:
        return
    sorted_items = sorted(events_by_id.items(), key=lambda item: (int(item[1]), str(item[0])))
    for event_id, _marker in sorted_items[:overflow]:
        events_by_id.pop(str(event_id), None)


def _persist_market_fill_journal(path: Path, market_fill_events_by_id: Dict[str, int], max_entries: int) -> None:
    trimmed_events = dict(market_fill_events_by_id)
    _trim_market_fill_journal(trimmed_events, max_entries=max_entries)
    payload = {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event_count": len(trimmed_events),
        "max_seq": max(trimmed_events.values()) if trimmed_events else 0,
        "events": trimmed_events,
    }
    _write_json_atomic(path, payload)


def _command_result_record(
    event: PaperExchangeEvent,
    *,
    audit_required: bool = False,
    audit_published: bool = True,
    command_metadata: Optional[Dict[str, str]] = None,
    command_producer: str = "",
    producer_authorized: bool = True,
) -> Dict[str, object]:
    namespace_key = _namespace_base_key(event.instance_name, event.connector_name, event.trading_pair)
    namespace_order_key = (
        _namespace_order_key(event.instance_name, event.connector_name, event.trading_pair, str(event.order_id or ""))
        if str(event.order_id or "").strip()
        else ""
    )
    return {
        "instance_name": event.instance_name,
        "command": event.command,
        "status": event.status,
        "reason": event.reason,
        "connector_name": event.connector_name,
        "trading_pair": event.trading_pair,
        "order_id": event.order_id,
        "metadata": dict(event.metadata or {}),
        "audit_required": bool(audit_required),
        "audit_published": bool(audit_published),
        "command_metadata": dict(command_metadata or {}),
        "command_producer": str(command_producer or ""),
        "producer_authorized": bool(producer_authorized),
        "namespace_key": namespace_key,
        "namespace_order_key": namespace_order_key,
    }


def _order_record_to_dict(order: OrderRecord) -> Dict[str, object]:
    namespace_key = _namespace_base_key(order.instance_name, order.connector_name, order.trading_pair)
    namespace_order_key = _namespace_order_key(
        order.instance_name,
        order.connector_name,
        order.trading_pair,
        order.order_id,
    )
    return {
        "order_id": order.order_id,
        "instance_name": order.instance_name,
        "connector_name": order.connector_name,
        "trading_pair": order.trading_pair,
        "side": order.side,
        "order_type": order.order_type,
        "amount_base": order.amount_base,
        "price": order.price,
        "time_in_force": order.time_in_force,
        "reduce_only": order.reduce_only,
        "post_only": order.post_only,
        "state": order.state,
        "created_ts_ms": order.created_ts_ms,
        "updated_ts_ms": order.updated_ts_ms,
        "last_command_event_id": order.last_command_event_id,
        "last_fill_snapshot_event_id": order.last_fill_snapshot_event_id,
        "first_fill_ts_ms": order.first_fill_ts_ms,
        "last_fill_amount_base": order.last_fill_amount_base,
        "filled_base": order.filled_base,
        "filled_quote": order.filled_quote,
        "fill_count": order.fill_count,
        "filled_fee_quote": order.filled_fee_quote,
        "margin_reserve_quote": order.margin_reserve_quote,
        "maker_fee_pct": order.maker_fee_pct,
        "taker_fee_pct": order.taker_fee_pct,
        "leverage": order.leverage,
        "margin_mode": order.margin_mode,
        "funding_rate": order.funding_rate,
        "position_action": order.position_action,
        "position_mode": order.position_mode,
        "namespace_key": namespace_key,
        "namespace_order_key": namespace_order_key,
    }


def _position_record_to_dict(position: "PositionRecord") -> Dict[str, object]:
    return {
        "instance_name": position.instance_name,
        "connector_name": position.connector_name,
        "trading_pair": position.trading_pair,
        "position_mode": position.position_mode,
        "long_base": position.long_base,
        "long_avg_entry_price": position.long_avg_entry_price,
        "short_base": position.short_base,
        "short_avg_entry_price": position.short_avg_entry_price,
        "realized_pnl_quote": position.realized_pnl_quote,
        "funding_paid_quote": position.funding_paid_quote,
        "last_fill_ts_ms": position.last_fill_ts_ms,
        "last_funding_ts_ms": position.last_funding_ts_ms,
        "last_funding_rate": position.last_funding_rate,
        "funding_event_count": position.funding_event_count,
    }


def _position_record_from_payload(payload: Dict[str, object]) -> Optional["PositionRecord"]:
    try:
        return PositionRecord(
            instance_name=str(payload.get("instance_name", "")),
            connector_name=str(payload.get("connector_name", "")),
            trading_pair=str(payload.get("trading_pair", "")),
            position_mode=str(payload.get("position_mode", "ONEWAY") or "ONEWAY").upper(),
            long_base=max(0.0, float(payload.get("long_base", 0.0))),
            long_avg_entry_price=max(0.0, float(payload.get("long_avg_entry_price", 0.0))),
            short_base=max(0.0, float(payload.get("short_base", 0.0))),
            short_avg_entry_price=max(0.0, float(payload.get("short_avg_entry_price", 0.0))),
            realized_pnl_quote=float(payload.get("realized_pnl_quote", 0.0)),
            funding_paid_quote=float(payload.get("funding_paid_quote", 0.0)),
            last_fill_ts_ms=max(0, int(payload.get("last_fill_ts_ms", 0))),
            last_funding_ts_ms=max(0, int(payload.get("last_funding_ts_ms", 0))),
            last_funding_rate=float(payload.get("last_funding_rate", 0.0)),
            funding_event_count=max(0, int(payload.get("funding_event_count", 0))),
        )
    except Exception:
        return None


def _order_record_from_payload(order_id: str, payload: Dict[str, object]) -> Optional[OrderRecord]:
    try:
        return OrderRecord(
            order_id=str(payload.get("order_id", order_id)),
            instance_name=str(payload.get("instance_name", "")),
            connector_name=str(payload.get("connector_name", "")),
            trading_pair=str(payload.get("trading_pair", "")),
            side=str(payload.get("side", "")),
            order_type=str(payload.get("order_type", "")),
            amount_base=float(payload.get("amount_base", 0.0)),
            price=float(payload.get("price", 0.0)),
            time_in_force=str(payload.get("time_in_force", "gtc")),
            reduce_only=_parse_bool(payload.get("reduce_only"), default=False),
            post_only=_parse_bool(payload.get("post_only"), default=False),
            state=str(payload.get("state", "working")),
            created_ts_ms=int(payload.get("created_ts_ms", 0)),
            updated_ts_ms=int(payload.get("updated_ts_ms", 0)),
            last_command_event_id=str(payload.get("last_command_event_id", "")),
            last_fill_snapshot_event_id=str(payload.get("last_fill_snapshot_event_id", "")),
            first_fill_ts_ms=int(payload.get("first_fill_ts_ms", 0)),
            last_fill_amount_base=float(payload.get("last_fill_amount_base", 0.0)),
            filled_base=float(payload.get("filled_base", 0.0)),
            filled_quote=float(payload.get("filled_quote", 0.0)),
            fill_count=int(payload.get("fill_count", 0)),
            filled_fee_quote=float(payload.get("filled_fee_quote", 0.0)),
            margin_reserve_quote=float(payload.get("margin_reserve_quote", 0.0)),
            maker_fee_pct=max(0.0, float(payload.get("maker_fee_pct", 0.0))),
            taker_fee_pct=max(0.0, float(payload.get("taker_fee_pct", 0.0))),
            leverage=max(1.0, float(payload.get("leverage", 1.0))),
            margin_mode=_coerce_margin_mode(payload.get("margin_mode", "leveraged")),
            funding_rate=float(payload.get("funding_rate", 0.0)),
            position_action=str(payload.get("position_action", "auto") or "auto"),
            position_mode=str(payload.get("position_mode", "ONEWAY") or "ONEWAY").upper(),
        )
    except Exception:
        return None


def _load_state_snapshot(path: Path) -> Dict[str, OrderRecord]:
    payload = _read_json(path)
    raw_orders = payload.get("orders", {})
    if not isinstance(raw_orders, dict):
        return {}
    out: Dict[str, OrderRecord] = {}
    for order_id, record in raw_orders.items():
        if not isinstance(record, dict):
            continue
        parsed = _order_record_from_payload(str(order_id), record)
        if parsed is not None and parsed.order_id:
            out[str(parsed.order_id)] = parsed
    return out


def _load_position_snapshot(path: Path) -> Dict[str, "PositionRecord"]:
    payload = _read_json(path)
    raw_positions = payload.get("positions", {})
    if not isinstance(raw_positions, dict):
        return {}
    out: Dict[str, PositionRecord] = {}
    for position_key, record in raw_positions.items():
        if not isinstance(record, dict):
            continue
        parsed = _position_record_from_payload(record)
        if parsed is not None and str(position_key or "").strip():
            out[str(position_key)] = parsed
    return out


def _persist_state_snapshot(
    path: Path,
    orders_by_id: Dict[str, OrderRecord],
    positions_by_key: Optional[Dict[str, "PositionRecord"]] = None,
    *,
    funding_summary: Optional[Dict[str, object]] = None,
) -> None:
    positions_payload = {
        position_key: _position_record_to_dict(position)
        for position_key, position in (positions_by_key or {}).items()
    }
    payload = {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "orders_total": len(orders_by_id),
        "orders": {order_id: _order_record_to_dict(order) for order_id, order in orders_by_id.items()},
        "positions_total": len(positions_payload),
        "positions": positions_payload,
        "funding_summary": dict(funding_summary or {}),
    }
    _write_json_atomic(path, payload)


def _pair_snapshot_to_dict(snapshot: PairSnapshot) -> Dict[str, object]:
    namespace_key = _namespace_base_key(snapshot.instance_name, snapshot.connector_name, snapshot.trading_pair)
    return {
        "connector_name": snapshot.connector_name,
        "trading_pair": snapshot.trading_pair,
        "instance_name": snapshot.instance_name,
        "timestamp_ms": int(snapshot.timestamp_ms),
        "freshness_ts_ms": int(snapshot.freshness_ts_ms),
        "mid_price": float(snapshot.mid_price),
        "best_bid": snapshot.best_bid,
        "best_ask": snapshot.best_ask,
        "best_bid_size": snapshot.best_bid_size,
        "best_ask_size": snapshot.best_ask_size,
        "last_trade_price": snapshot.last_trade_price,
        "mark_price": snapshot.mark_price,
        "funding_rate": snapshot.funding_rate,
        "exchange_ts_ms": snapshot.exchange_ts_ms,
        "ingest_ts_ms": snapshot.ingest_ts_ms,
        "market_sequence": snapshot.market_sequence,
        "event_id": snapshot.event_id,
        "source_event_type": snapshot.source_event_type,
        "bid_levels": [[float(price), float(size)] for price, size in snapshot.bid_levels],
        "ask_levels": [[float(price), float(size)] for price, size in snapshot.ask_levels],
        "namespace_key": namespace_key,
    }


def _persist_pair_snapshot(path: Path, pairs: Dict[str, PairSnapshot]) -> None:
    payload = {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pairs_total": len(pairs),
        "pairs": {key: _pair_snapshot_to_dict(snapshot) for key, snapshot in pairs.items()},
    }
    _write_json_atomic(path, payload)


@dataclass
class PairSnapshot:
    connector_name: str
    trading_pair: str
    instance_name: str
    timestamp_ms: int
    freshness_ts_ms: int
    mid_price: float
    best_bid: Optional[float]
    best_ask: Optional[float]
    best_bid_size: Optional[float]
    best_ask_size: Optional[float]
    last_trade_price: Optional[float]
    mark_price: Optional[float]
    funding_rate: Optional[float]
    exchange_ts_ms: Optional[int]
    ingest_ts_ms: Optional[int]
    market_sequence: Optional[int]
    event_id: str
    source_event_type: str
    bid_levels: Tuple[Tuple[float, float], ...] = ()
    ask_levels: Tuple[Tuple[float, float], ...] = ()


@dataclass
class OrderRecord:
    order_id: str
    instance_name: str
    connector_name: str
    trading_pair: str
    side: str
    order_type: str
    amount_base: float
    price: float
    time_in_force: str
    reduce_only: bool
    post_only: bool
    state: str
    created_ts_ms: int
    updated_ts_ms: int
    last_command_event_id: str
    last_fill_snapshot_event_id: str = ""
    first_fill_ts_ms: int = 0
    last_fill_amount_base: float = 0.0
    filled_base: float = 0.0
    filled_quote: float = 0.0
    fill_count: int = 0
    filled_fee_quote: float = 0.0
    margin_reserve_quote: float = 0.0
    maker_fee_pct: float = 0.0
    taker_fee_pct: float = 0.0
    leverage: float = 1.0
    margin_mode: str = "leveraged"
    funding_rate: float = 0.0
    position_action: str = "auto"
    position_mode: str = "ONEWAY"


@dataclass
class PositionRecord:
    instance_name: str
    connector_name: str
    trading_pair: str
    position_mode: str = "ONEWAY"
    long_base: float = 0.0
    long_avg_entry_price: float = 0.0
    short_base: float = 0.0
    short_avg_entry_price: float = 0.0
    realized_pnl_quote: float = 0.0
    funding_paid_quote: float = 0.0
    last_fill_ts_ms: int = 0
    last_funding_ts_ms: int = 0
    last_funding_rate: float = 0.0
    funding_event_count: int = 0


@dataclass
class PaperExchangeState:
    pairs: Dict[str, PairSnapshot] = field(default_factory=dict)
    orders_by_id: Dict[str, OrderRecord] = field(default_factory=dict)
    positions_by_key: Dict[str, PositionRecord] = field(default_factory=dict)
    accepted_snapshots: int = 0
    rejected_snapshots: int = 0
    processed_commands: int = 0
    rejected_commands: int = 0
    rejected_commands_stale_market: int = 0
    rejected_commands_missing_market: int = 0
    rejected_commands_disallowed_connector: int = 0
    rejected_commands_unauthorized_producer: int = 0
    rejected_commands_missing_privileged_metadata: int = 0
    rejected_commands_namespace_collision: int = 0
    privileged_commands_processed: int = 0
    privileged_command_audit_published: int = 0
    privileged_command_audit_publish_failures: int = 0
    duplicate_command_events: int = 0
    reclaimed_pending_entries: int = 0
    command_publish_failures: int = 0
    command_latency_samples: int = 0
    command_latency_ms_sum: int = 0
    command_latency_ms_max: int = 0
    orders_pruned_total: int = 0
    generated_fill_events: int = 0
    generated_partial_fill_events: int = 0
    market_fill_publish_failures: int = 0
    market_match_cycles: int = 0
    reclaimed_pending_market_entries: int = 0
    market_rows_not_acked: int = 0
    deduplicated_market_fill_events: int = 0
    market_fill_invalid_transition_drops: int = 0
    market_fill_journal_write_failures: int = 0
    market_fill_journal_next_seq: int = 0
    market_fill_events_by_id: Dict[str, int] = field(default_factory=dict)
    market_row_fill_cap_hits: int = 0
    command_results_by_id: Dict[str, Dict[str, object]] = field(default_factory=dict)
    funding_events_generated: int = 0
    funding_debit_events: int = 0
    funding_credit_events: int = 0
    funding_paid_quote_total: float = 0.0


@dataclass
class ServiceSettings:
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_enabled: bool = True
    service_instance_name: str = "paper_exchange"
    consumer_group: str = "hb_group_paper_exchange"
    consumer_name: str = "paper-exchange-consumer"
    market_data_stream: str = MARKET_QUOTE_STREAM
    command_stream: str = PAPER_EXCHANGE_COMMAND_STREAM
    event_stream: str = PAPER_EXCHANGE_EVENT_STREAM
    heartbeat_stream: str = PAPER_EXCHANGE_HEARTBEAT_STREAM
    audit_stream: str = AUDIT_STREAM
    allowed_connectors: Set[str] = field(default_factory=set)
    allowed_command_producers: Set[str] = field(default_factory=set)
    market_stale_after_ms: int = 15_000
    resting_fill_latency_ms: int = 0
    maker_queue_participation: float = 1.0
    market_sweep_depth_levels: int = 1
    funding_interval_ms: int = 28_800_000
    max_fill_events_per_market_row: int = 200
    heartbeat_interval_ms: int = 5_000
    read_count: int = 100
    read_block_ms: int = 1_000
    command_journal_path: str = "reports/verification/paper_exchange_command_journal_latest.json"
    state_snapshot_path: str = "reports/verification/paper_exchange_state_snapshot_latest.json"
    pair_snapshot_path: str = "reports/verification/paper_exchange_pair_snapshot_latest.json"
    market_fill_journal_path: str = "reports/verification/paper_exchange_market_fill_journal_latest.json"
    market_fill_journal_max_entries: int = 200_000
    pending_reclaim_enabled: bool = True
    pending_reclaim_idle_ms: int = 30_000
    pending_reclaim_interval_ms: int = 5_000
    pending_reclaim_count: int = 100
    market_pending_reclaim_enabled: bool = True
    market_pending_reclaim_idle_ms: int = 30_000
    market_pending_reclaim_interval_ms: int = 5_000
    market_pending_reclaim_count: int = 100
    terminal_order_ttl_ms: int = 86_400_000
    max_orders_tracked: int = 200_000
    persist_sync_state_results: bool = True


_SUPPORTED_ORDER_TYPES = {"limit", "market", "post_only"}
_SUPPORTED_TIME_IN_FORCE = {"gtc", "ioc", "fok"}
_MIN_FILL_EPSILON = 1e-12
_PRIVILEGED_COMMANDS = {"cancel_all"}
_PRIVILEGED_METADATA_FIELDS = ("operator", "reason", "change_ticket", "trace_id")


def _is_privileged_command(command_name: str) -> bool:
    return _normalize(command_name) in _PRIVILEGED_COMMANDS


def _missing_privileged_metadata(metadata: Dict[str, str]) -> List[str]:
    return [key for key in _PRIVILEGED_METADATA_FIELDS if not str(metadata.get(key, "")).strip()]


def _bool_from_record(record: Dict[str, object], key: str, default: bool) -> bool:
    raw = record.get(key)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _build_privileged_audit_event(
    *,
    command: PaperExchangeCommandEvent,
    result_status: str,
    result_reason: str,
    command_metadata: Dict[str, str],
) -> AuditEvent:
    status_norm = _normalize(result_status or "")
    severity = "warning" if status_norm != "processed" else "info"
    reason_norm = str(result_reason or "").strip() or "unknown"
    cmd = str(command.command or "").strip() or "unknown"
    return AuditEvent(
        producer="paper_exchange_service",
        instance_name=command.instance_name,
        correlation_id=command.event_id,
        severity=severity,
        category="paper_exchange_privileged_command",
        message=f"{cmd} {status_norm or 'processed'} ({reason_norm})",
        metadata={
            "command_event_id": str(command.event_id or ""),
            "command": cmd,
            "result_status": str(result_status or ""),
            "result_reason": reason_norm,
            "connector_name": str(command.connector_name or ""),
            "trading_pair": str(command.trading_pair or ""),
            "order_id": str(command.order_id or ""),
            "producer": str(command.producer or ""),
            "operator": str(command_metadata.get("operator", "")).strip(),
            "change_ticket": str(command_metadata.get("change_ticket", "")).strip(),
            "reason": str(command_metadata.get("reason", "")).strip(),
            "trace_id": str(command_metadata.get("trace_id", "")).strip(),
        },
    )


def _entry_sequence_from_stream_id(entry_id: str) -> int:
    text = str(entry_id or "").strip()
    if "-" not in text:
        return 0
    ms_part, seq_part = text.split("-", 1)
    try:
        ms = int(ms_part)
        seq = int(seq_part)
    except Exception:
        return 0
    # Deterministic sortable scalar for command stream ordering.
    return max(0, ms) * 1_000_000 + max(0, seq)


def _positive_or_none(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _snapshot_best_bid(snapshot: Optional[PairSnapshot]) -> Optional[float]:
    return _positive_or_none(None if snapshot is None else snapshot.best_bid)


def _snapshot_best_ask(snapshot: Optional[PairSnapshot]) -> Optional[float]:
    return _positive_or_none(None if snapshot is None else snapshot.best_ask)


def _snapshot_best_bid_size(snapshot: Optional[PairSnapshot]) -> Optional[float]:
    return _positive_or_none(None if snapshot is None else snapshot.best_bid_size)


def _snapshot_best_ask_size(snapshot: Optional[PairSnapshot]) -> Optional[float]:
    return _positive_or_none(None if snapshot is None else snapshot.best_ask_size)


def _remaining_amount_base(order: OrderRecord) -> float:
    return max(0.0, float(order.amount_base) - float(order.filled_base))


def _position_key(instance_name: str, connector_name: str, trading_pair: str) -> str:
    return _namespace_base_key(instance_name, connector_name, trading_pair)


def _get_or_create_position(state: PaperExchangeState, order: OrderRecord) -> PositionRecord:
    key = _position_key(order.instance_name, order.connector_name, order.trading_pair)
    position = state.positions_by_key.get(key)
    if position is not None:
        return position
    position = PositionRecord(
        instance_name=order.instance_name,
        connector_name=order.connector_name,
        trading_pair=order.trading_pair,
        position_mode=str(order.position_mode or "ONEWAY").upper() or "ONEWAY",
    )
    state.positions_by_key[key] = position
    return position


def _round_positive(value: float) -> float:
    return max(0.0, float(value))


def _open_long(position: PositionRecord, quantity: float, price: float) -> None:
    qty = _round_positive(quantity)
    if qty <= _MIN_FILL_EPSILON:
        return
    px = max(0.0, float(price))
    existing_qty = _round_positive(position.long_base)
    if existing_qty <= _MIN_FILL_EPSILON or position.long_avg_entry_price <= 0:
        position.long_base = qty
        position.long_avg_entry_price = px
        return
    total_qty = existing_qty + qty
    position.long_avg_entry_price = ((existing_qty * position.long_avg_entry_price) + (qty * px)) / total_qty
    position.long_base = total_qty


def _open_short(position: PositionRecord, quantity: float, price: float) -> None:
    qty = _round_positive(quantity)
    if qty <= _MIN_FILL_EPSILON:
        return
    px = max(0.0, float(price))
    existing_qty = _round_positive(position.short_base)
    if existing_qty <= _MIN_FILL_EPSILON or position.short_avg_entry_price <= 0:
        position.short_base = qty
        position.short_avg_entry_price = px
        return
    total_qty = existing_qty + qty
    position.short_avg_entry_price = ((existing_qty * position.short_avg_entry_price) + (qty * px)) / total_qty
    position.short_base = total_qty


def _close_long(position: PositionRecord, quantity: float, price: float) -> float:
    qty = min(_round_positive(quantity), _round_positive(position.long_base))
    if qty <= _MIN_FILL_EPSILON:
        return 0.0
    realized = qty * (float(price) - float(position.long_avg_entry_price))
    position.long_base = max(0.0, float(position.long_base) - qty)
    if position.long_base <= _MIN_FILL_EPSILON:
        position.long_base = 0.0
        position.long_avg_entry_price = 0.0
    position.realized_pnl_quote += realized
    return qty


def _close_short(position: PositionRecord, quantity: float, price: float) -> float:
    qty = min(_round_positive(quantity), _round_positive(position.short_base))
    if qty <= _MIN_FILL_EPSILON:
        return 0.0
    realized = qty * (float(position.short_avg_entry_price) - float(price))
    position.short_base = max(0.0, float(position.short_base) - qty)
    if position.short_base <= _MIN_FILL_EPSILON:
        position.short_base = 0.0
        position.short_avg_entry_price = 0.0
    position.realized_pnl_quote += realized
    return qty


def _is_flat_position(position: PositionRecord) -> bool:
    return _round_positive(position.long_base) <= _MIN_FILL_EPSILON and _round_positive(position.short_base) <= _MIN_FILL_EPSILON


def _apply_position_fill(
    *,
    state: PaperExchangeState,
    order: OrderRecord,
    fill_amount_base: float,
    fill_price: float,
    now_ms: int,
) -> None:
    qty = _round_positive(fill_amount_base)
    if qty <= _MIN_FILL_EPSILON:
        return
    position = _get_or_create_position(state, order)
    was_flat = _is_flat_position(position)
    side = _normalize(order.side)
    action = _normalize(order.position_action or "auto")
    mode = str(order.position_mode or "ONEWAY").strip().upper() or "ONEWAY"
    reduce_only = bool(order.reduce_only)

    if mode == "HEDGE":
        if side == "buy":
            if action == "close_short" or reduce_only:
                _close_short(position, qty, fill_price)
            else:
                _open_long(position, qty, fill_price)
        elif side == "sell":
            if action == "close_long" or reduce_only:
                _close_long(position, qty, fill_price)
            else:
                _open_short(position, qty, fill_price)
    else:
        remaining = qty
        if side == "buy":
            if action == "open_long":
                _open_long(position, remaining, fill_price)
                remaining = 0.0
            elif action == "close_short":
                _close_short(position, remaining, fill_price)
                remaining = 0.0
            else:
                closed = _close_short(position, remaining, fill_price)
                remaining = max(0.0, remaining - closed)
                if not reduce_only and remaining > _MIN_FILL_EPSILON:
                    _open_long(position, remaining, fill_price)
        elif side == "sell":
            if action == "open_short":
                _open_short(position, remaining, fill_price)
                remaining = 0.0
            elif action == "close_long":
                _close_long(position, remaining, fill_price)
                remaining = 0.0
            else:
                closed = _close_long(position, remaining, fill_price)
                remaining = max(0.0, remaining - closed)
                if not reduce_only and remaining > _MIN_FILL_EPSILON:
                    _open_short(position, remaining, fill_price)

    position.position_mode = mode
    position.last_fill_ts_ms = max(0, int(now_ms))
    if was_flat and not _is_flat_position(position):
        position.last_funding_ts_ms = max(0, int(now_ms))


def _funding_summary(state: PaperExchangeState) -> Dict[str, object]:
    return {
        "positions_with_exposure": sum(1 for position in state.positions_by_key.values() if not _is_flat_position(position)),
        "funding_events_generated": int(state.funding_events_generated),
        "funding_debit_events": int(state.funding_debit_events),
        "funding_credit_events": int(state.funding_credit_events),
        "funding_paid_quote_total": float(state.funding_paid_quote_total),
    }


@dataclass
class FundingSettlementCandidate:
    position_key: str
    leg_side: str
    funding_rate: float
    charge_quote: float
    reference_price: float
    position_base: float
    position_notional_quote: float
    last_funding_ts_ms: int
    current_funding_ts_ms: int
    event: PaperExchangeEvent


def _funding_events_for_snapshot(
    *,
    state: PaperExchangeState,
    snapshot: PairSnapshot,
    funding_interval_ms: int,
    now_ms: int,
) -> List[FundingSettlementCandidate]:
    interval_ms = max(1_000, int(funding_interval_ms))
    price_reference = max(
        0.0,
        float(snapshot.mark_price or 0.0) or float(snapshot.mid_price or 0.0),
    )
    if price_reference <= 0.0:
        return []
    funding_rate = float(snapshot.funding_rate or 0.0)
    if funding_rate == 0.0:
        return []
    candidates: List[FundingSettlementCandidate] = []
    matching_positions = [
        (position_key, position)
        for position_key, position in state.positions_by_key.items()
        if _normalize_connector_name(position.connector_name) == _normalize_connector_name(snapshot.connector_name)
        and str(position.trading_pair or "").strip().upper() == str(snapshot.trading_pair or "").strip().upper()
        and (
            not str(snapshot.instance_name or "").strip()
            or _normalize(position.instance_name) == _normalize(snapshot.instance_name)
        )
    ]
    for position_key, position in matching_positions:
        if _is_flat_position(position):
            position.last_funding_ts_ms = max(position.last_funding_ts_ms, int(now_ms))
            continue
        last_funding_ts_ms = max(0, int(position.last_funding_ts_ms))
        if last_funding_ts_ms <= 0:
            position.last_funding_ts_ms = int(now_ms)
            continue
        if (int(now_ms) - last_funding_ts_ms) < interval_ms:
            continue
        for leg_side, quantity, avg_entry_price, direction in (
            ("long", float(position.long_base), float(position.long_avg_entry_price), 1.0),
            ("short", float(position.short_base), float(position.short_avg_entry_price), -1.0),
        ):
            qty = _round_positive(quantity)
            if qty <= _MIN_FILL_EPSILON:
                continue
            reference_price = max(0.0, price_reference or avg_entry_price)
            if reference_price <= 0.0:
                continue
            notional_quote = qty * reference_price
            charge_quote = funding_rate * notional_quote * direction
            if abs(charge_quote) <= _MIN_FILL_EPSILON:
                continue
            cumulative_funding_quote = float(position.funding_paid_quote) + float(charge_quote)
            event_id = (
                f"pe-funding-{position.instance_name}-{snapshot.connector_name}-{snapshot.trading_pair}-"
                f"{leg_side}-{int(now_ms)}"
            )
            event = PaperExchangeEvent(
                producer="paper_exchange_service",
                event_id=event_id,
                correlation_id=event_id,
                instance_name=position.instance_name,
                command_event_id=event_id,
                command="funding_settlement",
                status="processed",
                reason="periodic_funding_settlement",
                connector_name=snapshot.connector_name,
                trading_pair=snapshot.trading_pair,
                position_mode=position.position_mode,
                metadata={
                    "leg_side": leg_side,
                    "funding_rate": str(funding_rate),
                    "charge_quote": str(charge_quote),
                    "reference_price": str(reference_price),
                    "position_base": str(qty),
                    "position_notional_quote": str(notional_quote),
                    "long_base": str(position.long_base),
                    "short_base": str(position.short_base),
                    "realized_pnl_quote": str(position.realized_pnl_quote),
                    "funding_paid_quote_total": str(cumulative_funding_quote),
                    "settlement_interval_ms": str(interval_ms),
                    "last_funding_ts_ms": str(last_funding_ts_ms),
                    "current_funding_ts_ms": str(int(now_ms)),
                    "snapshot_event_id": str(snapshot.event_id or ""),
                },
            )
            candidates.append(
                FundingSettlementCandidate(
                    position_key=position_key,
                    leg_side=leg_side,
                    funding_rate=funding_rate,
                    charge_quote=charge_quote,
                    reference_price=reference_price,
                    position_base=qty,
                    position_notional_quote=notional_quote,
                    last_funding_ts_ms=last_funding_ts_ms,
                    current_funding_ts_ms=int(now_ms),
                    event=event,
                )
            )
    return candidates


def _commit_funding_settlement(state: PaperExchangeState, candidate: FundingSettlementCandidate) -> None:
    position = state.positions_by_key.get(candidate.position_key)
    if position is None:
        return
    position.funding_paid_quote += float(candidate.charge_quote)
    position.last_funding_rate = float(candidate.funding_rate)
    position.funding_event_count += 1
    position.last_funding_ts_ms = int(candidate.current_funding_ts_ms)
    state.funding_events_generated += 1
    if float(candidate.charge_quote) > 0.0:
        state.funding_debit_events += 1
    else:
        state.funding_credit_events += 1
    state.funding_paid_quote_total += float(candidate.charge_quote)


@dataclass
class FillCandidate:
    event_id: str
    command_event_id: str
    order_id: str
    new_state: str
    fill_price: float
    fill_amount_base: float
    fill_notional_quote: float
    remaining_amount_base: float
    is_maker: bool
    snapshot_event_id: str
    snapshot_market_sequence: int
    fill_count: int
    fill_fee_quote: float = 0.0
    fill_fee_rate_pct: float = 0.0
    margin_reserve_quote: float = 0.0
    funding_rate: float = 0.0


def _parse_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _coerce_time_in_force(metadata: Dict[str, str]) -> str:
    tif = str(metadata.get("time_in_force", "gtc")).strip().lower()
    return tif if tif in _SUPPORTED_TIME_IN_FORCE else ""


def _try_float(value: object) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _decimal_from_metadata(metadata: Dict[str, str], key: str) -> Optional[Decimal]:
    raw = metadata.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _is_multiple_of_increment(value: Decimal, increment: Decimal) -> bool:
    if increment <= Decimal("0"):
        return True
    try:
        remainder = value % increment
    except Exception:
        return False
    return remainder == 0


def _validate_order_constraints(
    *,
    metadata: Dict[str, str],
    order_type: str,
    amount_base: float,
    price: Optional[float],
    market_reference_price: Optional[float],
) -> Optional[Tuple[str, Dict[str, str]]]:
    min_quantity = _decimal_from_metadata(metadata, "min_quantity") or Decimal("0")
    size_increment = _decimal_from_metadata(metadata, "size_increment") or Decimal("0")
    price_increment = _decimal_from_metadata(metadata, "price_increment") or Decimal("0")
    min_notional = _decimal_from_metadata(metadata, "min_notional") or Decimal("0")
    amount_dec = Decimal(str(amount_base))
    reference_price = market_reference_price if order_type == "market" else price
    price_dec = Decimal(str(reference_price)) if reference_price is not None else None

    if min_quantity > 0 and amount_dec < min_quantity:
        return (
            "below_min_quantity",
            {
                "amount_base": str(amount_dec),
                "min_quantity": str(min_quantity),
            },
        )
    if size_increment > 0 and not _is_multiple_of_increment(amount_dec, size_increment):
        return (
            "invalid_size_increment",
            {
                "amount_base": str(amount_dec),
                "size_increment": str(size_increment),
            },
        )
    if order_type != "market" and price_dec is not None and price_increment > 0 and not _is_multiple_of_increment(price_dec, price_increment):
        return (
            "invalid_price_increment",
            {
                "price": str(price_dec),
                "price_increment": str(price_increment),
            },
        )
    if min_notional > 0 and price_dec is not None and (amount_dec * price_dec) < min_notional:
        return (
            "below_min_notional",
            {
                "notional_quote": str(amount_dec * price_dec),
                "min_notional": str(min_notional),
            },
        )
    return None


def _coerce_margin_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in {"leveraged", "standard"} else "leveraged"


def _resolve_accounting_contract(
    metadata: Dict[str, str],
    *,
    pair_snapshot: Optional[PairSnapshot],
) -> Tuple[float, float, float, str, float]:
    maker_fee_pct = _try_float(metadata.get("maker_fee_pct"))
    taker_fee_pct = _try_float(metadata.get("taker_fee_pct"))
    fallback_fee_pct = _try_float(metadata.get("fee_pct"))
    if fallback_fee_pct is None:
        fallback_fee_pct = _try_float(metadata.get("spot_fee_pct"))

    if maker_fee_pct is None:
        maker_fee_pct = fallback_fee_pct
    if taker_fee_pct is None:
        taker_fee_pct = fallback_fee_pct
    if maker_fee_pct is None and taker_fee_pct is not None:
        maker_fee_pct = taker_fee_pct
    if taker_fee_pct is None and maker_fee_pct is not None:
        taker_fee_pct = maker_fee_pct

    maker_fee_pct = max(0.0, float(maker_fee_pct or 0.0))
    taker_fee_pct = max(0.0, float(taker_fee_pct or 0.0))

    leverage = _try_float(metadata.get("leverage"))
    leverage = max(1.0, float(leverage if leverage is not None else 1.0))

    margin_mode = _coerce_margin_mode(metadata.get("margin_mode"))

    funding_rate = _try_float(metadata.get("funding_rate"))
    if funding_rate is None and pair_snapshot is not None and pair_snapshot.funding_rate is not None:
        funding_rate = float(pair_snapshot.funding_rate)
    funding_rate = float(funding_rate if funding_rate is not None else 0.0)

    return maker_fee_pct, taker_fee_pct, leverage, margin_mode, funding_rate


def _fee_rate_for_fill(
    *,
    is_maker: bool,
    maker_fee_pct: float,
    taker_fee_pct: float,
) -> float:
    maker = max(0.0, float(maker_fee_pct))
    taker = max(0.0, float(taker_fee_pct))
    if is_maker:
        return maker if maker > 0 else taker
    return taker if taker > 0 else maker


def _calc_fill_fee_quote(
    *,
    fill_notional_quote: float,
    is_maker: bool,
    maker_fee_pct: float,
    taker_fee_pct: float,
) -> Tuple[float, float]:
    fee_rate_pct = _fee_rate_for_fill(
        is_maker=is_maker,
        maker_fee_pct=maker_fee_pct,
        taker_fee_pct=taker_fee_pct,
    )
    fee_quote = max(0.0, abs(float(fill_notional_quote)) * fee_rate_pct)
    return fee_quote, fee_rate_pct


def _calc_margin_reserve_quote(
    *,
    filled_notional_quote_total: float,
    leverage: float,
    margin_mode: str,
) -> float:
    notional = max(0.0, abs(float(filled_notional_quote_total)))
    if _coerce_margin_mode(margin_mode) == "standard":
        return notional
    lev = max(1.0, float(leverage))
    return notional / lev


def _order_metadata(order: OrderRecord) -> Dict[str, str]:
    remaining = _remaining_amount_base(order)
    return {
        "order_state": order.state,
        "side": order.side,
        "order_type": order.order_type,
        "amount_base": str(order.amount_base),
        "filled_amount_base_total": str(order.filled_base),
        "remaining_amount_base": str(remaining),
        "filled_notional_quote_total": str(order.filled_quote),
        "fill_count": str(order.fill_count),
        "price": str(order.price),
        "time_in_force": order.time_in_force,
        "reduce_only": "1" if order.reduce_only else "0",
        "post_only": "1" if order.post_only else "0",
        "updated_ts_ms": str(order.updated_ts_ms),
        "last_fill_snapshot_event_id": str(order.last_fill_snapshot_event_id or ""),
        "last_fill_amount_base": str(order.last_fill_amount_base),
        "filled_fee_quote_total": str(order.filled_fee_quote),
        "margin_reserve_quote": str(order.margin_reserve_quote),
        "maker_fee_pct": str(order.maker_fee_pct),
        "taker_fee_pct": str(order.taker_fee_pct),
        "leverage": str(order.leverage),
        "margin_mode": _coerce_margin_mode(order.margin_mode),
        "funding_rate": str(order.funding_rate),
    }


def _event_for_command(
    *,
    command: PaperExchangeCommandEvent,
    status: str,
    reason: str,
    metadata: Optional[Dict[str, str]] = None,
) -> PaperExchangeEvent:
    return PaperExchangeEvent(
        producer="paper_exchange_service",
        instance_name=command.instance_name,
        correlation_id=command.event_id,
        command_event_id=command.event_id,
        command=command.command,
        status=status,
        reason=reason,
        connector_name=command.connector_name,
        trading_pair=command.trading_pair,
        order_id=command.order_id,
        position_action=command.position_action,
        position_mode=command.position_mode,
        metadata=dict(metadata or {}),
    )


def _crosses_book(side: str, order_price: float, best_bid: Optional[float], best_ask: Optional[float]) -> bool:
    if side == "buy":
        return best_ask is not None and order_price >= best_ask
    if side == "sell":
        return best_bid is not None and order_price <= best_bid
    return False


def _market_execution_price(side: str, snapshot: Optional[PairSnapshot]) -> Optional[float]:
    best_bid = _snapshot_best_bid(snapshot)
    best_ask = _snapshot_best_ask(snapshot)
    if side == "buy":
        return best_ask or (snapshot.mid_price if snapshot is not None else None)
    if side == "sell":
        return best_bid or (snapshot.mid_price if snapshot is not None else None)
    return None


def _extract_depth_levels(raw_levels: object, *, descending: bool, max_levels: int = 5) -> Tuple[Tuple[float, float], ...]:
    levels: List[Tuple[float, float]] = []
    if not isinstance(raw_levels, list):
        return ()
    for raw in raw_levels:
        price: Optional[float] = None
        size: Optional[float] = None
        if isinstance(raw, dict):
            price = _try_float(raw.get("price"))
            size = _try_float(raw.get("size"))
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            price = _try_float(raw[0])
            size = _try_float(raw[1])
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        levels.append((float(price), float(size)))
        if len(levels) >= max(1, int(max_levels)):
            break
    levels.sort(key=lambda item: item[0], reverse=bool(descending))
    return tuple(levels)


def _contra_levels_for_snapshot(
    snapshot: PairSnapshot,
    *,
    side: str,
    max_levels: int,
    limit_price: Optional[float] = None,
) -> Tuple[Tuple[float, float], ...]:
    levels = snapshot.ask_levels if side == "buy" else snapshot.bid_levels
    if not levels:
        top_price = _snapshot_best_ask(snapshot) if side == "buy" else _snapshot_best_bid(snapshot)
        top_size = _snapshot_best_ask_size(snapshot) if side == "buy" else _snapshot_best_bid_size(snapshot)
        if top_price is None:
            return ()
        levels = ((float(top_price), float(top_size) if top_size is not None else float("inf")),)
    filtered: List[Tuple[float, float]] = []
    for price, size in levels[: max(1, int(max_levels))]:
        if limit_price is not None:
            if side == "buy" and float(price) > float(limit_price):
                continue
            if side == "sell" and float(price) < float(limit_price):
                continue
        if float(size) <= _MIN_FILL_EPSILON:
            continue
        filtered.append((float(price), float(size)))
    return tuple(filtered)


def _sweep_fill_from_levels(
    *,
    amount_base: float,
    levels: Tuple[Tuple[float, float], ...],
) -> Tuple[float, Optional[float]]:
    remaining = max(0.0, float(amount_base))
    if remaining <= _MIN_FILL_EPSILON:
        return 0.0, None
    filled = 0.0
    notional = 0.0
    for price, size in levels:
        take = min(remaining, max(0.0, float(size)))
        if take <= _MIN_FILL_EPSILON:
            continue
        filled += take
        notional += take * float(price)
        remaining = max(0.0, remaining - take)
        if remaining <= _MIN_FILL_EPSILON:
            break
    if filled <= _MIN_FILL_EPSILON:
        return 0.0, None
    return filled, (notional / filled)


def _effective_depth_from_levels(
    levels: Tuple[Tuple[float, float], ...],
    *,
    decay: float = 0.70,
) -> float:
    if not levels:
        return 0.0
    total = 0.0
    weight = 1.0
    bounded_decay = min(1.0, max(0.1, float(decay)))
    for _price, size in levels:
        if float(size) > _MIN_FILL_EPSILON:
            total += float(size) * weight
        weight *= bounded_decay
    return max(0.0, float(total))


def _consume_levels(
    levels: List[Tuple[float, float]],
    consumed: float,
) -> List[Tuple[float, float]]:
    remaining = max(0.0, float(consumed))
    if remaining <= _MIN_FILL_EPSILON:
        return [(float(price), float(size)) for price, size in levels]
    out: List[Tuple[float, float]] = []
    for price, size in levels:
        level_size = max(0.0, float(size))
        if remaining > _MIN_FILL_EPSILON and level_size > _MIN_FILL_EPSILON:
            used = min(level_size, remaining)
            level_size = max(0.0, level_size - used)
            remaining = max(0.0, remaining - used)
        if level_size > _MIN_FILL_EPSILON:
            out.append((float(price), level_size))
    return out


def _filter_levels_for_limit(
    levels: List[Tuple[float, float]],
    *,
    side: str,
    limit_price: float,
    max_levels: int,
) -> Tuple[Tuple[float, float], ...]:
    filtered: List[Tuple[float, float]] = []
    for price, size in levels[: max(1, int(max_levels))]:
        if side == "buy" and float(price) > float(limit_price):
            continue
        if side == "sell" and float(price) < float(limit_price):
            continue
        if float(size) <= _MIN_FILL_EPSILON:
            continue
        filtered.append((float(price), float(size)))
    return tuple(filtered)


def _order_matches_snapshot(order: OrderRecord, snapshot: PairSnapshot) -> bool:
    snapshot_instance = _normalize(snapshot.instance_name)
    return (
        (not snapshot_instance or _normalize(order.instance_name) == snapshot_instance)
        and
        _normalize_connector_name(order.connector_name) == _normalize_connector_name(snapshot.connector_name)
        and str(order.trading_pair).upper() == str(snapshot.trading_pair).upper()
    )


def _ordered_active_orders_for_snapshot(state: PaperExchangeState, snapshot: PairSnapshot) -> List[OrderRecord]:
    active = [
        order
        for order in state.orders_by_id.values()
        if order.state in {"working", "partially_filled"} and _order_matches_snapshot(order, snapshot)
    ]
    active.sort(key=lambda order: (int(order.created_ts_ms), str(order.order_id)))
    return active


def _build_fill_candidates_for_snapshot(
    *,
    state: PaperExchangeState,
    snapshot: PairSnapshot,
    resting_fill_latency_ms: int = 0,
    maker_queue_participation: float = 1.0,
    market_sweep_depth_levels: int = 1,
) -> List[FillCandidate]:
    best_bid = _snapshot_best_bid(snapshot)
    best_ask = _snapshot_best_ask(snapshot)
    if best_bid is None and best_ask is None:
        return []

    bid_levels = list(_contra_levels_for_snapshot(snapshot, side="sell", max_levels=max(1, int(market_sweep_depth_levels))))
    ask_levels = list(_contra_levels_for_snapshot(snapshot, side="buy", max_levels=max(1, int(market_sweep_depth_levels))))
    candidates: List[FillCandidate] = []

    # Replay guard for partially processed snapshot rows:
    # reserve liquidity already consumed by fills tied to this snapshot event_id.
    for historical_order in state.orders_by_id.values():
        if str(historical_order.last_fill_snapshot_event_id or "") != str(snapshot.event_id):
            continue
        consumed = max(0.0, float(historical_order.last_fill_amount_base))
        if consumed <= _MIN_FILL_EPSILON:
            continue
        if historical_order.side == "buy":
            ask_levels = _consume_levels(ask_levels, consumed)
        elif historical_order.side == "sell":
            bid_levels = _consume_levels(bid_levels, consumed)

    for order in _ordered_active_orders_for_snapshot(state, snapshot):
        if is_immediate_tif(order.time_in_force):
            # Defensive migration guard: immediate-only orders must never keep resting
            # across snapshots (e.g., after version upgrades or legacy snapshots).
            if can_transition_state(order.state, "expired"):
                order.state = "expired"
                order.updated_ts_ms = _now_ms()
            else:
                state.market_fill_invalid_transition_drops += 1
                logger.warning(
                    "paper_exchange invalid transition dropped | order_id=%s from=%s to=expired source=immediate_tif_guard",
                    order.order_id,
                    order.state,
                )
            continue
        if str(order.last_fill_snapshot_event_id or "") == str(snapshot.event_id):
            # Replay guard: one fill step per order per snapshot event_id.
            continue
        remaining = _remaining_amount_base(order)
        if remaining <= _MIN_FILL_EPSILON:
            continue
        if not _crosses_book(order.side, float(order.price), best_bid, best_ask):
            continue
        if int(snapshot.timestamp_ms) - int(order.created_ts_ms) < max(0, int(resting_fill_latency_ms)):
            continue

        if order.side == "buy":
            contra_levels = _filter_levels_for_limit(
                ask_levels,
                side=order.side,
                limit_price=float(order.price),
                max_levels=max(1, int(market_sweep_depth_levels)),
            )
        else:
            contra_levels = _filter_levels_for_limit(
                bid_levels,
                side=order.side,
                limit_price=float(order.price),
                max_levels=max(1, int(market_sweep_depth_levels)),
            )
        if order.side == "buy":
            fill_price = float(order.price)
        else:
            fill_price = float(order.price)
        if fill_price <= 0:
            continue

        effective_depth = _effective_depth_from_levels(contra_levels)
        fillable_available = (
            remaining
            if effective_depth <= _MIN_FILL_EPSILON
            else float(effective_depth) * max(0.0, float(maker_queue_participation))
        )
        fill_amount = min(remaining, max(0.0, fillable_available))
        if fill_amount <= _MIN_FILL_EPSILON:
            continue

        remaining_after = max(0.0, remaining - fill_amount)
        if order.side == "buy":
            ask_levels = _consume_levels(ask_levels, fill_amount)
        else:
            bid_levels = _consume_levels(bid_levels, fill_amount)

        fill_notional_quote = fill_amount * fill_price
        fill_fee_quote, fill_fee_rate_pct = _calc_fill_fee_quote(
            fill_notional_quote=fill_notional_quote,
            is_maker=True,
            maker_fee_pct=order.maker_fee_pct,
            taker_fee_pct=order.taker_fee_pct,
        )
        filled_notional_quote_total = max(0.0, float(order.filled_quote) + float(fill_notional_quote))
        margin_reserve_quote = _calc_margin_reserve_quote(
            filled_notional_quote_total=filled_notional_quote_total,
            leverage=order.leverage,
            margin_mode=order.margin_mode,
        )
        fill_count = int(order.fill_count) + 1
        candidates.append(
            FillCandidate(
                event_id=f"pe-fill-{snapshot.event_id}-{order.order_id}-{fill_count}",
                command_event_id=f"market_snapshot:{snapshot.event_id}",
                order_id=str(order.order_id),
                new_state="filled" if remaining_after <= _MIN_FILL_EPSILON else "partially_filled",
                fill_price=fill_price,
                fill_amount_base=fill_amount,
                fill_notional_quote=fill_notional_quote,
                remaining_amount_base=remaining_after,
                is_maker=True,
                snapshot_event_id=str(snapshot.event_id),
                snapshot_market_sequence=int(snapshot.market_sequence or 0),
                fill_count=fill_count,
                fill_fee_quote=float(fill_fee_quote),
                fill_fee_rate_pct=float(fill_fee_rate_pct),
                margin_reserve_quote=float(margin_reserve_quote),
                funding_rate=float(order.funding_rate),
            )
        )
    return candidates


def _market_fill_event_from_candidate(
    *,
    order: OrderRecord,
    snapshot: PairSnapshot,
    candidate: FillCandidate,
) -> PaperExchangeEvent:
    reason = "resting_order_filled" if candidate.new_state == "filled" else "resting_order_partial_fill"
    filled_base_total = max(0.0, float(order.filled_base) + float(candidate.fill_amount_base))
    filled_notional_quote_total = max(0.0, float(order.filled_quote) + float(candidate.fill_notional_quote))
    filled_fee_quote_total = max(0.0, float(order.filled_fee_quote) + float(candidate.fill_fee_quote))
    return PaperExchangeEvent(
        producer="paper_exchange_service",
        event_id=str(candidate.event_id),
        correlation_id=str(candidate.command_event_id),
        instance_name=order.instance_name,
        command_event_id=str(candidate.command_event_id),
        command="order_fill",
        status="processed",
        reason=reason,
        connector_name=order.connector_name,
        trading_pair=order.trading_pair,
        order_id=order.order_id,
        metadata={
            "order_state": candidate.new_state,
            "side": order.side,
            "order_type": order.order_type,
            "amount_base": str(order.amount_base),
            "price": str(order.price),
            "time_in_force": order.time_in_force,
            "reduce_only": "1" if order.reduce_only else "0",
            "post_only": "1" if order.post_only else "0",
            "fill_price": str(candidate.fill_price),
            "fill_amount_base": str(candidate.fill_amount_base),
            "fill_notional_quote": str(candidate.fill_notional_quote),
            "fill_fee_quote": str(candidate.fill_fee_quote),
            "fill_fee_rate_pct": str(candidate.fill_fee_rate_pct),
            "is_maker": "1" if candidate.is_maker else "0",
            "remaining_amount_base": str(candidate.remaining_amount_base),
            "filled_amount_base_total": str(filled_base_total),
            "filled_notional_quote_total": str(filled_notional_quote_total),
            "filled_fee_quote_total": str(filled_fee_quote_total),
            "maker_fee_pct": str(order.maker_fee_pct),
            "taker_fee_pct": str(order.taker_fee_pct),
            "leverage": str(order.leverage),
            "margin_mode": _coerce_margin_mode(order.margin_mode),
            "funding_rate": str(candidate.funding_rate),
            "snapshot_funding_rate": str(snapshot.funding_rate) if snapshot.funding_rate is not None else "",
            "margin_reserve_quote": str(candidate.margin_reserve_quote),
            "fill_count": str(candidate.fill_count),
            "snapshot_event_id": str(candidate.snapshot_event_id),
            "snapshot_market_sequence": str(candidate.snapshot_market_sequence),
            "best_bid": str(snapshot.best_bid) if snapshot.best_bid is not None else "",
            "best_ask": str(snapshot.best_ask) if snapshot.best_ask is not None else "",
        },
    )


def _apply_fill_candidate(order: OrderRecord, candidate: FillCandidate, *, now_ms: int) -> bool:
    target_state = str(candidate.new_state or "").strip().lower()
    if not can_transition_state(order.state, target_state):
        logger.warning(
            "paper_exchange invalid transition dropped | order_id=%s from=%s to=%s source=apply_fill_candidate",
            order.order_id,
            order.state,
            target_state,
        )
        return False
    order.filled_base = max(0.0, float(order.filled_base) + float(candidate.fill_amount_base))
    order.filled_quote = max(0.0, float(order.filled_quote) + float(candidate.fill_notional_quote))
    order.filled_fee_quote = max(0.0, float(order.filled_fee_quote) + float(candidate.fill_fee_quote))
    order.margin_reserve_quote = max(0.0, float(candidate.margin_reserve_quote))
    order.fill_count = int(candidate.fill_count)
    if float(candidate.fill_amount_base) > _MIN_FILL_EPSILON and int(order.first_fill_ts_ms) <= 0:
        order.first_fill_ts_ms = int(now_ms)
    order.state = target_state
    order.last_fill_snapshot_event_id = str(candidate.snapshot_event_id)
    order.last_fill_amount_base = max(0.0, float(candidate.fill_amount_base))
    order.updated_ts_ms = int(now_ms)
    return True


def _prune_orders(
    *,
    state: PaperExchangeState,
    now_ms: int,
    terminal_order_ttl_ms: int,
    max_orders_tracked: int,
) -> int:
    removed = 0
    ttl_ms = max(0, int(terminal_order_ttl_ms))
    max_tracked = max(1, int(max_orders_tracked))

    if ttl_ms > 0:
        for order_id, order in list(state.orders_by_id.items()):
            if order.state not in _TERMINAL_ORDER_STATES:
                continue
            order_age_ms = max(0, int(now_ms) - int(order.updated_ts_ms))
            if order_age_ms > ttl_ms:
                state.orders_by_id.pop(order_id, None)
                removed += 1

    overflow = len(state.orders_by_id) - max_tracked
    if overflow > 0:
        sorted_orders = sorted(
            state.orders_by_id.items(),
            key=lambda item: (
                0 if item[1].state in _TERMINAL_ORDER_STATES else 1,
                int(item[1].updated_ts_ms),
                str(item[0]),
            ),
        )
        for order_id, _order in sorted_orders[:overflow]:
            if order_id in state.orders_by_id:
                state.orders_by_id.pop(order_id, None)
                removed += 1

    if removed > 0:
        state.orders_pruned_total += removed
    return removed


def ingest_market_snapshot_payload(
    payload: Dict[str, object],
    state: PaperExchangeState,
    allowed_connectors: Set[str],
    *,
    entry_id: str = "",
) -> Tuple[bool, str]:
    """Ingest a canonical market quote or legacy controller snapshot."""
    for field_name, reason in (
        ("best_bid_size", "non_positive_best_bid_size"),
        ("best_ask_size", "non_positive_best_ask_size"),
    ):
        if field_name not in payload or payload.get(field_name) in (None, ""):
            continue
        try:
            if float(payload.get(field_name) or 0.0) <= 0.0:
                state.rejected_snapshots += 1
                return False, reason
        except Exception:
            state.rejected_snapshots += 1
            return False, reason

    state_view = parse_canonical_market_state(payload, entry_id=entry_id)
    if state_view is None:
        state.rejected_snapshots += 1
        return False, "invalid_schema"

    event_type = state_view.event_type
    instance_name = state_view.instance_name
    mid_price = float(state_view.mid_price)
    best_bid = float(state_view.best_bid) if state_view.best_bid > 0 else None
    best_ask = float(state_view.best_ask) if state_view.best_ask > 0 else None
    best_bid_size = float(state_view.best_bid_size) if state_view.best_bid_size > 0 else None
    best_ask_size = float(state_view.best_ask_size) if state_view.best_ask_size > 0 else None
    last_trade_price = float(state_view.last_trade_price) if state_view.last_trade_price > 0 else None
    mark_price = float(state_view.mark_price) if state_view.mark_price > 0 else None
    funding_rate = float(state_view.funding_rate) if state_view.funding_rate != 0 else 0.0
    exchange_ts_ms = int(state_view.exchange_ts_ms) if state_view.exchange_ts_ms > 0 else None
    ingest_ts_ms = int(state_view.ingest_ts_ms) if state_view.ingest_ts_ms > 0 else None
    market_sequence = int(state_view.market_sequence) if state_view.market_sequence > 0 else None
    connector_name = _canonical_connector_name(state_view.connector_name)
    trading_pair = state_view.trading_pair
    timestamp_ms = int(state_view.timestamp_ms)
    freshness_ts_ms = int(state_view.freshness_ts_ms)
    bid_levels = _extract_depth_levels(payload.get("bids"), descending=True)
    ask_levels = _extract_depth_levels(payload.get("asks"), descending=False)
    if not bid_levels and best_bid is not None and best_bid_size is not None:
        bid_levels = ((float(best_bid), float(best_bid_size)),)
    if not ask_levels and best_ask is not None and best_ask_size is not None:
        ask_levels = ((float(best_ask), float(best_ask_size)),)

    if mid_price <= 0:
        state.rejected_snapshots += 1
        return False, "non_positive_mid_price"
    if best_bid is not None and float(best_bid) <= 0:
        state.rejected_snapshots += 1
        return False, "non_positive_best_bid"
    if best_ask is not None and float(best_ask) <= 0:
        state.rejected_snapshots += 1
        return False, "non_positive_best_ask"
    if best_bid_size is not None and float(best_bid_size) <= 0:
        state.rejected_snapshots += 1
        return False, "non_positive_best_bid_size"
    if best_ask_size is not None and float(best_ask_size) <= 0:
        state.rejected_snapshots += 1
        return False, "non_positive_best_ask_size"
    if best_bid is not None and best_ask is not None and float(best_bid) >= float(best_ask):
        state.rejected_snapshots += 1
        return False, "invalid_top_of_book"

    normalized_connector = _normalize_connector_name(connector_name)
    if allowed_connectors and normalized_connector not in allowed_connectors:
        state.rejected_snapshots += 1
        return False, "connector_not_allowed"

    key = _pair_key(instance_name, connector_name, trading_pair)
    previous = state.pairs.get(key)
    incoming_order_key = market_payload_order_key(payload, entry_id=entry_id)
    previous_order_key = None
    if previous is not None:
        previous_order_key = (
            int(previous.exchange_ts_ms or previous.ingest_ts_ms or previous.timestamp_ms or previous.freshness_ts_ms),
            int(previous.market_sequence or 0),
            int(previous.timestamp_ms),
        )
    if previous_order_key is not None and incoming_order_key < previous_order_key:
        state.rejected_snapshots += 1
        return False, "out_of_order_snapshot"

    state.pairs[key] = PairSnapshot(
        connector_name=connector_name,
        trading_pair=trading_pair,
        instance_name=instance_name,
        timestamp_ms=timestamp_ms,
        freshness_ts_ms=freshness_ts_ms or market_payload_freshness_ts_ms(payload, entry_id=entry_id) or timestamp_ms,
        mid_price=mid_price,
        best_bid=best_bid,
        best_ask=best_ask,
        best_bid_size=best_bid_size,
        best_ask_size=best_ask_size,
        last_trade_price=last_trade_price,
        mark_price=mark_price,
        funding_rate=funding_rate,
        exchange_ts_ms=exchange_ts_ms,
        ingest_ts_ms=ingest_ts_ms,
        market_sequence=market_sequence,
        event_id=str(state_view.event_id or ""),
        source_event_type=event_type,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
    )
    state.accepted_snapshots += 1
    return True, "accepted"


def build_heartbeat_event(
    state: PaperExchangeState,
    service_instance_name: str,
    allowed_connectors: Set[str],
    stale_after_ms: int,
    consumer_group: str = "",
    consumer_name: str = "",
    now_ms: Optional[int] = None,
) -> PaperExchangeHeartbeatEvent:
    now = int(now_ms if now_ms is not None else _now_ms())
    ages = [max(0, now - int(s.freshness_ts_ms or s.timestamp_ms)) for s in state.pairs.values()]
    stale_pairs = sum(1 for age in ages if age > stale_after_ms)
    l1_ready_pairs = sum(
        1 for snapshot in state.pairs.values() if snapshot.best_bid is not None and snapshot.best_ask is not None
    )
    active_orders = sum(1 for order in state.orders_by_id.values() if order.state in _ACTIVE_ORDER_STATES)
    terminal_orders = sum(1 for order in state.orders_by_id.values() if order.state in _TERMINAL_ORDER_STATES)
    active_positions = sum(1 for position in state.positions_by_key.values() if not _is_flat_position(position))
    latency_avg_ms = (
        int(state.command_latency_ms_sum / state.command_latency_samples)
        if state.command_latency_samples > 0
        else 0
    )
    status = "ok" if ages and stale_pairs == 0 else "degraded"
    return PaperExchangeHeartbeatEvent(
        producer="paper_exchange_service",
        instance_name=service_instance_name,
        status=status,
        market_pairs_total=len(ages),
        stale_pairs=stale_pairs,
        newest_snapshot_age_ms=min(ages) if ages else 0,
        oldest_snapshot_age_ms=max(ages) if ages else 0,
        metadata={
            "allowed_connectors": ",".join(sorted(allowed_connectors)),
            "consumer_group": str(consumer_group or "").strip(),
            "consumer_name": str(consumer_name or "").strip(),
            "accepted_snapshots": str(state.accepted_snapshots),
            "rejected_snapshots": str(state.rejected_snapshots),
            "processed_commands": str(state.processed_commands),
            "rejected_commands": str(state.rejected_commands),
            "rejected_commands_stale_market": str(state.rejected_commands_stale_market),
            "rejected_commands_missing_market": str(state.rejected_commands_missing_market),
            "rejected_commands_disallowed_connector": str(state.rejected_commands_disallowed_connector),
            "rejected_commands_unauthorized_producer": str(state.rejected_commands_unauthorized_producer),
            "rejected_commands_namespace_collision": str(state.rejected_commands_namespace_collision),
            "rejected_commands_missing_privileged_metadata": str(
                state.rejected_commands_missing_privileged_metadata
            ),
            "privileged_commands_processed": str(state.privileged_commands_processed),
            "privileged_command_audit_published": str(state.privileged_command_audit_published),
            "privileged_command_audit_publish_failures": str(state.privileged_command_audit_publish_failures),
            "duplicate_command_events": str(state.duplicate_command_events),
            "reclaimed_pending_entries": str(state.reclaimed_pending_entries),
            "command_publish_failures": str(state.command_publish_failures),
            "idempotency_journal_size": str(len(state.command_results_by_id)),
            "orders_total": str(len(state.orders_by_id)),
            "orders_active": str(active_orders),
            "orders_terminal": str(terminal_orders),
            "positions_active": str(active_positions),
            "orders_pruned_total": str(state.orders_pruned_total),
            "l1_ready_pairs": str(l1_ready_pairs),
            "command_latency_samples": str(state.command_latency_samples),
            "command_latency_avg_ms": str(latency_avg_ms),
            "command_latency_max_ms": str(state.command_latency_ms_max),
            "generated_fill_events": str(state.generated_fill_events),
            "generated_partial_fill_events": str(state.generated_partial_fill_events),
            "market_fill_publish_failures": str(state.market_fill_publish_failures),
            "market_match_cycles": str(state.market_match_cycles),
            "reclaimed_pending_market_entries": str(state.reclaimed_pending_market_entries),
            "market_rows_not_acked": str(state.market_rows_not_acked),
            "deduplicated_market_fill_events": str(state.deduplicated_market_fill_events),
            "market_fill_invalid_transition_drops": str(state.market_fill_invalid_transition_drops),
            "market_fill_journal_write_failures": str(state.market_fill_journal_write_failures),
            "market_fill_journal_size": str(len(state.market_fill_events_by_id)),
            "market_row_fill_cap_hits": str(state.market_row_fill_cap_hits),
            "funding_events_generated": str(state.funding_events_generated),
            "funding_debit_events": str(state.funding_debit_events),
            "funding_credit_events": str(state.funding_credit_events),
            "funding_paid_quote_total": str(state.funding_paid_quote_total),
        },
    )


def handle_command_payload(
    payload: Dict[str, object],
    state: PaperExchangeState,
    service_instance_name: str,
    allowed_connectors: Optional[Set[str]] = None,
    allowed_command_producers: Optional[Set[str]] = None,
    market_stale_after_ms: int = 15_000,
    market_sweep_depth_levels: int = 1,
    command_sequence: int = 0,
    now_ms: Optional[int] = None,
) -> PaperExchangeEvent:
    now = int(now_ms if now_ms is not None else _now_ms())
    command_seq = max(0, int(command_sequence))
    allowed = set(allowed_connectors or set())
    allowed_producers = set(allowed_command_producers or set())
    try:
        command = PaperExchangeCommandEvent(**payload)
    except Exception:
        state.rejected_commands += 1
        return PaperExchangeEvent(
            producer="paper_exchange_service",
            instance_name=service_instance_name,
            command_event_id="",
            command="invalid",
            status="rejected",
            reason="invalid_schema",
            connector_name="",
            trading_pair="",
        )
    try:
        command_latency_ms = max(0, now - int(command.timestamp_ms))
    except Exception:
        command_latency_ms = 0
    state.command_latency_samples += 1
    state.command_latency_ms_sum += int(command_latency_ms)
    state.command_latency_ms_max = max(int(state.command_latency_ms_max), int(command_latency_ms))
    command_metadata = dict(command.metadata or {})
    resolved_connector_name = _canonical_connector_name(command.connector_name)
    if resolved_connector_name != str(command.connector_name or ""):
        try:
            command.connector_name = resolved_connector_name
        except Exception:
            pass

    normalized_producer = _normalize(command.producer)
    if allowed_producers and normalized_producer not in allowed_producers:
        state.rejected_commands += 1
        state.rejected_commands_unauthorized_producer += 1
        return _event_for_command(
            command=command,
            status="rejected",
            reason="unauthorized_producer",
            metadata={"producer": str(command.producer), "allowed_producers": ",".join(sorted(allowed_producers))},
        )

    if not str(command.instance_name or "").strip():
        state.rejected_commands += 1
        return _event_for_command(command=command, status="rejected", reason="missing_instance_name")

    if not str(command.connector_name or "").strip():
        state.rejected_commands += 1
        return _event_for_command(command=command, status="rejected", reason="missing_connector_name")

    if not str(command.trading_pair or "").strip():
        state.rejected_commands += 1
        return _event_for_command(command=command, status="rejected", reason="missing_trading_pair")

    normalized_connector = _normalize_connector_name(command.connector_name)
    if allowed and normalized_connector not in allowed:
        state.rejected_commands += 1
        state.rejected_commands_disallowed_connector += 1
        return _event_for_command(command=command, status="rejected", reason="connector_not_allowed")

    if _is_privileged_command(command.command):
        missing_privileged_metadata = _missing_privileged_metadata(command_metadata)
        if missing_privileged_metadata:
            state.rejected_commands += 1
            state.rejected_commands_missing_privileged_metadata += 1
            return _event_for_command(
                command=command,
                status="rejected",
                reason="missing_privileged_metadata",
                metadata={"missing_fields": ",".join(missing_privileged_metadata)},
            )

    if command.expires_at_ms is not None and now > int(command.expires_at_ms):
        state.rejected_commands += 1
        return _event_for_command(command=command, status="rejected", reason="expired_command")

    # Non-sync commands require fresh market snapshots from real exchange feed.
    pair_snapshot: Optional[PairSnapshot] = None
    if command.command != "sync_state":
        pair_snapshot = _get_pair_snapshot(
            state,
            command.instance_name,
            command.connector_name,
            command.trading_pair,
        )
        if pair_snapshot is None:
            state.rejected_commands += 1
            state.rejected_commands_missing_market += 1
            return _event_for_command(command=command, status="rejected", reason="no_market_snapshot")
        snapshot_age_ms = max(0, now - int(pair_snapshot.freshness_ts_ms or pair_snapshot.timestamp_ms))
        if snapshot_age_ms > int(max(1_000, market_stale_after_ms)):
            state.rejected_commands += 1
            state.rejected_commands_stale_market += 1
            return _event_for_command(
                command=command,
                status="rejected",
                reason="stale_market_snapshot",
                metadata={"snapshot_age_ms": str(snapshot_age_ms)},
            )

    if command.command == "sync_state":
        state.processed_commands += 1
        return _event_for_command(
            command=command,
            status="processed",
            reason="sync_state_accepted",
            metadata={
                "market_pairs_total": str(len(state.pairs)),
                "accepted_snapshots": str(state.accepted_snapshots),
                "command_sequence": str(command_seq),
            },
        )

    if command.command == "submit_order":
        order_id = str(command.order_id or "").strip()
        if not order_id:
            state.rejected_commands += 1
            return _event_for_command(command=command, status="rejected", reason="missing_order_id")

        existing_order = state.orders_by_id.get(order_id)
        if existing_order is not None:
            existing_namespace = _namespace_base_key(
                existing_order.instance_name,
                existing_order.connector_name,
                existing_order.trading_pair,
            )
            command_namespace = _namespace_base_key(
                command.instance_name,
                command.connector_name,
                command.trading_pair,
            )
            if existing_namespace != command_namespace:
                state.rejected_commands += 1
                state.rejected_commands_namespace_collision += 1
                return _event_for_command(
                    command=command,
                    status="rejected",
                    reason="order_id_namespace_collision",
                    metadata={
                        "existing_namespace": existing_namespace,
                        "command_namespace": command_namespace,
                    },
                )
            state.rejected_commands += 1
            return _event_for_command(
                command=command,
                status="rejected",
                reason="duplicate_order_id",
                metadata={"existing_state": existing_order.state},
            )

        side = _normalize(command.side or "")
        if side not in {"buy", "sell"}:
            state.rejected_commands += 1
            return _event_for_command(command=command, status="rejected", reason="invalid_side")

        amount_base = float(command.amount_base or 0.0)
        if amount_base <= 0:
            state.rejected_commands += 1
            return _event_for_command(command=command, status="rejected", reason="invalid_amount_base")

        order_type = _normalize(command.order_type or "limit")
        if order_type not in _SUPPORTED_ORDER_TYPES:
            state.rejected_commands += 1
            return _event_for_command(
                command=command,
                status="rejected",
                reason="unsupported_order_type",
                metadata={"supported_order_types": ",".join(sorted(_SUPPORTED_ORDER_TYPES))},
            )

        metadata = dict(command.metadata or {})
        maker_fee_pct, taker_fee_pct, leverage, margin_mode, funding_rate = _resolve_accounting_contract(
            metadata,
            pair_snapshot=pair_snapshot,
        )
        time_in_force = _coerce_time_in_force(metadata)
        if not time_in_force:
            state.rejected_commands += 1
            return _event_for_command(
                command=command,
                status="rejected",
                reason="unsupported_time_in_force",
                metadata={"supported_time_in_force": ",".join(sorted(_SUPPORTED_TIME_IN_FORCE))},
            )

        reduce_only = _parse_bool(metadata.get("reduce_only"), default=False)
        position_action = str(command.position_action or metadata.get("position_action") or "auto").strip().lower() or "auto"
        position_mode = str(command.position_mode or metadata.get("position_mode") or "ONEWAY").strip().upper() or "ONEWAY"
        post_only = bool(order_type == "post_only" or _parse_bool(metadata.get("post_only"), default=False))
        best_bid = _snapshot_best_bid(pair_snapshot)
        best_ask = _snapshot_best_ask(pair_snapshot)
        best_bid_size = _snapshot_best_bid_size(pair_snapshot)
        best_ask_size = _snapshot_best_ask_size(pair_snapshot)
        market_reference_price = _market_execution_price(side, pair_snapshot) if order_type == "market" else None
        constraint_error = _validate_order_constraints(
            metadata=metadata,
            order_type=order_type,
            amount_base=amount_base,
            price=float(command.price) if command.price is not None else None,
            market_reference_price=market_reference_price,
        )
        if constraint_error is not None:
            state.rejected_commands += 1
            reason, details = constraint_error
            return _event_for_command(
                command=command,
                status="rejected",
                reason=reason,
                metadata=details,
            )
        initial_state = "working"
        reason = "order_accepted"
        fill_price: Optional[float] = None
        fill_notional_quote: Optional[float] = None
        is_maker = True
        initial_filled_base = 0.0
        initial_filled_quote = 0.0
        initial_filled_fee_quote = 0.0
        initial_fill_fee_rate_pct = 0.0
        initial_margin_reserve_quote = 0.0
        initial_fill_count = 0
        initial_last_fill_snapshot_event_id = ""

        if order_type == "market":
            order_price = float(_market_execution_price(side, pair_snapshot) or 0.0)
            if order_price <= 0:
                state.rejected_commands += 1
                return _event_for_command(command=command, status="rejected", reason="invalid_market_reference_price")
            initial_state = "filled"
            reason = "order_filled_market"
            fill_price = order_price
            fill_notional_quote = amount_base * fill_price
            is_maker = False
            initial_filled_base = amount_base
            initial_filled_quote = float(fill_notional_quote)
            initial_fill_count = 1
        else:
            if command.price is None or float(command.price) <= 0:
                state.rejected_commands += 1
                return _event_for_command(command=command, status="rejected", reason="invalid_price")
            order_price = float(command.price)
            crosses = _crosses_book(side, order_price, best_bid, best_ask)

            if post_only and crosses:
                state.rejected_commands += 1
                return _event_for_command(
                    command=command,
                    status="rejected",
                    reason="post_only_would_take",
                    metadata={
                        "best_bid": str(best_bid) if best_bid is not None else "",
                        "best_ask": str(best_ask) if best_ask is not None else "",
                    },
                )

            if crosses:
                cross_levels = _contra_levels_for_snapshot(
                    pair_snapshot,
                    side=side,
                    max_levels=max(1, int(market_sweep_depth_levels)),
                    limit_price=order_price,
                )
                cross_fill_amount, cross_fill_price = _sweep_fill_from_levels(
                    amount_base=amount_base,
                    levels=cross_levels,
                )
                fill_price = float(cross_fill_price if cross_fill_price is not None else order_price)
                cross_fill_amount = max(0.0, float(cross_fill_amount))
                if cross_fill_amount <= _MIN_FILL_EPSILON:
                    state.rejected_commands += 1
                    return _event_for_command(
                        command=command,
                        status="rejected",
                        reason="insufficient_top_of_book_liquidity",
                    )
                initial_state, reason, effective_fill_amount = resolve_crossing_limit_order_outcome(
                    amount_base=amount_base,
                    immediate_fill_amount=cross_fill_amount,
                    time_in_force=time_in_force,
                    min_fill_epsilon=_MIN_FILL_EPSILON,
                )
                if effective_fill_amount > _MIN_FILL_EPSILON:
                    fill_notional_quote = effective_fill_amount * fill_price
                    is_maker = False
                    initial_filled_base = effective_fill_amount
                    initial_filled_quote = float(fill_notional_quote)
                    initial_fill_count = 1
            elif time_in_force in {"ioc", "fok"}:
                # Deterministic baseline: no book cross means IOC/FOK cannot execute.
                initial_state = "expired"
                reason = "time_in_force_expired_no_fill"

        if initial_filled_quote > _MIN_FILL_EPSILON:
            initial_filled_fee_quote, initial_fill_fee_rate_pct = _calc_fill_fee_quote(
                fill_notional_quote=initial_filled_quote,
                is_maker=is_maker,
                maker_fee_pct=maker_fee_pct,
                taker_fee_pct=taker_fee_pct,
            )
            initial_margin_reserve_quote = _calc_margin_reserve_quote(
                filled_notional_quote_total=initial_filled_quote,
                leverage=leverage,
                margin_mode=margin_mode,
            )

        order_record = OrderRecord(
            order_id=order_id,
            instance_name=command.instance_name,
            connector_name=command.connector_name,
            trading_pair=command.trading_pair,
            side=side,
            order_type=order_type,
            amount_base=amount_base,
            price=order_price,
            time_in_force=time_in_force,
            reduce_only=reduce_only,
            post_only=post_only,
            state=initial_state,
            created_ts_ms=now,
            updated_ts_ms=now,
            last_command_event_id=command.event_id,
            last_fill_snapshot_event_id=(
                str(pair_snapshot.event_id)
                if pair_snapshot is not None and initial_filled_base > _MIN_FILL_EPSILON
                else initial_last_fill_snapshot_event_id
            ),
            last_fill_amount_base=initial_filled_base if initial_filled_base > _MIN_FILL_EPSILON else 0.0,
            filled_base=initial_filled_base,
            filled_quote=initial_filled_quote,
            first_fill_ts_ms=(now if initial_filled_base > _MIN_FILL_EPSILON else 0),
            fill_count=initial_fill_count,
            filled_fee_quote=initial_filled_fee_quote,
            margin_reserve_quote=initial_margin_reserve_quote,
            maker_fee_pct=maker_fee_pct,
            taker_fee_pct=taker_fee_pct,
            leverage=leverage,
            margin_mode=margin_mode,
            funding_rate=funding_rate,
            position_action=position_action,
            position_mode=position_mode,
        )
        state.orders_by_id[order_id] = order_record
        if order_record.filled_base > _MIN_FILL_EPSILON:
            _apply_position_fill(
                state=state,
                order=order_record,
                fill_amount_base=order_record.filled_base,
                fill_price=float(fill_price if fill_price is not None else order_record.price),
                now_ms=now,
            )
        state.processed_commands += 1
        event_metadata = _order_metadata(order_record)
        event_metadata.update(
            {
                "command_sequence": str(command_seq),
                "best_bid": str(best_bid) if best_bid is not None else "",
                "best_ask": str(best_ask) if best_ask is not None else "",
                "best_bid_size": str(best_bid_size) if best_bid_size is not None else "",
                "best_ask_size": str(best_ask_size) if best_ask_size is not None else "",
                "snapshot_funding_rate": str(pair_snapshot.funding_rate) if pair_snapshot and pair_snapshot.funding_rate is not None else "",
                "accounting_contract_version": str(metadata.get("accounting_contract_version", "paper_exchange_v1")),
            }
        )
        fee_source = str(metadata.get("fee_source", "")).strip()
        if fee_source:
            event_metadata["fee_source"] = fee_source
        if order_record.filled_base > _MIN_FILL_EPSILON:
            event_metadata.update(
                {
                    "fill_price": str(fill_price if fill_price is not None else order_record.price),
                    "fill_amount_base": str(order_record.filled_base),
                    "fill_notional_quote": str(
                        fill_notional_quote
                        if fill_notional_quote is not None
                        else order_record.filled_base * order_record.price
                    ),
                    "fill_fee_quote": str(initial_filled_fee_quote),
                    "fill_fee_rate_pct": str(initial_fill_fee_rate_pct),
                    "is_maker": "1" if is_maker else "0",
                    "filled_fee_quote_total": str(order_record.filled_fee_quote),
                    "margin_reserve_quote": str(order_record.margin_reserve_quote),
                    "funding_rate": str(order_record.funding_rate),
                }
            )
        return _event_for_command(
            command=command,
            status="processed",
            reason=reason,
            metadata=event_metadata,
        )

    if command.command == "cancel_order":
        order_id = str(command.order_id or "").strip()
        if not order_id:
            state.rejected_commands += 1
            return _event_for_command(command=command, status="rejected", reason="missing_order_id")

        order = state.orders_by_id.get(order_id)
        if order is None:
            state.rejected_commands += 1
            return _event_for_command(command=command, status="rejected", reason="order_not_found")

        if (
            order.instance_name != command.instance_name
            or _normalize(order.connector_name) != normalized_connector
            or str(order.trading_pair).upper() != str(command.trading_pair).upper()
        ):
            state.rejected_commands += 1
            return _event_for_command(command=command, status="rejected", reason="order_scope_mismatch")

        if not can_transition_state(order.state, "cancelled"):
            state.rejected_commands += 1
            return _event_for_command(
                command=command,
                status="rejected",
                reason="order_not_cancellable",
                metadata={"current_state": order.state},
            )

        order.state = "cancelled"
        order.updated_ts_ms = now
        order.last_command_event_id = command.event_id
        state.processed_commands += 1
        cancel_metadata = _order_metadata(order)
        cancel_metadata["command_sequence"] = str(command_seq)
        return _event_for_command(
            command=command,
            status="processed",
            reason="order_cancelled",
            metadata=cancel_metadata,
        )

    if command.command == "cancel_all":
        cancelled_count = 0
        for order in state.orders_by_id.values():
            if (
                order.instance_name != command.instance_name
                or _normalize(order.connector_name) != normalized_connector
                or str(order.trading_pair).upper() != str(command.trading_pair).upper()
            ):
                continue
            if can_transition_state(order.state, "cancelled") and order.state != "cancelled":
                order.state = "cancelled"
                order.updated_ts_ms = now
                order.last_command_event_id = command.event_id
                cancelled_count += 1
        state.processed_commands += 1
        state.privileged_commands_processed += 1
        return _event_for_command(
            command=command,
            status="processed",
            reason="cancel_all_processed",
            metadata={"cancelled_count": str(cancelled_count), "command_sequence": str(command_seq)},
        )

    # Defensive fallback (schema enum should already prevent this branch).
    if command.command != "sync_state":
        state.rejected_commands += 1
        return _event_for_command(command=command, status="rejected", reason="unsupported_command")

    state.processed_commands += 1
    return _event_for_command(command=command, status="processed", reason="sync_state_accepted")


def _ack_entries(client: RedisStreamClient, stream: str, group: str, entry_ids: List[str]) -> None:
    if not entry_ids:
        return
    ack_many = getattr(client, "ack_many", None)
    if callable(ack_many):
        ack_many(stream, group, entry_ids)
        return
    for entry_id in entry_ids:
        client.ack(stream, group, entry_id)


def process_command_rows(
    *,
    rows: List[Tuple[str, Dict[str, object]]],
    source: str,
    client: RedisStreamClient,
    state: PaperExchangeState,
    settings: ServiceSettings,
    command_journal_path: Path,
    state_snapshot_path: Optional[Path] = None,
) -> None:
    ack_entry_ids: List[str] = []
    for entry_id, payload in rows:
        parsed_command: Optional[PaperExchangeCommandEvent] = None
        command_event_id = ""
        command_metadata: Dict[str, str] = {}
        command_is_privileged = False
        command_name = ""
        command_mutates_orders = False
        command_is_sync_state = False
        track_command_result = False
        command_producer = ""
        command_producer_authorized = True
        try:
            parsed_command = PaperExchangeCommandEvent(**payload)
            command_event_id = str(parsed_command.event_id or "").strip()
            command_metadata = dict(parsed_command.metadata or {})
            command_name = _normalize(parsed_command.command)
            command_producer = str(parsed_command.producer or "")
            if settings.allowed_command_producers:
                command_producer_authorized = _normalize(command_producer) in settings.allowed_command_producers
            command_mutates_orders = command_name in {"submit_order", "cancel_order", "cancel_all"}
            command_is_sync_state = command_name == "sync_state"
            command_is_privileged = _is_privileged_command(parsed_command.command)
            track_command_result = bool(command_event_id)
            if command_is_sync_state and track_command_result:
                is_load_harness_command = _parse_bool(command_metadata.get("load_harness"), default=False)
                track_command_result = bool(settings.persist_sync_state_results) and not is_load_harness_command
        except Exception:
            parsed_command = None

        existing_record = (
            state.command_results_by_id.get(command_event_id) if (track_command_result and command_event_id) else None
        )
        if command_event_id and existing_record is not None:
            state.duplicate_command_events += 1
            if source == "reclaimed":
                state.reclaimed_pending_entries += 1
            if parsed_command is not None and command_is_privileged and isinstance(existing_record, dict):
                audit_required = _bool_from_record(existing_record, "audit_required", default=True)
                audit_published = _bool_from_record(existing_record, "audit_published", default=False)
                if audit_required and not audit_published:
                    audit_event = _build_privileged_audit_event(
                        command=parsed_command,
                        result_status=str(existing_record.get("status", "")),
                        result_reason=str(existing_record.get("reason", "")),
                        command_metadata=command_metadata,
                    )
                    audit_publish_result = client.xadd(
                        stream=settings.audit_stream,
                        payload=audit_event.model_dump(),
                        maxlen=STREAM_RETENTION_MAXLEN.get(settings.audit_stream),
                    )
                    if audit_publish_result is None:
                        state.privileged_command_audit_publish_failures += 1
                        logger.warning(
                            "paper_exchange privileged command audit publish failed on replay for entry=%s source=%s",
                            entry_id,
                            source,
                        )
                        continue
                    existing_record["audit_published"] = True
                    state.privileged_command_audit_published += 1
                    try:
                        _persist_command_journal(command_journal_path, state.command_results_by_id)
                    except Exception as exc:
                        logger.warning("paper_exchange command journal persist failed: %s", exc)
            ack_entry_ids.append(str(entry_id))
            continue

        command_sequence = _entry_sequence_from_stream_id(str(entry_id))
        result_event = handle_command_payload(
            payload=payload,
            state=state,
            service_instance_name=settings.service_instance_name,
            allowed_connectors=settings.allowed_connectors,
            allowed_command_producers=settings.allowed_command_producers,
            market_stale_after_ms=settings.market_stale_after_ms,
            market_sweep_depth_levels=settings.market_sweep_depth_levels,
            command_sequence=command_sequence,
        )
        if command_mutates_orders:
            _prune_orders(
                state=state,
                now_ms=_now_ms(),
                terminal_order_ttl_ms=settings.terminal_order_ttl_ms,
                max_orders_tracked=settings.max_orders_tracked,
            )
        result_payload = result_event.model_dump()
        identity_ok, identity_reason = validate_event_identity(result_payload)
        if not identity_ok:
            state.command_publish_failures += 1
            logger.warning(
                "paper_exchange command result dropped due to identity contract entry=%s source=%s reason=%s result_reason=%s",
                entry_id,
                source,
                identity_reason,
                result_event.reason,
            )
            if source == "reclaimed":
                state.reclaimed_pending_entries += 1
            ack_entry_ids.append(str(entry_id))
            continue
        publish_result = client.xadd(
            stream=settings.event_stream,
            payload=result_payload,
            maxlen=STREAM_RETENTION_MAXLEN.get(settings.event_stream),
        )
        if publish_result is None:
            state.command_publish_failures += 1
            logger.warning("paper_exchange command result publish failed for entry=%s source=%s", entry_id, source)
            continue

        audit_required = parsed_command is not None and command_is_privileged
        audit_published = not audit_required
        if audit_required and parsed_command is not None:
            audit_event = _build_privileged_audit_event(
                command=parsed_command,
                result_status=result_event.status,
                result_reason=result_event.reason,
                command_metadata=command_metadata,
            )
            audit_publish_result = client.xadd(
                stream=settings.audit_stream,
                payload=audit_event.model_dump(),
                maxlen=STREAM_RETENTION_MAXLEN.get(settings.audit_stream),
            )
            if audit_publish_result is None:
                state.privileged_command_audit_publish_failures += 1
                logger.warning(
                    "paper_exchange privileged command audit publish failed for entry=%s source=%s",
                    entry_id,
                    source,
                )
                audit_published = False
                if command_event_id:
                    state.command_results_by_id[command_event_id] = _command_result_record(
                        result_event,
                        audit_required=True,
                        audit_published=False,
                        command_metadata=command_metadata,
                        command_producer=command_producer,
                        producer_authorized=command_producer_authorized,
                    )
                    try:
                        _persist_command_journal(command_journal_path, state.command_results_by_id)
                    except Exception as exc:
                        logger.warning("paper_exchange command journal persist failed: %s", exc)
                # Leave entry pending to re-attempt audit publish without repeating side effects.
                continue
            audit_published = True
            state.privileged_command_audit_published += 1

        if track_command_result and command_event_id:
            state.command_results_by_id[command_event_id] = _command_result_record(
                result_event,
                audit_required=audit_required,
                audit_published=audit_published,
                command_metadata=command_metadata,
                command_producer=command_producer,
                producer_authorized=command_producer_authorized,
            )
            try:
                _persist_command_journal(command_journal_path, state.command_results_by_id)
            except Exception as exc:
                logger.warning("paper_exchange command journal persist failed: %s", exc)
        if state_snapshot_path is not None and command_mutates_orders:
            try:
                _persist_state_snapshot(
                    state_snapshot_path,
                    state.orders_by_id,
                    state.positions_by_key,
                    funding_summary=_funding_summary(state),
                )
            except Exception as exc:
                logger.warning("paper_exchange state snapshot persist failed: %s", exc)

        if source == "reclaimed":
            state.reclaimed_pending_entries += 1
        ack_entry_ids.append(str(entry_id))
    _ack_entries(client, settings.command_stream, settings.consumer_group, ack_entry_ids)


def process_market_rows(
    *,
    rows: List[Tuple[str, Dict[str, object]]],
    source: str,
    client: RedisStreamClient,
    state: PaperExchangeState,
    settings: ServiceSettings,
    state_snapshot_path: Optional[Path] = None,
    pair_snapshot_path: Optional[Path] = None,
    market_fill_journal_path: Optional[Path] = None,
) -> None:
    for entry_id, payload in rows:
        ok, _reason = ingest_market_snapshot_payload(
            payload=payload,
            state=state,
            allowed_connectors=settings.allowed_connectors,
            entry_id=str(entry_id),
        )
        if not ok:
            if source == "reclaimed":
                state.reclaimed_pending_market_entries += 1
            client.ack(settings.market_data_stream, settings.consumer_group, entry_id)
            continue

        snapshot = _get_pair_snapshot(
            state,
            str(payload.get("instance_name", "")),
            str(payload.get("connector_name", "")),
            str(payload.get("trading_pair", "")),
        )
        if snapshot is None:
            if source == "reclaimed":
                state.reclaimed_pending_market_entries += 1
            client.ack(settings.market_data_stream, settings.consumer_group, entry_id)
            continue
        if pair_snapshot_path is not None:
            try:
                _persist_pair_snapshot(pair_snapshot_path, state.pairs)
            except Exception as exc:
                logger.warning("paper_exchange pair snapshot persist failed: %s", exc)

        state.market_match_cycles += 1
        applied_count = 0
        publish_failed = False
        persist_failed = False
        cap_hit = False
        for candidate in _build_fill_candidates_for_snapshot(
            state=state,
            snapshot=snapshot,
            resting_fill_latency_ms=settings.resting_fill_latency_ms,
            maker_queue_participation=settings.maker_queue_participation,
            market_sweep_depth_levels=settings.market_sweep_depth_levels,
        ):
            if applied_count >= max(1, int(settings.max_fill_events_per_market_row)):
                state.market_row_fill_cap_hits += 1
                logger.warning(
                    "paper_exchange market row fill cap reached | entry=%s cap=%s",
                    entry_id,
                    settings.max_fill_events_per_market_row,
                )
                cap_hit = True
                break
            order = state.orders_by_id.get(candidate.order_id)
            if order is None:
                continue
            if not can_transition_state(order.state, candidate.new_state):
                state.market_fill_invalid_transition_drops += 1
                logger.warning(
                    "paper_exchange invalid transition dropped | order_id=%s from=%s to=%s source=process_market_rows",
                    order.order_id,
                    order.state,
                    candidate.new_state,
                )
                continue
            fill_event = _market_fill_event_from_candidate(order=order, snapshot=snapshot, candidate=candidate)
            event_id = str(fill_event.event_id or "")
            event_already_published = bool(event_id and event_id in state.market_fill_events_by_id)
            if event_already_published:
                state.deduplicated_market_fill_events += 1
            else:
                fill_payload = fill_event.model_dump()
                fill_identity_ok, fill_identity_reason = validate_event_identity(fill_payload)
                if not fill_identity_ok:
                    state.market_fill_publish_failures += 1
                    logger.warning(
                        "paper_exchange market fill dropped due to identity contract | entry=%s order_id=%s reason=%s",
                        entry_id,
                        order.order_id,
                        fill_identity_reason,
                    )
                    continue
                publish_result = client.xadd(
                    stream=settings.event_stream,
                    payload=fill_payload,
                    maxlen=STREAM_RETENTION_MAXLEN.get(settings.event_stream),
                )
                if publish_result is None:
                    state.market_fill_publish_failures += 1
                    logger.warning(
                        "paper_exchange market fill publish failed | entry=%s order_id=%s",
                        entry_id,
                        order.order_id,
                    )
                    publish_failed = True
                    break
                if event_id:
                    state.market_fill_journal_next_seq += 1
                    state.market_fill_events_by_id[event_id] = int(state.market_fill_journal_next_seq)
                    _trim_market_fill_journal(
                        state.market_fill_events_by_id,
                        max_entries=settings.market_fill_journal_max_entries,
                    )
                    if market_fill_journal_path is not None:
                        try:
                            _persist_market_fill_journal(
                                market_fill_journal_path,
                                state.market_fill_events_by_id,
                                max_entries=settings.market_fill_journal_max_entries,
                            )
                        except Exception as exc:
                            state.market_fill_journal_write_failures += 1
                            logger.warning("paper_exchange market fill journal persist failed: %s", exc)
                            persist_failed = True
                            break

            if not _apply_fill_candidate(order, candidate, now_ms=_now_ms()):
                state.market_fill_invalid_transition_drops += 1
                continue
            _apply_position_fill(
                state=state,
                order=order,
                fill_amount_base=float(candidate.fill_amount_base),
                fill_price=float(candidate.fill_price),
                now_ms=_now_ms(),
            )
            if not event_already_published:
                state.generated_fill_events += 1
                if candidate.new_state == "partially_filled":
                    state.generated_partial_fill_events += 1
            applied_count += 1
            if state_snapshot_path is not None:
                try:
                    _persist_state_snapshot(
                        state_snapshot_path,
                        state.orders_by_id,
                        state.positions_by_key,
                        funding_summary=_funding_summary(state),
                    )
                except Exception as exc:
                    logger.warning("paper_exchange state snapshot persist failed after market fill: %s", exc)
                    persist_failed = True
                    break

        if not publish_failed and not persist_failed and not cap_hit:
            funding_events = _funding_events_for_snapshot(
                state=state,
                snapshot=snapshot,
                funding_interval_ms=settings.funding_interval_ms,
                now_ms=int(snapshot.freshness_ts_ms or snapshot.timestamp_ms or _now_ms()),
            )
            for funding_event in funding_events:
                funding_payload = funding_event.event.model_dump()
                identity_ok, identity_reason = validate_event_identity(funding_payload)
                if not identity_ok:
                    state.command_publish_failures += 1
                    logger.warning(
                        "paper_exchange funding settlement dropped due to identity contract | entry=%s pair=%s reason=%s",
                        entry_id,
                        snapshot.trading_pair,
                        identity_reason,
                    )
                    publish_failed = True
                    break
                publish_result = client.xadd(
                    stream=settings.event_stream,
                    payload=funding_payload,
                    maxlen=STREAM_RETENTION_MAXLEN.get(settings.event_stream),
                )
                if publish_result is None:
                    state.command_publish_failures += 1
                    logger.warning(
                        "paper_exchange funding settlement publish failed | entry=%s pair=%s",
                        entry_id,
                        snapshot.trading_pair,
                    )
                    publish_failed = True
                    break
                _commit_funding_settlement(state, funding_event)
            if not publish_failed and state_snapshot_path is not None and funding_events:
                try:
                    _persist_state_snapshot(
                        state_snapshot_path,
                        state.orders_by_id,
                        state.positions_by_key,
                        funding_summary=_funding_summary(state),
                    )
                except Exception as exc:
                    logger.warning("paper_exchange state snapshot persist failed after funding settlement: %s", exc)
                    persist_failed = True

        _prune_orders(
            state=state,
            now_ms=_now_ms(),
            terminal_order_ttl_ms=settings.terminal_order_ttl_ms,
            max_orders_tracked=settings.max_orders_tracked,
        )

        if publish_failed or persist_failed or cap_hit:
            state.market_rows_not_acked += 1
            # Leave market row pending so replay can recover remaining fill work.
            continue

        if source == "reclaimed":
            state.reclaimed_pending_market_entries += 1
        client.ack(settings.market_data_stream, settings.consumer_group, entry_id)


def run(settings: ServiceSettings) -> None:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    command_journal_path = _resolve_path(settings.command_journal_path, root)
    state_snapshot_path = _resolve_path(settings.state_snapshot_path, root)
    pair_snapshot_path = _resolve_path(settings.pair_snapshot_path, root)
    market_fill_journal_path = _resolve_path(settings.market_fill_journal_path, root)
    client = RedisStreamClient(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        enabled=settings.redis_enabled,
    )
    client.create_group(settings.market_data_stream, settings.consumer_group)
    client.create_group(settings.command_stream, settings.consumer_group)
    state = PaperExchangeState()
    state.command_results_by_id = _load_command_journal(command_journal_path)
    state.orders_by_id = _load_state_snapshot(state_snapshot_path)
    state.positions_by_key = _load_position_snapshot(state_snapshot_path)
    state.market_fill_events_by_id = _load_market_fill_journal(market_fill_journal_path)
    state.market_fill_journal_next_seq = (
        max(state.market_fill_events_by_id.values()) if state.market_fill_events_by_id else 0
    )
    _trim_market_fill_journal(
        state.market_fill_events_by_id,
        max_entries=settings.market_fill_journal_max_entries,
    )
    _prune_orders(
        state=state,
        now_ms=_now_ms(),
        terminal_order_ttl_ms=settings.terminal_order_ttl_ms,
        max_orders_tracked=settings.max_orders_tracked,
    )
    if state.command_results_by_id:
        logger.info(
            "paper_exchange idempotency journal loaded | entries=%s path=%s",
            len(state.command_results_by_id),
            command_journal_path,
        )
    if state.orders_by_id:
        logger.info(
            "paper_exchange order snapshot loaded | orders=%s path=%s",
            len(state.orders_by_id),
            state_snapshot_path,
        )
    if state.market_fill_events_by_id:
        logger.info(
            "paper_exchange market fill journal loaded | entries=%s path=%s",
            len(state.market_fill_events_by_id),
            market_fill_journal_path,
        )
    last_heartbeat_ms = 0
    last_pending_reclaim_ms = 0
    last_market_pending_reclaim_ms = 0
    logger.info(
        "paper_exchange_service started | market_stream=%s command_stream=%s audit_stream=%s connectors=%s",
        settings.market_data_stream,
        settings.command_stream,
        settings.audit_stream,
        ",".join(sorted(settings.allowed_connectors)) or "*",
    )

    while True:
        reclaimed_market_rows: List[Tuple[str, Dict[str, object]]] = []
        now = _now_ms()
        if (
            settings.market_pending_reclaim_enabled
            and (now - last_market_pending_reclaim_ms) >= max(1_000, settings.market_pending_reclaim_interval_ms)
        ):
            reclaimed_market_rows = client.claim_pending(
                stream=settings.market_data_stream,
                group=settings.consumer_group,
                consumer=settings.consumer_name,
                min_idle_ms=max(1_000, settings.market_pending_reclaim_idle_ms),
                count=max(1, settings.market_pending_reclaim_count),
                start_id="0-0",
            )
            last_market_pending_reclaim_ms = now
            if reclaimed_market_rows:
                logger.info("paper_exchange reclaimed pending market snapshots=%s", len(reclaimed_market_rows))

        if reclaimed_market_rows:
            process_market_rows(
                rows=reclaimed_market_rows,
                source="reclaimed",
                client=client,
                state=state,
                settings=settings,
                state_snapshot_path=state_snapshot_path,
                pair_snapshot_path=pair_snapshot_path,
                market_fill_journal_path=market_fill_journal_path,
            )

        market_rows = client.read_group(
            stream=settings.market_data_stream,
            group=settings.consumer_group,
            consumer=settings.consumer_name,
            count=settings.read_count,
            # Keep this near non-blocking so command latency isn't gated by sparse market flow.
            block_ms=min(max(1, int(settings.read_block_ms)), 10),
        )
        if market_rows:
            process_market_rows(
                rows=market_rows,
                source="new",
                client=client,
                state=state,
                settings=settings,
                state_snapshot_path=state_snapshot_path,
                pair_snapshot_path=pair_snapshot_path,
                market_fill_journal_path=market_fill_journal_path,
            )

        command_rows = client.read_group(
            stream=settings.command_stream,
            group=settings.consumer_group,
            consumer=settings.consumer_name,
            count=settings.read_count,
            block_ms=1,
        )
        reclaimed_rows: List[Tuple[str, Dict[str, object]]] = []
        now = _now_ms()
        if (
            settings.pending_reclaim_enabled
            and (now - last_pending_reclaim_ms) >= max(1_000, settings.pending_reclaim_interval_ms)
        ):
            reclaimed_rows = client.claim_pending(
                stream=settings.command_stream,
                group=settings.consumer_group,
                consumer=settings.consumer_name,
                min_idle_ms=max(1_000, settings.pending_reclaim_idle_ms),
                count=max(1, settings.pending_reclaim_count),
                start_id="0-0",
            )
            last_pending_reclaim_ms = now
            if reclaimed_rows:
                logger.info("paper_exchange reclaimed pending commands=%s", len(reclaimed_rows))

        if reclaimed_rows:
            process_command_rows(
                rows=reclaimed_rows,
                source="reclaimed",
                client=client,
                state=state,
                settings=settings,
                command_journal_path=command_journal_path,
                state_snapshot_path=state_snapshot_path,
            )
        if command_rows:
            process_command_rows(
                rows=command_rows,
                source="new",
                client=client,
                state=state,
                settings=settings,
                command_journal_path=command_journal_path,
                state_snapshot_path=state_snapshot_path,
            )

        now = _now_ms()
        if now - last_heartbeat_ms >= settings.heartbeat_interval_ms:
            try:
                _persist_pair_snapshot(pair_snapshot_path, state.pairs)
            except Exception as exc:
                logger.warning("paper_exchange pair snapshot persist failed: %s", exc)
            heartbeat = build_heartbeat_event(
                state=state,
                service_instance_name=settings.service_instance_name,
                allowed_connectors=settings.allowed_connectors,
                stale_after_ms=settings.market_stale_after_ms,
                consumer_group=settings.consumer_group,
                consumer_name=settings.consumer_name,
                now_ms=now,
            )
            client.xadd(
                stream=settings.heartbeat_stream,
                payload=heartbeat.model_dump(),
                maxlen=STREAM_RETENTION_MAXLEN.get(settings.heartbeat_stream),
            )
            last_heartbeat_ms = now


def _parse_args() -> ServiceSettings:
    parser = argparse.ArgumentParser(description="Paper Exchange Service (semi-pro baseline).")
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "127.0.0.1"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--redis-db", type=int, default=int(os.getenv("REDIS_DB", "0")))
    parser.add_argument("--redis-password", default=os.getenv("REDIS_PASSWORD", ""))
    parser.add_argument(
        "--redis-enabled",
        default=os.getenv("REDIS_STREAMS_ENABLED", "true"),
        help="Set to false to disable redis stream I/O.",
    )
    parser.add_argument(
        "--service-instance-name",
        default=os.getenv("PAPER_EXCHANGE_SERVICE_INSTANCE_NAME", "paper_exchange"),
    )
    parser.add_argument(
        "--consumer-group",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_GROUP", "hb_group_paper_exchange"),
    )
    parser.add_argument(
        "--consumer-name",
        default=os.getenv("PAPER_EXCHANGE_CONSUMER_NAME", f"paper-exchange-{os.getpid()}"),
    )
    parser.add_argument(
        "--market-stream",
        default=os.getenv("PAPER_EXCHANGE_MARKET_STREAM", MARKET_QUOTE_STREAM),
        help="Redis stream carrying market snapshots.",
    )
    parser.add_argument(
        "--command-stream",
        default=os.getenv("PAPER_EXCHANGE_COMMAND_STREAM", PAPER_EXCHANGE_COMMAND_STREAM),
        help="Redis stream carrying paper-exchange commands.",
    )
    parser.add_argument(
        "--event-stream",
        default=os.getenv("PAPER_EXCHANGE_EVENT_STREAM", PAPER_EXCHANGE_EVENT_STREAM),
        help="Redis stream carrying paper-exchange command/fill results.",
    )
    parser.add_argument(
        "--heartbeat-stream",
        default=os.getenv("PAPER_EXCHANGE_HEARTBEAT_STREAM", PAPER_EXCHANGE_HEARTBEAT_STREAM),
        help="Redis stream for paper-exchange heartbeat events.",
    )
    parser.add_argument(
        "--allowed-connectors",
        default=os.getenv("PAPER_EXCHANGE_ALLOWED_CONNECTORS", "bitget_perpetual"),
        help="Comma-separated list of real exchange connectors accepted by this service.",
    )
    parser.add_argument(
        "--allowed-command-producers",
        default=os.getenv("PAPER_EXCHANGE_ALLOWED_COMMAND_PRODUCERS", ""),
        help="Optional comma-separated producer allowlist for incoming command events.",
    )
    parser.add_argument(
        "--audit-stream",
        default=os.getenv("PAPER_EXCHANGE_AUDIT_STREAM", AUDIT_STREAM),
        help="Audit stream where privileged command attribution events are published.",
    )
    parser.add_argument(
        "--market-stale-after-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MARKET_STALE_AFTER_MS", "15000")),
    )
    parser.add_argument(
        "--resting-fill-latency-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_RESTING_FILL_LATENCY_MS", "250")),
        help="Minimum resting age before passive fills can occur.",
    )
    parser.add_argument(
        "--maker-queue-participation",
        type=float,
        default=float(os.getenv("PAPER_EXCHANGE_MAKER_QUEUE_PARTICIPATION", "0.35")),
        help="Deterministic fraction of visible touch liquidity considered fillable for resting maker orders.",
    )
    parser.add_argument(
        "--market-sweep-depth-levels",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MARKET_SWEEP_DEPTH_LEVELS", "3")),
        help="Maximum contra depth levels consumed for crossing-limit sweep pricing.",
    )
    parser.add_argument(
        "--max-fill-events-per-market-row",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MAX_FILL_EVENTS_PER_MARKET_ROW", "200")),
        help="Backpressure cap for number of fill events processed from a single market row before replay.",
    )
    parser.add_argument(
        "--heartbeat-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_HEARTBEAT_INTERVAL_MS", "5000")),
    )
    parser.add_argument(
        "--funding-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_FUNDING_INTERVAL_MS", "28800000")),
        help="Funding settlement cadence for open perp exposure.",
    )
    parser.add_argument(
        "--read-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_READ_COUNT", "100")),
    )
    parser.add_argument(
        "--read-block-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_READ_BLOCK_MS", "1000")),
    )
    parser.add_argument(
        "--command-journal-path",
        default=os.getenv(
            "PAPER_EXCHANGE_COMMAND_JOURNAL_PATH",
            "reports/verification/paper_exchange_command_journal_latest.json",
        ),
        help="Persistent idempotency journal path for processed command IDs.",
    )
    parser.add_argument(
        "--state-snapshot-path",
        default=os.getenv(
            "PAPER_EXCHANGE_STATE_SNAPSHOT_PATH",
            "reports/verification/paper_exchange_state_snapshot_latest.json",
        ),
        help="Persistent order-state snapshot path for restart recovery.",
    )
    parser.add_argument(
        "--pair-snapshot-path",
        default=os.getenv(
            "PAPER_EXCHANGE_PAIR_SNAPSHOT_PATH",
            "reports/verification/paper_exchange_pair_snapshot_latest.json",
        ),
        help="Persistent pair snapshot path for per-symbol market freshness metrics.",
    )
    parser.add_argument(
        "--market-fill-journal-path",
        default=os.getenv(
            "PAPER_EXCHANGE_MARKET_FILL_JOURNAL_PATH",
            "reports/verification/paper_exchange_market_fill_journal_latest.json",
        ),
        help="Persistent dedup journal path for published market fill event IDs.",
    )
    parser.add_argument(
        "--market-fill-journal-max-entries",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MARKET_FILL_JOURNAL_MAX_ENTRIES", "200000")),
        help="Maximum number of market fill IDs retained in dedup journal.",
    )
    parser.add_argument(
        "--pending-reclaim-enabled",
        default=os.getenv("PAPER_EXCHANGE_PENDING_RECLAIM_ENABLED", "true"),
        help="Enable reclaim loop for stale pending stream entries.",
    )
    parser.add_argument(
        "--pending-reclaim-idle-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_PENDING_RECLAIM_IDLE_MS", "30000")),
        help="Idle threshold before pending entries are claimed by this consumer.",
    )
    parser.add_argument(
        "--pending-reclaim-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_PENDING_RECLAIM_INTERVAL_MS", "5000")),
        help="Loop interval for attempting pending reclaim.",
    )
    parser.add_argument(
        "--pending-reclaim-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_PENDING_RECLAIM_COUNT", "100")),
        help="Maximum number of pending entries to reclaim per loop.",
    )
    parser.add_argument(
        "--market-pending-reclaim-enabled",
        default=os.getenv("PAPER_EXCHANGE_MARKET_PENDING_RECLAIM_ENABLED", "true"),
        help="Enable reclaim loop for stale pending market snapshot entries.",
    )
    parser.add_argument(
        "--market-pending-reclaim-idle-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MARKET_PENDING_RECLAIM_IDLE_MS", "30000")),
        help="Idle threshold before pending market entries are claimed by this consumer.",
    )
    parser.add_argument(
        "--market-pending-reclaim-interval-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MARKET_PENDING_RECLAIM_INTERVAL_MS", "5000")),
        help="Loop interval for attempting market pending reclaim.",
    )
    parser.add_argument(
        "--market-pending-reclaim-count",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MARKET_PENDING_RECLAIM_COUNT", "100")),
        help="Maximum number of pending market entries to reclaim per loop.",
    )
    parser.add_argument(
        "--terminal-order-ttl-ms",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_TERMINAL_ORDER_TTL_MS", "86400000")),
        help="TTL for terminal orders before pruning from in-memory/snapshot state.",
    )
    parser.add_argument(
        "--max-orders-tracked",
        type=int,
        default=int(os.getenv("PAPER_EXCHANGE_MAX_ORDERS_TRACKED", "200000")),
        help="Hard cap for tracked orders; oldest terminal orders are pruned first.",
    )
    parser.add_argument(
        "--persist-sync-state-results",
        default=os.getenv("PAPER_EXCHANGE_PERSIST_SYNC_STATE_RESULTS", "true"),
        help="Persist sync_state command results to idempotency journal (set false for synthetic load runs).",
    )
    args = parser.parse_args()
    redis_enabled = str(args.redis_enabled).strip().lower() in {"1", "true", "yes", "on"}
    pending_reclaim_enabled = str(args.pending_reclaim_enabled).strip().lower() in {"1", "true", "yes", "on"}
    market_pending_reclaim_enabled = str(args.market_pending_reclaim_enabled).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    persist_sync_state_results = str(args.persist_sync_state_results).strip().lower() in {"1", "true", "yes", "on"}
    return ServiceSettings(
        redis_host=str(args.redis_host),
        redis_port=int(args.redis_port),
        redis_db=int(args.redis_db),
        redis_password=str(args.redis_password or ""),
        redis_enabled=redis_enabled,
        service_instance_name=str(args.service_instance_name),
        consumer_group=str(args.consumer_group),
        consumer_name=str(args.consumer_name),
        market_data_stream=str(args.market_stream),
        command_stream=str(args.command_stream),
        event_stream=str(args.event_stream),
        heartbeat_stream=str(args.heartbeat_stream),
        allowed_connectors=_csv_set(str(args.allowed_connectors)),
        allowed_command_producers=_csv_set(str(args.allowed_command_producers)),
        audit_stream=str(args.audit_stream),
        market_stale_after_ms=max(1_000, int(args.market_stale_after_ms)),
        resting_fill_latency_ms=max(0, int(args.resting_fill_latency_ms)),
        maker_queue_participation=min(1.0, max(0.0, float(args.maker_queue_participation))),
        market_sweep_depth_levels=max(1, int(args.market_sweep_depth_levels)),
        funding_interval_ms=max(1_000, int(args.funding_interval_ms)),
        max_fill_events_per_market_row=max(1, int(args.max_fill_events_per_market_row)),
        heartbeat_interval_ms=max(1_000, int(args.heartbeat_interval_ms)),
        read_count=max(1, int(args.read_count)),
        read_block_ms=max(1, int(args.read_block_ms)),
        command_journal_path=str(args.command_journal_path),
        state_snapshot_path=str(args.state_snapshot_path),
        pair_snapshot_path=str(args.pair_snapshot_path),
        market_fill_journal_path=str(args.market_fill_journal_path),
        market_fill_journal_max_entries=max(1, int(args.market_fill_journal_max_entries)),
        pending_reclaim_enabled=pending_reclaim_enabled,
        pending_reclaim_idle_ms=max(1_000, int(args.pending_reclaim_idle_ms)),
        pending_reclaim_interval_ms=max(1_000, int(args.pending_reclaim_interval_ms)),
        pending_reclaim_count=max(1, int(args.pending_reclaim_count)),
        market_pending_reclaim_enabled=market_pending_reclaim_enabled,
        market_pending_reclaim_idle_ms=max(1_000, int(args.market_pending_reclaim_idle_ms)),
        market_pending_reclaim_interval_ms=max(1_000, int(args.market_pending_reclaim_interval_ms)),
        market_pending_reclaim_count=max(1, int(args.market_pending_reclaim_count)),
        terminal_order_ttl_ms=max(0, int(args.terminal_order_ttl_ms)),
        max_orders_tracked=max(1, int(args.max_orders_tracked)),
        persist_sync_state_results=persist_sync_state_results,
    )


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = _parse_args()
    try:
        run(settings)
    except KeyboardInterrupt:
        logger.info("paper_exchange_service interrupted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
