from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from platform_lib.contracts.event_schemas import PaperExchangeEvent
from platform_lib.core.latency_tracker import JsonLatencyTracker
from services.paper_exchange_service.models import (
    OrderRecord,
    PairSnapshot,
    PaperExchangeState,
    PositionRecord,
    ServiceSettings,
    _namespace_base_key,
    _namespace_order_key,
    _normalize,
    _normalize_connector_name,
    _now_ms,
)

logger = logging.getLogger(__name__)


def _resolve_path(path_value: str, root: Path) -> Path:
    path = Path(str(path_value or "").strip() or "reports/verification/paper_exchange_command_journal_latest.json")
    if not path.is_absolute():
        path = root / path
    return path


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _load_command_journal(path: Path) -> dict[str, dict[str, object]]:
    payload = _read_json(path)
    commands = payload.get("commands", {})
    if not isinstance(commands, dict):
        return {}
    out: dict[str, dict[str, object]] = {}
    for command_event_id, record in commands.items():
        if isinstance(record, dict):
            out[str(command_event_id)] = dict(record)
    return out


def _write_json_atomic(path: Path, payload: dict[str, object], *, retries: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2)
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


def _persist_command_journal(path: Path, command_results_by_id: dict[str, dict[str, object]]) -> None:
    payload = {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "command_count": len(command_results_by_id),
        "commands": command_results_by_id,
    }
    _write_json_atomic(path, payload)


def _load_market_fill_journal(path: Path) -> dict[str, int]:
    payload = _read_json(path)
    raw_events = payload.get("events", {})
    if not isinstance(raw_events, dict):
        return {}
    out: dict[str, int] = {}
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


def _trim_market_fill_journal(events_by_id: dict[str, int], max_entries: int) -> None:
    limit = max(1, int(max_entries))
    overflow = len(events_by_id) - limit
    if overflow <= 0:
        return
    sorted_items = sorted(events_by_id.items(), key=lambda item: (int(item[1]), str(item[0])))
    for event_id, _marker in sorted_items[:overflow]:
        events_by_id.pop(str(event_id), None)


def _persist_market_fill_journal(path: Path, market_fill_events_by_id: dict[str, int], max_entries: int) -> None:
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
    command_metadata: dict[str, str] | None = None,
    command_producer: str = "",
    producer_authorized: bool = True,
) -> dict[str, object]:
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


def _order_record_to_dict(order: OrderRecord) -> dict[str, object]:
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


def _position_record_to_dict(position: PositionRecord) -> dict[str, object]:
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


def _position_record_from_payload(payload: dict[str, object]) -> PositionRecord | None:
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


def _order_record_from_payload(order_id: str, payload: dict[str, object]) -> OrderRecord | None:
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


def _load_state_snapshot(path: Path) -> dict[str, OrderRecord]:
    payload = _read_json(path)
    raw_orders = payload.get("orders", {})
    if not isinstance(raw_orders, dict):
        return {}
    out: dict[str, OrderRecord] = {}
    for order_id, record in raw_orders.items():
        if not isinstance(record, dict):
            continue
        parsed = _order_record_from_payload(str(order_id), record)
        if parsed is not None and parsed.order_id:
            out[str(parsed.order_id)] = parsed
    return out


def _load_position_snapshot(path: Path) -> dict[str, PositionRecord]:
    payload = _read_json(path)
    raw_positions = payload.get("positions", {})
    if not isinstance(raw_positions, dict):
        return {}
    out: dict[str, PositionRecord] = {}
    for position_key, record in raw_positions.items():
        if not isinstance(record, dict):
            continue
        parsed = _position_record_from_payload(record)
        if parsed is not None and str(position_key or "").strip():
            out[str(position_key)] = parsed
    return out


def _persist_state_snapshot(
    path: Path,
    orders_by_id: dict[str, OrderRecord],
    positions_by_key: dict[str, PositionRecord] | None = None,
    *,
    funding_summary: dict[str, object] | None = None,
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


def _pair_snapshot_to_dict(snapshot: PairSnapshot) -> dict[str, object]:
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


def _persist_pair_snapshot(path: Path, pairs: dict[str, PairSnapshot]) -> None:
    payload = {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pairs_total": len(pairs),
        "pairs": {key: _pair_snapshot_to_dict(snapshot) for key, snapshot in pairs.items()},
    }
    _write_json_atomic(path, payload)


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


def _coerce_margin_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in {"leveraged", "standard"} else "leveraged"


def _is_flat_position(position: PositionRecord) -> bool:
    _MIN_FILL_EPSILON = 1e-12
    return float(position.long_base) <= _MIN_FILL_EPSILON and float(position.short_base) <= _MIN_FILL_EPSILON


def _funding_summary(state: PaperExchangeState) -> dict[str, object]:
    return {
        "positions_with_exposure": sum(1 for position in state.positions_by_key.values() if not _is_flat_position(position)),
        "funding_events_generated": int(state.funding_events_generated),
        "funding_debit_events": int(state.funding_debit_events),
        "funding_credit_events": int(state.funding_credit_events),
        "funding_paid_quote_total": float(state.funding_paid_quote_total),
    }


@dataclass
class PersistenceCoordinator:
    state: PaperExchangeState
    settings: ServiceSettings
    command_journal_path: Path | None = None
    state_snapshot_path: Path | None = None
    pair_snapshot_path: Path | None = None
    market_fill_journal_path: Path | None = None
    latency_tracker: JsonLatencyTracker | None = None
    command_journal_dirty: bool = False
    state_snapshot_dirty: bool = False
    pair_snapshot_dirty: bool = False
    market_fill_journal_dirty: bool = False
    _last_general_flush_ms: int = 0
    _last_pair_flush_ms: int = 0

    def mark_command_journal_dirty(self) -> None:
        self.command_journal_dirty = self.command_journal_path is not None

    def mark_state_snapshot_dirty(self) -> None:
        self.state_snapshot_dirty = self.state_snapshot_path is not None

    def mark_pair_snapshot_dirty(self) -> None:
        self.pair_snapshot_dirty = self.pair_snapshot_path is not None

    def mark_market_fill_journal_dirty(self) -> None:
        self.market_fill_journal_dirty = self.market_fill_journal_path is not None

    def flush_due(self, now_ms: int | None = None, *, force: bool = False) -> None:
        current_ms = int(now_ms if now_ms is not None else _now_ms())
        general_interval_ms = max(1, int(self.settings.persistence_flush_interval_ms))
        pair_interval_ms = max(general_interval_ms, int(self.settings.pair_snapshot_flush_interval_ms))
        flush_general = force or (current_ms - self._last_general_flush_ms) >= general_interval_ms
        flush_pair = force or (current_ms - self._last_pair_flush_ms) >= pair_interval_ms

        if flush_general and self.command_journal_dirty and self.command_journal_path is not None:
            started = time.perf_counter()
            _persist_command_journal(self.command_journal_path, self.state.command_results_by_id)
            self.command_journal_dirty = False
            self._last_general_flush_ms = current_ms
            if self.latency_tracker is not None:
                self.latency_tracker.observe(
                    "paper_exchange_persist_command_journal_ms",
                    (time.perf_counter() - started) * 1000.0,
                )
        if flush_general and self.market_fill_journal_dirty and self.market_fill_journal_path is not None:
            started = time.perf_counter()
            _persist_market_fill_journal(
                self.market_fill_journal_path,
                self.state.market_fill_events_by_id,
                max_entries=self.settings.market_fill_journal_max_entries,
            )
            self.market_fill_journal_dirty = False
            self._last_general_flush_ms = current_ms
            if self.latency_tracker is not None:
                self.latency_tracker.observe(
                    "paper_exchange_persist_market_fill_journal_ms",
                    (time.perf_counter() - started) * 1000.0,
                )
        if flush_general and self.state_snapshot_dirty and self.state_snapshot_path is not None:
            started = time.perf_counter()
            _persist_state_snapshot(
                self.state_snapshot_path,
                self.state.orders_by_id,
                self.state.positions_by_key,
                funding_summary=_funding_summary(self.state),
            )
            self.state_snapshot_dirty = False
            self._last_general_flush_ms = current_ms
            if self.latency_tracker is not None:
                self.latency_tracker.observe(
                    "paper_exchange_persist_state_snapshot_ms",
                    (time.perf_counter() - started) * 1000.0,
                )
        if flush_pair and self.pair_snapshot_dirty and self.pair_snapshot_path is not None:
            started = time.perf_counter()
            _persist_pair_snapshot(self.pair_snapshot_path, self.state.pairs)
            self.pair_snapshot_dirty = False
            self._last_pair_flush_ms = current_ms
            if self.latency_tracker is not None:
                self.latency_tracker.observe(
                    "paper_exchange_persist_pair_snapshot_ms",
                    (time.perf_counter() - started) * 1000.0,
                )
