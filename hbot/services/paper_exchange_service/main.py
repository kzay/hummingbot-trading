from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from services.contracts.event_schemas import (
    AuditEvent,
    MarketSnapshotEvent,
    PaperExchangeCommandEvent,
    PaperExchangeEvent,
    PaperExchangeHeartbeatEvent,
)
from services.contracts.stream_names import (
    AUDIT_STREAM,
    MARKET_DATA_STREAM,
    PAPER_EXCHANGE_COMMAND_STREAM,
    PAPER_EXCHANGE_EVENT_STREAM,
    PAPER_EXCHANGE_HEARTBEAT_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def _csv_set(value: str) -> Set[str]:
    return {_normalize(x) for x in str(value or "").split(",") if _normalize(x)}


def _pair_key(connector_name: str, trading_pair: str) -> str:
    return f"{_normalize(connector_name)}::{str(trading_pair or '').strip().upper()}"


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
) -> Dict[str, object]:
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
    }


def _order_record_to_dict(order: OrderRecord) -> Dict[str, object]:
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
        "last_fill_amount_base": order.last_fill_amount_base,
        "filled_base": order.filled_base,
        "filled_quote": order.filled_quote,
        "fill_count": order.fill_count,
    }


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
            last_fill_amount_base=float(payload.get("last_fill_amount_base", 0.0)),
            filled_base=float(payload.get("filled_base", 0.0)),
            filled_quote=float(payload.get("filled_quote", 0.0)),
            fill_count=int(payload.get("fill_count", 0)),
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


def _persist_state_snapshot(path: Path, orders_by_id: Dict[str, OrderRecord]) -> None:
    payload = {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "orders_total": len(orders_by_id),
        "orders": {order_id: _order_record_to_dict(order) for order_id, order in orders_by_id.items()},
    }
    _write_json_atomic(path, payload)


@dataclass
class PairSnapshot:
    connector_name: str
    trading_pair: str
    instance_name: str
    timestamp_ms: int
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
    last_fill_amount_base: float = 0.0
    filled_base: float = 0.0
    filled_quote: float = 0.0
    fill_count: int = 0


@dataclass
class PaperExchangeState:
    pairs: Dict[str, PairSnapshot] = field(default_factory=dict)
    orders_by_id: Dict[str, OrderRecord] = field(default_factory=dict)
    accepted_snapshots: int = 0
    rejected_snapshots: int = 0
    processed_commands: int = 0
    rejected_commands: int = 0
    rejected_commands_stale_market: int = 0
    rejected_commands_missing_market: int = 0
    rejected_commands_disallowed_connector: int = 0
    rejected_commands_unauthorized_producer: int = 0
    rejected_commands_missing_privileged_metadata: int = 0
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
    market_fill_journal_write_failures: int = 0
    market_fill_journal_next_seq: int = 0
    market_fill_events_by_id: Dict[str, int] = field(default_factory=dict)
    market_row_fill_cap_hits: int = 0
    command_results_by_id: Dict[str, Dict[str, object]] = field(default_factory=dict)


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
    market_data_stream: str = MARKET_DATA_STREAM
    command_stream: str = PAPER_EXCHANGE_COMMAND_STREAM
    event_stream: str = PAPER_EXCHANGE_EVENT_STREAM
    heartbeat_stream: str = PAPER_EXCHANGE_HEARTBEAT_STREAM
    audit_stream: str = AUDIT_STREAM
    allowed_connectors: Set[str] = field(default_factory=set)
    allowed_command_producers: Set[str] = field(default_factory=set)
    market_stale_after_ms: int = 15_000
    max_fill_events_per_market_row: int = 200
    heartbeat_interval_ms: int = 5_000
    read_count: int = 100
    read_block_ms: int = 1_000
    command_journal_path: str = "reports/verification/paper_exchange_command_journal_latest.json"
    state_snapshot_path: str = "reports/verification/paper_exchange_state_snapshot_latest.json"
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


_ACTIVE_ORDER_STATES = {"accepted", "working", "partially_filled"}
_TERMINAL_ORDER_STATES = {"filled", "cancelled", "rejected", "expired"}
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


def _order_matches_snapshot(order: OrderRecord, snapshot: PairSnapshot) -> bool:
    return (
        _normalize(order.connector_name) == _normalize(snapshot.connector_name)
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
) -> List[FillCandidate]:
    best_bid = _snapshot_best_bid(snapshot)
    best_ask = _snapshot_best_ask(snapshot)
    if best_bid is None and best_ask is None:
        return []

    bid_liquidity = _snapshot_best_bid_size(snapshot)
    ask_liquidity = _snapshot_best_ask_size(snapshot)
    candidates: List[FillCandidate] = []

    # Replay guard for partially processed snapshot rows:
    # reserve liquidity already consumed by fills tied to this snapshot event_id.
    for historical_order in state.orders_by_id.values():
        if str(historical_order.last_fill_snapshot_event_id or "") != str(snapshot.event_id):
            continue
        consumed = max(0.0, float(historical_order.last_fill_amount_base))
        if consumed <= _MIN_FILL_EPSILON:
            continue
        if historical_order.side == "buy" and ask_liquidity is not None:
            ask_liquidity = max(0.0, ask_liquidity - consumed)
        elif historical_order.side == "sell" and bid_liquidity is not None:
            bid_liquidity = max(0.0, bid_liquidity - consumed)

    for order in _ordered_active_orders_for_snapshot(state, snapshot):
        if str(order.last_fill_snapshot_event_id or "") == str(snapshot.event_id):
            # Replay guard: one fill step per order per snapshot event_id.
            continue
        remaining = _remaining_amount_base(order)
        if remaining <= _MIN_FILL_EPSILON:
            continue
        if not _crosses_book(order.side, float(order.price), best_bid, best_ask):
            continue

        if order.side == "buy":
            available = ask_liquidity
            fill_price = float(best_ask if best_ask is not None else order.price)
        else:
            available = bid_liquidity
            fill_price = float(best_bid if best_bid is not None else order.price)
        if fill_price <= 0:
            continue

        fill_amount = remaining if available is None else min(remaining, float(available))
        if fill_amount <= _MIN_FILL_EPSILON:
            continue

        remaining_after = max(0.0, remaining - fill_amount)
        if order.side == "buy" and ask_liquidity is not None:
            ask_liquidity = max(0.0, ask_liquidity - fill_amount)
        if order.side == "sell" and bid_liquidity is not None:
            bid_liquidity = max(0.0, bid_liquidity - fill_amount)

        fill_count = int(order.fill_count) + 1
        candidates.append(
            FillCandidate(
                event_id=f"pe-fill-{snapshot.event_id}-{order.order_id}-{fill_count}",
                command_event_id=f"market_snapshot:{snapshot.event_id}",
                order_id=str(order.order_id),
                new_state="filled" if remaining_after <= _MIN_FILL_EPSILON else "partially_filled",
                fill_price=fill_price,
                fill_amount_base=fill_amount,
                fill_notional_quote=fill_amount * fill_price,
                remaining_amount_base=remaining_after,
                is_maker=True,
                snapshot_event_id=str(snapshot.event_id),
                snapshot_market_sequence=int(snapshot.market_sequence or 0),
                fill_count=fill_count,
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
            "fill_fee_quote": "0",
            "is_maker": "1" if candidate.is_maker else "0",
            "remaining_amount_base": str(candidate.remaining_amount_base),
            "filled_amount_base_total": str(max(0.0, (order.filled_base + candidate.fill_amount_base))),
            "filled_notional_quote_total": str(max(0.0, (order.filled_quote + candidate.fill_notional_quote))),
            "fill_count": str(candidate.fill_count),
            "snapshot_event_id": str(candidate.snapshot_event_id),
            "snapshot_market_sequence": str(candidate.snapshot_market_sequence),
            "best_bid": str(snapshot.best_bid) if snapshot.best_bid is not None else "",
            "best_ask": str(snapshot.best_ask) if snapshot.best_ask is not None else "",
        },
    )


def _apply_fill_candidate(order: OrderRecord, candidate: FillCandidate, *, now_ms: int) -> None:
    order.filled_base = max(0.0, float(order.filled_base) + float(candidate.fill_amount_base))
    order.filled_quote = max(0.0, float(order.filled_quote) + float(candidate.fill_notional_quote))
    order.fill_count = int(candidate.fill_count)
    order.state = str(candidate.new_state)
    order.last_fill_snapshot_event_id = str(candidate.snapshot_event_id)
    order.last_fill_amount_base = max(0.0, float(candidate.fill_amount_base))
    order.updated_ts_ms = int(now_ms)


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
) -> Tuple[bool, str]:
    """Ingest a market snapshot from real exchange feed used by bots."""
    try:
        event = MarketSnapshotEvent(**payload)
    except Exception:
        state.rejected_snapshots += 1
        return False, "invalid_schema"

    if event.mid_price <= 0:
        state.rejected_snapshots += 1
        return False, "non_positive_mid_price"
    if event.best_bid is not None and float(event.best_bid) <= 0:
        state.rejected_snapshots += 1
        return False, "non_positive_best_bid"
    if event.best_ask is not None and float(event.best_ask) <= 0:
        state.rejected_snapshots += 1
        return False, "non_positive_best_ask"
    if event.best_bid_size is not None and float(event.best_bid_size) <= 0:
        state.rejected_snapshots += 1
        return False, "non_positive_best_bid_size"
    if event.best_ask_size is not None and float(event.best_ask_size) <= 0:
        state.rejected_snapshots += 1
        return False, "non_positive_best_ask_size"
    if event.best_bid is not None and event.best_ask is not None and float(event.best_bid) >= float(event.best_ask):
        state.rejected_snapshots += 1
        return False, "invalid_top_of_book"

    normalized_connector = _normalize(event.connector_name)
    if allowed_connectors and normalized_connector not in allowed_connectors:
        state.rejected_snapshots += 1
        return False, "connector_not_allowed"

    key = _pair_key(event.connector_name, event.trading_pair)
    previous = state.pairs.get(key)
    incoming_exchange_ts = int(event.exchange_ts_ms) if event.exchange_ts_ms is not None else int(event.timestamp_ms)
    incoming_sequence = int(event.market_sequence) if event.market_sequence is not None else 0
    incoming_order_key = (incoming_exchange_ts, incoming_sequence, int(event.timestamp_ms))
    previous_order_key = None
    if previous is not None:
        previous_exchange_ts = (
            int(previous.exchange_ts_ms)
            if previous.exchange_ts_ms is not None
            else int(previous.timestamp_ms)
        )
        previous_sequence = int(previous.market_sequence) if previous.market_sequence is not None else 0
        previous_order_key = (previous_exchange_ts, previous_sequence, int(previous.timestamp_ms))
    if previous_order_key is not None and incoming_order_key < previous_order_key:
        state.rejected_snapshots += 1
        return False, "out_of_order_snapshot"

    state.pairs[key] = PairSnapshot(
        connector_name=event.connector_name,
        trading_pair=event.trading_pair,
        instance_name=event.instance_name,
        timestamp_ms=int(event.timestamp_ms),
        mid_price=float(event.mid_price),
        best_bid=float(event.best_bid) if event.best_bid is not None else None,
        best_ask=float(event.best_ask) if event.best_ask is not None else None,
        best_bid_size=float(event.best_bid_size) if event.best_bid_size is not None else None,
        best_ask_size=float(event.best_ask_size) if event.best_ask_size is not None else None,
        last_trade_price=float(event.last_trade_price) if event.last_trade_price is not None else None,
        mark_price=float(event.mark_price) if event.mark_price is not None else None,
        funding_rate=float(event.funding_rate) if event.funding_rate is not None else None,
        exchange_ts_ms=int(event.exchange_ts_ms) if event.exchange_ts_ms is not None else None,
        ingest_ts_ms=int(event.ingest_ts_ms) if event.ingest_ts_ms is not None else None,
        market_sequence=int(event.market_sequence) if event.market_sequence is not None else None,
        event_id=str(event.event_id),
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
    ages = [max(0, now - int(s.timestamp_ms)) for s in state.pairs.values()]
    stale_pairs = sum(1 for age in ages if age > stale_after_ms)
    l1_ready_pairs = sum(
        1 for snapshot in state.pairs.values() if snapshot.best_bid is not None and snapshot.best_ask is not None
    )
    active_orders = sum(1 for order in state.orders_by_id.values() if order.state in _ACTIVE_ORDER_STATES)
    terminal_orders = sum(1 for order in state.orders_by_id.values() if order.state in _TERMINAL_ORDER_STATES)
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
            "market_fill_journal_write_failures": str(state.market_fill_journal_write_failures),
            "market_fill_journal_size": str(len(state.market_fill_events_by_id)),
            "market_row_fill_cap_hits": str(state.market_row_fill_cap_hits),
        },
    )


def handle_command_payload(
    payload: Dict[str, object],
    state: PaperExchangeState,
    service_instance_name: str,
    allowed_connectors: Optional[Set[str]] = None,
    allowed_command_producers: Optional[Set[str]] = None,
    market_stale_after_ms: int = 15_000,
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

    normalized_connector = _normalize(command.connector_name)
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
        pair_snapshot = state.pairs.get(_pair_key(command.connector_name, command.trading_pair))
        if pair_snapshot is None:
            state.rejected_commands += 1
            state.rejected_commands_missing_market += 1
            return _event_for_command(command=command, status="rejected", reason="no_market_snapshot")
        snapshot_age_ms = max(0, now - int(pair_snapshot.timestamp_ms))
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
        post_only = bool(order_type == "post_only" or _parse_bool(metadata.get("post_only"), default=False))
        best_bid = _snapshot_best_bid(pair_snapshot)
        best_ask = _snapshot_best_ask(pair_snapshot)
        best_bid_size = _snapshot_best_bid_size(pair_snapshot)
        best_ask_size = _snapshot_best_ask_size(pair_snapshot)
        initial_state = "working"
        reason = "order_accepted"
        fill_price: Optional[float] = None
        fill_notional_quote: Optional[float] = None
        is_maker = True
        initial_filled_base = 0.0
        initial_filled_quote = 0.0
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
                cross_fill_amount = amount_base
                if side == "buy":
                    fill_price = float(best_ask if best_ask is not None else order_price)
                    if best_ask_size is not None:
                        cross_fill_amount = min(cross_fill_amount, float(best_ask_size))
                else:
                    fill_price = float(best_bid if best_bid is not None else order_price)
                    if best_bid_size is not None:
                        cross_fill_amount = min(cross_fill_amount, float(best_bid_size))
                cross_fill_amount = max(0.0, float(cross_fill_amount))
                if cross_fill_amount <= _MIN_FILL_EPSILON:
                    state.rejected_commands += 1
                    return _event_for_command(
                        command=command,
                        status="rejected",
                        reason="insufficient_top_of_book_liquidity",
                    )
                if cross_fill_amount + _MIN_FILL_EPSILON < amount_base:
                    initial_state = "partially_filled"
                    reason = "order_partially_filled_crossing"
                else:
                    initial_state = "filled"
                    reason = "order_filled_crossing"
                fill_notional_quote = cross_fill_amount * fill_price
                is_maker = False
                initial_filled_base = cross_fill_amount
                initial_filled_quote = float(fill_notional_quote)
                initial_fill_count = 1
            elif time_in_force in {"ioc", "fok"}:
                # Deterministic baseline: no book cross means IOC/FOK cannot execute.
                initial_state = "expired"
                reason = "time_in_force_expired_no_fill"

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
            fill_count=initial_fill_count,
        )
        state.orders_by_id[order_id] = order_record
        state.processed_commands += 1
        event_metadata = _order_metadata(order_record)
        event_metadata.update(
            {
                "command_sequence": str(command_seq),
                "best_bid": str(best_bid) if best_bid is not None else "",
                "best_ask": str(best_ask) if best_ask is not None else "",
                "best_bid_size": str(best_bid_size) if best_bid_size is not None else "",
                "best_ask_size": str(best_ask_size) if best_ask_size is not None else "",
            }
        )
        if order_record.state in {"filled", "partially_filled"}:
            event_metadata.update(
                {
                    "fill_price": str(fill_price if fill_price is not None else order_record.price),
                    "fill_amount_base": str(order_record.filled_base),
                    "fill_notional_quote": str(
                        fill_notional_quote
                        if fill_notional_quote is not None
                        else order_record.filled_base * order_record.price
                    ),
                    "fill_fee_quote": "0",
                    "is_maker": "1" if is_maker else "0",
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

        if order.state in _TERMINAL_ORDER_STATES:
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
            if order.state in _ACTIVE_ORDER_STATES:
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
        try:
            parsed_command = PaperExchangeCommandEvent(**payload)
            command_event_id = str(parsed_command.event_id or "").strip()
            command_metadata = dict(parsed_command.metadata or {})
            command_name = _normalize(parsed_command.command)
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
            command_sequence=command_sequence,
        )
        if command_mutates_orders:
            _prune_orders(
                state=state,
                now_ms=_now_ms(),
                terminal_order_ttl_ms=settings.terminal_order_ttl_ms,
                max_orders_tracked=settings.max_orders_tracked,
            )
        publish_result = client.xadd(
            stream=settings.event_stream,
            payload=result_event.model_dump(),
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
            )
            try:
                _persist_command_journal(command_journal_path, state.command_results_by_id)
            except Exception as exc:
                logger.warning("paper_exchange command journal persist failed: %s", exc)
        if state_snapshot_path is not None and command_mutates_orders:
            try:
                _persist_state_snapshot(state_snapshot_path, state.orders_by_id)
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
    market_fill_journal_path: Optional[Path] = None,
) -> None:
    for entry_id, payload in rows:
        ok, _reason = ingest_market_snapshot_payload(
            payload=payload,
            state=state,
            allowed_connectors=settings.allowed_connectors,
        )
        if not ok:
            if source == "reclaimed":
                state.reclaimed_pending_market_entries += 1
            client.ack(settings.market_data_stream, settings.consumer_group, entry_id)
            continue

        snapshot_key = _pair_key(str(payload.get("connector_name", "")), str(payload.get("trading_pair", "")))
        snapshot = state.pairs.get(snapshot_key)
        if snapshot is None:
            if source == "reclaimed":
                state.reclaimed_pending_market_entries += 1
            client.ack(settings.market_data_stream, settings.consumer_group, entry_id)
            continue

        state.market_match_cycles += 1
        applied_count = 0
        publish_failed = False
        persist_failed = False
        cap_hit = False
        for candidate in _build_fill_candidates_for_snapshot(state=state, snapshot=snapshot):
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
            fill_event = _market_fill_event_from_candidate(order=order, snapshot=snapshot, candidate=candidate)
            event_id = str(fill_event.event_id or "")
            event_already_published = bool(event_id and event_id in state.market_fill_events_by_id)
            if event_already_published:
                state.deduplicated_market_fill_events += 1
            else:
                publish_result = client.xadd(
                    stream=settings.event_stream,
                    payload=fill_event.model_dump(),
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

            _apply_fill_candidate(order, candidate, now_ms=_now_ms())
            if not event_already_published:
                state.generated_fill_events += 1
                if candidate.new_state == "partially_filled":
                    state.generated_partial_fill_events += 1
            applied_count += 1
            if state_snapshot_path is not None:
                try:
                    _persist_state_snapshot(state_snapshot_path, state.orders_by_id)
                except Exception as exc:
                    logger.warning("paper_exchange state snapshot persist failed after market fill: %s", exc)
                    persist_failed = True
                    break

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
        default=os.getenv("PAPER_EXCHANGE_MARKET_STREAM", MARKET_DATA_STREAM),
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
        max_fill_events_per_market_row=max(1, int(args.max_fill_events_per_market_row)),
        heartbeat_interval_ms=max(1_000, int(args.heartbeat_interval_ms)),
        read_count=max(1, int(args.read_count)),
        read_block_ms=max(1, int(args.read_block_ms)),
        command_journal_path=str(args.command_journal_path),
        state_snapshot_path=str(args.state_snapshot_path),
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
