from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import logging
import os
import queue
import struct
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

try:
    import psycopg
except Exception:  # pragma: no cover - optional at runtime in lightweight environments.
    psycopg = None  # type: ignore[assignment]

try:
    import ccxt  # type: ignore
except Exception:  # pragma: no cover - optional in lightweight environments.
    ccxt = None  # type: ignore[assignment]

from services.common.logging_config import configure_logging
from services.contracts.stream_names import (
    BOT_TELEMETRY_STREAM,
    DEFAULT_CONSUMER_GROUP,
    MARKET_DATA_STREAM,
    MARKET_DEPTH_STREAM,
    MARKET_QUOTE_STREAM,
    PAPER_EXCHANGE_EVENT_STREAM,
)
from services.hb_bridge.redis_client import RedisStreamClient

configure_logging()
logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _to_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _normalize_pair(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "").replace("-", "").replace("_", "")


def _to_epoch_ms(value: Any) -> Optional[int]:
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    numeric = _to_float(value)
    if numeric is not None:
        parsed = int(numeric)
        return parsed if parsed > 10_000_000_000 else parsed * 1000
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.isdigit():
            parsed = int(raw)
            return parsed if parsed > 10_000_000_000 else parsed * 1000
    except Exception:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp() * 1000)
    except Exception:
        return None


def _ccxt_exchange_id(connector_name: str) -> str:
    normalized = str(connector_name or "").strip().lower()
    if normalized.startswith("bitget"):
        return "bitget"
    if normalized.startswith("binance_perpetual") or normalized.startswith("binanceusdm"):
        return "binanceusdm"
    return ""


def _ccxt_symbol(trading_pair: str) -> str:
    raw = str(trading_pair or "").strip().upper().replace("_", "-")
    return raw.replace("-", "/")


def _ccxt_timeframe(timeframe_s: int) -> str:
    mapping = {
        60: "1m",
        180: "3m",
        300: "5m",
        900: "15m",
        1800: "30m",
        3600: "1h",
        14400: "4h",
        86400: "1d",
    }
    return mapping.get(max(1, int(timeframe_s)), "1m")


def _candles_from_points(points: List[Tuple[int, float]], timeframe_s: int, limit: int) -> List[Dict[str, Any]]:
    timeframe_ms = max(1, int(timeframe_s)) * 1000
    buckets: Dict[int, Dict[str, Any]] = {}
    last_close: Optional[float] = None
    last_bucket: Optional[int] = None
    for ts_ms, price in points:
        bucket = (int(ts_ms) // timeframe_ms) * timeframe_ms
        row = buckets.get(bucket)
        if row is None:
            open_price = float(price)
            # When only one point exists per minute, bridge open to previous close to avoid flat 1m bars.
            if timeframe_ms <= 60_000 and last_close is not None and last_bucket != bucket:
                open_price = float(last_close)
            buckets[bucket] = {
                "bucket_ms": bucket,
                "open": open_price,
                "high": max(open_price, float(price)),
                "low": min(open_price, float(price)),
                "close": float(price),
            }
            last_close = float(price)
            last_bucket = bucket
            continue
        row["high"] = max(float(row["high"]), float(price))
        row["low"] = min(float(row["low"]), float(price))
        row["close"] = float(price)
        last_close = float(price)
        last_bucket = bucket
    candles = [buckets[k] for k in sorted(buckets.keys())]
    return candles[-max(1, int(limit)) :]


def _stream_ms(entry_id: str) -> int:
    raw = str(entry_id or "").strip().split("-", 1)[0]
    try:
        return int(raw)
    except Exception:
        return _now_ms()


def _window_summary_template() -> Dict[str, Any]:
    return {
        "fill_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "maker_count": 0,
        "maker_ratio": 0.0,
        "volume_base": 0.0,
        "notional_quote": 0.0,
        "realized_pnl_quote": 0.0,
        "avg_fill_size": 0.0,
        "avg_fill_price": 0.0,
    }


def _account_summary_template() -> Dict[str, Any]:
    return {
        "equity_quote": 0.0,
        "quote_balance": 0.0,
        "equity_open_quote": 0.0,
        "equity_peak_quote": 0.0,
        "realized_pnl_quote": 0.0,
        "controller_state": "",
        "regime": "",
        "pnl_governor_active": False,
        "pnl_governor_reason": "",
        "risk_reasons": "",
        "daily_loss_pct": 0.0,
        "max_daily_loss_pct_hard": 0.0,
        "drawdown_pct": 0.0,
        "max_drawdown_pct_hard": 0.0,
        "order_book_stale": False,
        "soft_pause_edge": False,
        "net_edge_pct": 0.0,
        "net_edge_gate_pct": 0.0,
        "adaptive_effective_min_edge_pct": 0.0,
        "spread_pct": 0.0,
        "spread_floor_pct": 0.0,
        "spread_competitiveness_cap_active": False,
        "orders_active": 0,
        "quoting_status": "",
        "quoting_reason": "",
        "quote_gates": [],
        "snapshot_ts": "",
    }


def _day_bounds_utc(day_key: str) -> Tuple[str, int, int]:
    normalized = str(day_key or "").strip()
    if normalized:
        start_dt = datetime.fromisoformat(f"{normalized}T00:00:00+00:00")
    else:
        now = datetime.now(timezone.utc)
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        normalized = start_dt.date().isoformat()
    end_dt = start_dt + timedelta(days=1)
    return normalized, int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)


def _daily_review_template(day_key: str) -> Dict[str, Any]:
    return {
        "day": day_key,
        "summary": {
            "equity_open_quote": 0.0,
            "equity_close_quote": 0.0,
            "equity_high_quote": 0.0,
            "equity_low_quote": 0.0,
            "quote_balance_end_quote": 0.0,
            "realized_pnl_day_quote": 0.0,
            "unrealized_pnl_end_quote": 0.0,
            "fill_count": 0,
            "buy_count": 0,
            "sell_count": 0,
            "maker_ratio": 0.0,
            "notional_quote": 0.0,
            "fees_quote": 0.0,
            "controller_state_end": "",
            "regime_end": "",
            "risk_reasons_end": "",
            "pnl_governor_active_end": False,
            "order_book_stale_end": False,
            "minute_points": 0,
        },
        "equity_curve": [],
        "hourly": [],
        "fills": [],
        "gate_timeline": [],
        "narrative": "",
    }


def _weekly_review_template() -> Dict[str, Any]:
    return {
        "summary": {
            "period_start": "",
            "period_end": "",
            "n_days": 0,
            "days_with_data": 0,
            "total_net_pnl_quote": 0.0,
            "mean_daily_pnl_quote": 0.0,
            "mean_daily_net_pnl_bps": 0.0,
            "sharpe_annualized": 0.0,
            "win_rate": 0.0,
            "winning_days": 0,
            "losing_days": 0,
            "max_single_day_drawdown_pct": 0.0,
            "hard_stop_days": 0,
            "total_fills": 0,
            "spread_capture_dominant_source": False,
            "dominant_source": "",
            "dominant_regime": "",
            "gate_pass": False,
            "gate_failed_criteria": [],
            "warnings": [],
        },
        "days": [],
        "regime_breakdown": {},
        "narrative": "",
    }


def _journal_review_template() -> Dict[str, Any]:
    return {
        "summary": {
            "trade_count": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "realized_pnl_quote_total": 0.0,
            "fees_quote_total": 0.0,
            "avg_realized_pnl_quote": 0.0,
            "avg_hold_seconds": 0.0,
            "avg_win_quote": 0.0,
            "avg_loss_quote": 0.0,
            "avg_mfe_quote": 0.0,
            "avg_mae_quote": 0.0,
            "start_ts": "",
            "end_ts": "",
            "entry_regime_breakdown": {},
            "exit_reason_breakdown": {},
        },
        "trades": [],
        "narrative": "",
    }


def _build_trade_fill_contribution(
    fill: Dict[str, Any],
    amount_base: float,
    fee_quote: float,
    realized_pnl_quote: float,
    role: str,
) -> Dict[str, Any]:
    price = float(_to_float(fill.get("price")) or 0.0)
    ts_ms = int(fill.get("timestamp_ms") or 0)
    return {
        "ts": str(fill.get("ts") or (datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat() if ts_ms > 0 else "")),
        "timestamp_ms": ts_ms,
        "side": str(fill.get("side", "") or "").upper(),
        "price": price,
        "amount_base": float(amount_base),
        "notional_quote": float(amount_base * price),
        "fee_quote": float(fee_quote),
        "realized_pnl_quote": float(realized_pnl_quote),
        "order_id": str(fill.get("order_id", "") or ""),
        "is_maker": bool(fill.get("is_maker")),
        "role": role,
    }


def _reconstruct_closed_trades(fills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    safe_fills = [row for row in fills if isinstance(row, dict)]
    safe_fills.sort(key=lambda row: int(row.get("timestamp_ms") or 0))
    trades: List[Dict[str, Any]] = []
    pos_qty = 0.0
    avg_entry = 0.0
    entry_ts_ms = 0
    entry_notional = 0.0
    entry_qty = 0.0
    exit_notional = 0.0
    exit_qty = 0.0
    realized_accum = 0.0
    fees_accum = 0.0
    fill_count = 0
    maker_count = 0
    trade_id = 1
    entry_side_sign = 0.0
    trade_fills: List[Dict[str, Any]] = []
    eps = 1e-12

    def _emit_trade(exit_ts_ms: int) -> None:
        nonlocal entry_ts_ms, entry_notional, entry_qty, exit_notional, exit_qty, realized_accum, fees_accum, fill_count, maker_count, trade_id, entry_side_sign, trade_fills
        if entry_qty <= eps or exit_qty <= eps:
            return
        side = "long" if entry_side_sign >= 0 else "short"
        avg_entry_price = entry_notional / entry_qty if entry_qty > eps else 0.0
        avg_exit_price = exit_notional / exit_qty if exit_qty > eps else 0.0
        trades.append(
            {
                "trade_id": f"trade-{trade_id}",
                "entry_ts_ms": int(entry_ts_ms),
                "exit_ts_ms": int(exit_ts_ms),
                "entry_ts": datetime.fromtimestamp(entry_ts_ms / 1000, tz=timezone.utc).isoformat() if entry_ts_ms > 0 else "",
                "exit_ts": datetime.fromtimestamp(exit_ts_ms / 1000, tz=timezone.utc).isoformat() if exit_ts_ms > 0 else "",
                "side": side,
                "quantity": float(exit_qty),
                "avg_entry_price": float(avg_entry_price),
                "avg_exit_price": float(avg_exit_price),
                "realized_pnl_quote": float(realized_accum),
                "fees_quote": float(fees_accum),
                "hold_seconds": max(0.0, (float(exit_ts_ms) - float(entry_ts_ms)) / 1000.0),
                "fill_count": int(fill_count),
                "maker_ratio": (float(maker_count) / float(fill_count)) if fill_count > 0 else 0.0,
                "fills": list(trade_fills),
            }
        )
        trade_id += 1
        entry_ts_ms = 0
        entry_notional = 0.0
        entry_qty = 0.0
        exit_notional = 0.0
        exit_qty = 0.0
        realized_accum = 0.0
        fees_accum = 0.0
        fill_count = 0
        maker_count = 0
        entry_side_sign = 0.0
        trade_fills = []

    for fill in safe_fills:
        ts_ms = int(fill.get("timestamp_ms") or 0)
        side_raw = str(fill.get("side", "") or "").strip().lower()
        sign = 1.0 if side_raw == "buy" else -1.0 if side_raw == "sell" else 0.0
        qty = abs(float(_to_float(fill.get("amount_base")) or 0.0))
        price = float(_to_float(fill.get("price")) or 0.0)
        realized_fill = float(_to_float(fill.get("realized_pnl_quote")) or 0.0)
        fee_fill = float(_to_float(fill.get("fee_quote")) or 0.0)
        is_maker = bool(fill.get("is_maker"))
        if sign == 0.0 or qty <= eps or price <= 0.0 or ts_ms <= 0:
            continue

        remaining_qty = qty
        remaining_realized = realized_fill
        remaining_fee = fee_fill

        if abs(pos_qty) <= eps:
            pos_qty = sign * remaining_qty
            avg_entry = price
            entry_side_sign = sign
            entry_ts_ms = ts_ms
            entry_notional = remaining_qty * price
            entry_qty = remaining_qty
            exit_notional = 0.0
            exit_qty = 0.0
            realized_accum = 0.0
            fees_accum = remaining_fee
            fill_count = 1
            maker_count = 1 if is_maker else 0
            trade_fills = [_build_trade_fill_contribution(fill, remaining_qty, remaining_fee, 0.0, "entry")]
            continue

        current_sign = 1.0 if pos_qty > 0 else -1.0
        if sign == current_sign:
            total_qty = abs(pos_qty) + remaining_qty
            avg_entry = ((abs(pos_qty) * avg_entry) + (remaining_qty * price)) / total_qty if total_qty > eps else price
            pos_qty = current_sign * total_qty
            entry_notional += remaining_qty * price
            entry_qty += remaining_qty
            fees_accum += remaining_fee
            fill_count += 1
            if is_maker:
                maker_count += 1
            trade_fills.append(_build_trade_fill_contribution(fill, remaining_qty, remaining_fee, 0.0, "entry"))
            continue

        while remaining_qty > eps and abs(pos_qty) > eps and sign != (1.0 if pos_qty > 0 else -1.0):
            close_qty = min(abs(pos_qty), remaining_qty)
            ratio = close_qty / qty if qty > eps else 0.0
            realized_piece = realized_fill * ratio
            fee_piece = fee_fill * ratio
            exit_notional += close_qty * price
            exit_qty += close_qty
            realized_accum += realized_piece
            fees_accum += fee_piece
            fill_count += 1
            if is_maker:
                maker_count += 1
            trade_fills.append(_build_trade_fill_contribution(fill, close_qty, fee_piece, realized_piece, "exit"))
            remaining_qty -= close_qty
            remaining_realized -= realized_piece
            remaining_fee -= fee_piece
            next_abs = abs(pos_qty) - close_qty
            pos_qty = (1.0 if pos_qty > 0 else -1.0) * next_abs
            if abs(pos_qty) <= eps:
                _emit_trade(ts_ms)
                pos_qty = 0.0
                avg_entry = 0.0

        if remaining_qty > eps:
            pos_qty = sign * remaining_qty
            avg_entry = price
            entry_side_sign = sign
            entry_ts_ms = ts_ms
            entry_notional = remaining_qty * price
            entry_qty = remaining_qty
            exit_notional = 0.0
            exit_qty = 0.0
            realized_accum = 0.0
            fees_accum = max(0.0, remaining_fee)
            fill_count = 1
            maker_count = 1 if is_maker else 0
            trade_fills = [_build_trade_fill_contribution(fill, remaining_qty, max(0.0, remaining_fee), 0.0, "entry")]

    return trades


def _nearest_context_row(target_ms: int, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    nearest: Dict[str, Any] = {}
    nearest_distance: Optional[int] = None
    for row in rows:
        ts_ms = int(row.get("timestamp_ms") or 0)
        if ts_ms <= 0:
            continue
        distance = abs(ts_ms - target_ms)
        if nearest_distance is None or distance < nearest_distance:
            nearest = row
            nearest_distance = distance
    return nearest


def _split_risk_reasons(raw: Any) -> List[str]:
    parts = [part.strip() for part in str(raw or "").split("|")]
    return [part for part in parts if part]


def _build_quote_gate_summary(minute: Dict[str, Any]) -> Dict[str, Any]:
    controller_state = str(minute.get("state", "") or "").strip().lower()
    risk_reasons = _split_risk_reasons(minute.get("risk_reasons"))
    order_book_stale = _to_bool(minute.get("order_book_stale"))
    pnl_governor_active = _to_bool(minute.get("pnl_governor_active"))
    spread_cap_active = _to_bool(minute.get("spread_competitiveness_cap_active"))
    soft_pause_edge = _to_bool(minute.get("soft_pause_edge"))
    orders_active = int(_to_float(minute.get("orders_active")) or 0)
    net_edge_pct = float(_to_float(minute.get("net_edge_pct")) or 0.0)
    net_edge_gate_pct = float(_to_float(minute.get("net_edge_gate_pct")) or 0.0)
    adaptive_effective_min_edge_pct = float(_to_float(minute.get("adaptive_effective_min_edge_pct")) or 0.0)
    edge_threshold = max(net_edge_gate_pct, adaptive_effective_min_edge_pct)
    spread_pct = float(_to_float(minute.get("spread_pct")) or 0.0)
    spread_floor_pct = float(_to_float(minute.get("spread_floor_pct")) or 0.0)

    quote_gates: List[Dict[str, Any]] = [
        {
            "key": "controller_state",
            "label": "Controller state",
            "status": "fail" if controller_state == "hard_stop" else "warn" if controller_state == "soft_pause" else "pass",
            "detail": controller_state or "running",
        },
        {
            "key": "risk_reasons",
            "label": "Risk reasons",
            "status": "fail" if risk_reasons else "pass",
            "detail": "|".join(risk_reasons) if risk_reasons else "none",
        },
        {
            "key": "order_book",
            "label": "Order book freshness",
            "status": "fail" if order_book_stale else "pass",
            "detail": "stale" if order_book_stale else "fresh",
        },
        {
            "key": "edge",
            "label": "Net edge >= threshold",
            "status": "pass" if edge_threshold <= 0 or net_edge_pct >= edge_threshold else "fail",
            "detail": f"{net_edge_pct:.6f} / {edge_threshold:.6f}",
        },
        {
            "key": "spread",
            "label": "Spread >= floor",
            "status": "pass" if spread_floor_pct <= 0 or spread_pct >= spread_floor_pct else "fail",
            "detail": f"{spread_pct:.6f} / {spread_floor_pct:.6f}",
        },
        {
            "key": "spread_cap",
            "label": "Competitiveness cap",
            "status": "warn" if spread_cap_active else "pass",
            "detail": "active" if spread_cap_active else "inactive",
        },
        {
            "key": "pnl_governor",
            "label": "PnL governor",
            "status": "warn" if pnl_governor_active else "pass",
            "detail": str(minute.get("pnl_governor_activation_reason", "") or "off"),
        },
        {
            "key": "orders",
            "label": "Orders active",
            "status": "info" if orders_active > 0 else "warn",
            "detail": str(orders_active),
        },
    ]

    failed = [gate for gate in quote_gates if gate["status"] == "fail"]
    warned = [gate for gate in quote_gates if gate["status"] == "warn"]
    only_soft_pause_risk = bool(risk_reasons) and all(reason == "soft_pause_edge" for reason in risk_reasons)
    if soft_pause_edge and controller_state != "hard_stop" and (not risk_reasons or only_soft_pause_risk) and not order_book_stale:
        quoting_status = "waiting"
        quoting_reason = "Soft pause edge gate active"
    elif failed:
        quoting_status = "blocked" if controller_state == "hard_stop" else "not quoting"
        quoting_reason = f"{failed[0]['label']}: {failed[0]['detail']}"
    elif warned:
        quoting_status = "limited" if orders_active > 0 else "waiting"
        quoting_reason = f"{warned[0]['label']}: {warned[0]['detail']}"
    elif orders_active > 0:
        quoting_status = "quoting"
        quoting_reason = f"{orders_active} orders active"
    else:
        quoting_status = "ready"
        quoting_reason = "All quote gates passing"

    return {
        "soft_pause_edge": soft_pause_edge,
        "net_edge_pct": net_edge_pct,
        "net_edge_gate_pct": net_edge_gate_pct,
        "adaptive_effective_min_edge_pct": adaptive_effective_min_edge_pct,
        "spread_pct": spread_pct,
        "spread_floor_pct": spread_floor_pct,
        "spread_competitiveness_cap_active": spread_cap_active,
        "orders_active": orders_active,
        "quoting_status": quoting_status,
        "quoting_reason": quoting_reason,
        "quote_gates": quote_gates,
    }


def _build_runtime_open_order_placeholders(
    orders_active: int,
    best_bid: Optional[float],
    best_ask: Optional[float],
    mid_price: Optional[float],
    quantity: Optional[float],
    trading_pair: str = "",
    timestamp_ms: Optional[int] = None,
    source_label: str = "runtime",
) -> List[Dict[str, Any]]:
    count = max(0, int(orders_active or 0))
    if count <= 0:
        return []
    ts_ms = int(timestamp_ms or _now_ms())
    qty_abs = abs(float(quantity)) if quantity is not None else None
    pair = str(trading_pair or "")
    bid_hint = best_bid if best_bid is not None else mid_price
    ask_hint = best_ask if best_ask is not None else mid_price
    price_hint_source = "book" if best_bid is not None or best_ask is not None else "mid" if mid_price is not None else "none"
    out: List[Dict[str, Any]] = []
    if count >= 2:
        out.append(
            {
                "order_id": f"{source_label}-{pair or 'pair'}-buy-1",
                "side": "buy",
                "price": bid_hint,
                "amount": qty_abs,
                "quantity": qty_abs,
                "state": source_label,
                "trading_pair": pair,
                "is_estimated": True,
                "estimate_source": source_label,
                "price_hint_source": price_hint_source,
                "updated_ts_ms": ts_ms,
            }
        )
        out.append(
            {
                "order_id": f"{source_label}-{pair or 'pair'}-sell-1",
                "side": "sell",
                "price": ask_hint,
                "amount": qty_abs,
                "quantity": qty_abs,
                "state": source_label,
                "trading_pair": pair,
                "is_estimated": True,
                "estimate_source": source_label,
                "price_hint_source": price_hint_source,
                "updated_ts_ms": ts_ms,
            }
        )
        return out[:count]
    side = "buy" if quantity is not None and quantity < 0 else "sell"
    price = bid_hint if side == "buy" else ask_hint
    out.append(
        {
            "order_id": f"{source_label}-{pair or 'pair'}-open-1",
            "side": side,
            "price": price,
            "amount": qty_abs,
            "quantity": qty_abs,
            "state": source_label,
            "trading_pair": pair,
            "is_estimated": True,
            "estimate_source": source_label,
            "price_hint_source": price_hint_source,
            "updated_ts_ms": ts_ms,
        }
    )
    return out


def _build_gate_timeline(minute_rows: List[Dict[str, Any]], max_segments: int = 200) -> List[Dict[str, Any]]:
    safe_rows = [row for row in minute_rows if isinstance(row, dict)]
    safe_rows.sort(key=lambda row: int(row.get("timestamp_ms") or 0))
    if not safe_rows:
        return []
    segments: List[Dict[str, Any]] = []
    active: Optional[Dict[str, Any]] = None
    for row in safe_rows:
        ts_ms = int(row.get("timestamp_ms") or 0)
        if ts_ms <= 0:
            continue
        gate_summary = _build_quote_gate_summary(row)
        quoting_status = str(gate_summary.get("quoting_status") or "")
        quoting_reason = str(gate_summary.get("quoting_reason") or "")
        controller_state = str(row.get("state", "") or "")
        regime = str(row.get("regime", "") or "")
        risk_reasons = str(row.get("risk_reasons", "") or "")
        signature = "|".join([quoting_status, quoting_reason, controller_state, regime, risk_reasons])
        if active is None or active["signature"] != signature:
            if active is not None:
                segments.append(
                    {
                        "start_ts_ms": int(active["start_ts_ms"]),
                        "end_ts_ms": int(active["end_ts_ms"]),
                        "start_ts": datetime.fromtimestamp(int(active["start_ts_ms"]) / 1000, tz=timezone.utc).isoformat(),
                        "end_ts": datetime.fromtimestamp(int(active["end_ts_ms"]) / 1000, tz=timezone.utc).isoformat(),
                        "duration_seconds": max(0.0, (float(active["end_ts_ms"]) - float(active["start_ts_ms"])) / 1000.0),
                        "quoting_status": str(active["quoting_status"]),
                        "quoting_reason": str(active["quoting_reason"]),
                        "controller_state": str(active["controller_state"]),
                        "regime": str(active["regime"]),
                        "risk_reasons": str(active["risk_reasons"]),
                        "orders_active": int(active["orders_active"]),
                    }
                )
            active = {
                "signature": signature,
                "start_ts_ms": ts_ms,
                "end_ts_ms": ts_ms,
                "quoting_status": quoting_status,
                "quoting_reason": quoting_reason,
                "controller_state": controller_state,
                "regime": regime,
                "risk_reasons": risk_reasons,
                "orders_active": int(gate_summary.get("orders_active") or 0),
            }
        else:
            active["end_ts_ms"] = ts_ms
            active["orders_active"] = int(gate_summary.get("orders_active") or active["orders_active"])
    if active is not None:
        segments.append(
            {
                "start_ts_ms": int(active["start_ts_ms"]),
                "end_ts_ms": int(active["end_ts_ms"]),
                "start_ts": datetime.fromtimestamp(int(active["start_ts_ms"]) / 1000, tz=timezone.utc).isoformat(),
                "end_ts": datetime.fromtimestamp(int(active["end_ts_ms"]) / 1000, tz=timezone.utc).isoformat(),
                "duration_seconds": max(0.0, (float(active["end_ts_ms"]) - float(active["start_ts_ms"])) / 1000.0),
                "quoting_status": str(active["quoting_status"]),
                "quoting_reason": str(active["quoting_reason"]),
                "controller_state": str(active["controller_state"]),
                "regime": str(active["regime"]),
                "risk_reasons": str(active["risk_reasons"]),
                "orders_active": int(active["orders_active"]),
            }
        )
    return segments[-max(1, int(max_segments)) :]


def _infer_trade_exit_reason(
    realized_pnl_quote: float,
    exit_state: str,
    risk_reasons: List[str],
    pnl_governor_seen: bool,
    order_book_stale_seen: bool,
) -> str:
    state = str(exit_state or "").strip().lower()
    risk_blob = "|".join(risk_reasons).lower()
    if state == "hard_stop":
        return "hard stop"
    if "derisk" in risk_blob or "base_pct_above_max" in risk_blob or "drawdown" in risk_blob or "daily_loss" in risk_blob:
        return "risk / derisk"
    if pnl_governor_seen:
        return "pnl governor"
    if order_book_stale_seen:
        return "book stale"
    if realized_pnl_quote > 0:
        return "profitable close"
    if realized_pnl_quote < 0:
        return "adverse close"
    return "flat close"


def _sample_trade_path_points(window: List[Dict[str, Any]], max_points: int = 120) -> List[Dict[str, Any]]:
    safe_window = [row for row in window if isinstance(row, dict)]
    if not safe_window:
        return []
    if len(safe_window) <= max_points:
        sampled = safe_window
    else:
        step = max(1, len(safe_window) // max_points)
        sampled = safe_window[::step]
        if sampled[-1] is not safe_window[-1]:
            sampled = sampled[: max_points - 1] + [safe_window[-1]]
    return [
        {
            "ts": str(row.get("ts", "") or ""),
            "timestamp_ms": int(row.get("timestamp_ms") or 0),
            "mid": float(_to_float(row.get("mid")) or 0.0),
            "equity_quote": float(_to_float(row.get("equity_quote")) or 0.0),
            "state": str(row.get("state", "") or ""),
            "regime": str(row.get("regime", "") or ""),
        }
        for row in sampled
    ]


def _sample_trade_path_from_fills(fill_rows: List[Dict[str, Any]], max_points: int = 120) -> List[Dict[str, Any]]:
    safe_fills = [row for row in fill_rows if isinstance(row, dict)]
    if not safe_fills:
        return []
    if len(safe_fills) <= max_points:
        sampled = safe_fills
    else:
        step = max(1, len(safe_fills) // max_points)
        sampled = safe_fills[::step]
        if sampled[-1] is not safe_fills[-1]:
            sampled = sampled[: max_points - 1] + [safe_fills[-1]]
    return [
        {
            "ts": str(row.get("ts", "") or ""),
            "timestamp_ms": int(row.get("timestamp_ms") or 0),
            "mid": float(_to_float(row.get("price")) or 0.0),
            "equity_quote": 0.0,
            "state": str(row.get("role", "") or ""),
            "regime": "",
        }
        for row in sampled
    ]


def _enrich_closed_trades_with_minute_context(
    trades: List[Dict[str, Any]],
    minute_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    safe_minutes = [row for row in minute_rows if isinstance(row, dict)]
    safe_minutes.sort(key=lambda row: int(row.get("timestamp_ms") or 0))
    enriched: List[Dict[str, Any]] = []
    for trade in trades:
        entry_ms = int(trade.get("entry_ts_ms") or 0)
        exit_ms = int(trade.get("exit_ts_ms") or 0)
        side = str(trade.get("side", "") or "").strip().lower()
        qty = abs(float(_to_float(trade.get("quantity")) or 0.0))
        entry_price = float(_to_float(trade.get("avg_entry_price")) or 0.0)
        realized_pnl = float(_to_float(trade.get("realized_pnl_quote")) or 0.0)
        direction = 1.0 if side == "long" else -1.0 if side == "short" else 0.0
        window = [
            row
            for row in safe_minutes
            if int(row.get("timestamp_ms") or 0) >= entry_ms and int(row.get("timestamp_ms") or 0) <= exit_ms
        ]
        entry_ctx = _nearest_context_row(entry_ms, safe_minutes)
        exit_ctx = _nearest_context_row(exit_ms, safe_minutes)
        risk_tags: List[str] = []
        seen: set[str] = set()
        for row in window:
            for risk in _split_risk_reasons(row.get("risk_reasons")):
                if risk not in seen:
                    seen.add(risk)
                    risk_tags.append(risk)
        pnl_governor_seen = any(_to_bool(row.get("pnl_governor_active")) for row in window)
        order_book_stale_seen = any(_to_bool(row.get("order_book_stale")) for row in window)
        mfe_quote = 0.0
        mae_quote = 0.0
        mfe_ts = ""
        mae_ts = ""
        trade_fill_rows = [row for row in trade.get("fills", []) if isinstance(row, dict)]
        mid_open = float(_to_float(window[0].get("mid")) or 0.0) if window else float(_to_float(trade_fill_rows[0].get("price")) or 0.0) if trade_fill_rows else 0.0
        mid_close = float(_to_float(window[-1].get("mid")) or 0.0) if window else float(_to_float(trade_fill_rows[-1].get("price")) or 0.0) if trade_fill_rows else 0.0
        mid_high = max((float(_to_float(row.get("mid")) or 0.0) for row in window), default=0.0)
        mid_low = min((float(_to_float(row.get("mid")) or 0.0) for row in window), default=0.0)
        equity_open = float(_to_float(window[0].get("equity_quote")) or 0.0) if window else 0.0
        equity_close = float(_to_float(window[-1].get("equity_quote")) or 0.0) if window else 0.0
        if qty > 0.0 and entry_price > 0.0 and direction != 0.0 and window:
            best_quote: Optional[float] = None
            worst_quote: Optional[float] = None
            best_ts = 0
            worst_ts = 0
            for row in window:
                mid = float(_to_float(row.get("mid")) or 0.0)
                ts_ms = int(row.get("timestamp_ms") or 0)
                if mid <= 0.0 or ts_ms <= 0:
                    continue
                excursion_quote = direction * (mid - entry_price) * qty
                if best_quote is None or excursion_quote > best_quote:
                    best_quote = excursion_quote
                    best_ts = ts_ms
                if worst_quote is None or excursion_quote < worst_quote:
                    worst_quote = excursion_quote
                    worst_ts = ts_ms
            mfe_quote = max(0.0, float(best_quote or 0.0))
            mae_quote = min(0.0, float(worst_quote or 0.0))
            mfe_ts = datetime.fromtimestamp(best_ts / 1000, tz=timezone.utc).isoformat() if best_ts > 0 else ""
            mae_ts = datetime.fromtimestamp(worst_ts / 1000, tz=timezone.utc).isoformat() if worst_ts > 0 else ""
        elif qty > 0.0 and entry_price > 0.0 and direction != 0.0 and trade_fill_rows:
            best_quote: Optional[float] = None
            worst_quote: Optional[float] = None
            best_ts = 0
            worst_ts = 0
            for row in trade_fill_rows:
                mid = float(_to_float(row.get("price")) or 0.0)
                ts_ms = int(row.get("timestamp_ms") or 0)
                if mid <= 0.0 or ts_ms <= 0:
                    continue
                excursion_quote = direction * (mid - entry_price) * qty
                if best_quote is None or excursion_quote > best_quote:
                    best_quote = excursion_quote
                    best_ts = ts_ms
                if worst_quote is None or excursion_quote < worst_quote:
                    worst_quote = excursion_quote
                    worst_ts = ts_ms
            mfe_quote = max(0.0, float(best_quote or 0.0))
            mae_quote = min(0.0, float(worst_quote or 0.0))
            mfe_ts = datetime.fromtimestamp(best_ts / 1000, tz=timezone.utc).isoformat() if best_ts > 0 else ""
            mae_ts = datetime.fromtimestamp(worst_ts / 1000, tz=timezone.utc).isoformat() if worst_ts > 0 else ""
            mid_high = max((float(_to_float(row.get("price")) or 0.0) for row in trade_fill_rows), default=mid_open)
            mid_low = min((float(_to_float(row.get("price")) or 0.0) for row in trade_fill_rows), default=mid_open)
        exit_state = str(exit_ctx.get("state", "") or "")
        exit_reason_label = _infer_trade_exit_reason(
            realized_pnl,
            exit_state,
            risk_tags,
            pnl_governor_seen,
            order_book_stale_seen,
        )
        enriched.append(
            {
                **trade,
                "entry_regime": str(entry_ctx.get("regime", "") or ""),
                "entry_state": str(entry_ctx.get("state", "") or ""),
                "exit_regime": str(exit_ctx.get("regime", "") or ""),
                "exit_state": exit_state,
                "risk_reasons_seen": risk_tags,
                "pnl_governor_seen": pnl_governor_seen,
                "order_book_stale_seen": order_book_stale_seen,
                "mfe_quote": float(mfe_quote),
                "mae_quote": float(mae_quote),
                "mfe_ts": mfe_ts,
                "mae_ts": mae_ts,
                "exit_reason_label": exit_reason_label,
                "context_source": "minute_log" if safe_minutes else "fills_only",
                "gate_timeline": _build_gate_timeline(window) if window else [],
                "path_summary": {
                    "point_count": len(window) if window else len(trade_fill_rows),
                    "mid_open": mid_open,
                    "mid_close": mid_close,
                    "mid_high": mid_high,
                    "mid_low": mid_low,
                    "equity_open_quote": equity_open,
                    "equity_close_quote": equity_close,
                },
                "path_points": _sample_trade_path_points(window) if window else _sample_trade_path_from_fills(trade_fill_rows),
            }
        )
    return enriched


def _summarize_journal_review(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    payload = _journal_review_template()
    summary = payload["summary"]
    safe_trades = [row for row in trades if isinstance(row, dict)]
    winners = [row for row in safe_trades if float(_to_float(row.get("realized_pnl_quote")) or 0.0) > 0]
    losers = [row for row in safe_trades if float(_to_float(row.get("realized_pnl_quote")) or 0.0) < 0]
    trade_count = len(safe_trades)
    total_realized = sum(float(_to_float(row.get("realized_pnl_quote")) or 0.0) for row in safe_trades)
    total_fees = sum(float(_to_float(row.get("fees_quote")) or 0.0) for row in safe_trades)
    avg_hold = sum(float(_to_float(row.get("hold_seconds")) or 0.0) for row in safe_trades) / trade_count if trade_count > 0 else 0.0
    avg_mfe = sum(float(_to_float(row.get("mfe_quote")) or 0.0) for row in safe_trades) / trade_count if trade_count > 0 else 0.0
    avg_mae = sum(float(_to_float(row.get("mae_quote")) or 0.0) for row in safe_trades) / trade_count if trade_count > 0 else 0.0
    entry_regime_breakdown: Dict[str, int] = defaultdict(int)
    exit_reason_breakdown: Dict[str, int] = defaultdict(int)
    for row in safe_trades:
        entry_regime = str(row.get("entry_regime", "") or "").strip() or "unknown"
        exit_reason = str(row.get("exit_reason_label", "") or "").strip() or "unknown"
        entry_regime_breakdown[entry_regime] += 1
        exit_reason_breakdown[exit_reason] += 1
    summary.update(
        {
            "trade_count": trade_count,
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "win_rate": (float(len(winners)) / float(trade_count)) if trade_count > 0 else 0.0,
            "realized_pnl_quote_total": total_realized,
            "fees_quote_total": total_fees,
            "avg_realized_pnl_quote": (total_realized / trade_count) if trade_count > 0 else 0.0,
            "avg_hold_seconds": avg_hold,
            "avg_win_quote": (sum(float(_to_float(row.get("realized_pnl_quote")) or 0.0) for row in winners) / len(winners)) if winners else 0.0,
            "avg_loss_quote": (sum(float(_to_float(row.get("realized_pnl_quote")) or 0.0) for row in losers) / len(losers)) if losers else 0.0,
            "avg_mfe_quote": avg_mfe,
            "avg_mae_quote": avg_mae,
            "start_ts": str(safe_trades[0].get("entry_ts") or "") if safe_trades else "",
            "end_ts": str(safe_trades[-1].get("exit_ts") or "") if safe_trades else "",
            "entry_regime_breakdown": dict(entry_regime_breakdown),
            "exit_reason_breakdown": dict(exit_reason_breakdown),
        }
    )
    payload["trades"] = safe_trades[-500:]
    payload["narrative"] = (
        f"{trade_count} closed trades, realized PnL {total_realized:.4f}, fees {total_fees:.4f}, "
        f"win rate {summary['win_rate'] * 100:.1f}%, average hold {avg_hold:.1f}s, "
        f"average MFE {avg_mfe:.4f}, average MAE {avg_mae:.4f}."
    )
    return payload


def _summarize_weekly_report(instance_name: str, report: Dict[str, Any]) -> Dict[str, Any]:
    payload = _weekly_review_template()
    summary = payload["summary"]
    period = report.get("period", {}) if isinstance(report.get("period"), dict) else {}
    regime_breakdown = report.get("regime_breakdown", {}) if isinstance(report.get("regime_breakdown"), dict) else {}
    gate = report.get("road1_gate", {}) if isinstance(report.get("road1_gate"), dict) else {}
    breakdown = report.get("daily_breakdown", []) if isinstance(report.get("daily_breakdown"), list) else []
    dominant_regime = ""
    dominant_regime_count = -1
    for key, value in regime_breakdown.items():
        count = int(_to_float(value) or 0)
        if key and count > dominant_regime_count:
            dominant_regime = str(key)
            dominant_regime_count = count
    summary.update(
        {
            "period_start": str(period.get("start", "") or ""),
            "period_end": str(period.get("end", "") or ""),
            "n_days": int(report.get("n_days") or 0),
            "days_with_data": int(report.get("days_with_data") or 0),
            "total_net_pnl_quote": float(_to_float(report.get("total_net_pnl_usdt")) or 0.0),
            "mean_daily_pnl_quote": float(_to_float(report.get("mean_daily_pnl_usdt")) or 0.0),
            "mean_daily_net_pnl_bps": float(_to_float(report.get("mean_daily_net_pnl_bps")) or 0.0),
            "sharpe_annualized": float(_to_float(report.get("sharpe_annualized")) or 0.0),
            "win_rate": float(_to_float(report.get("win_rate")) or 0.0),
            "winning_days": int(report.get("winning_days") or 0),
            "losing_days": int(report.get("losing_days") or 0),
            "max_single_day_drawdown_pct": float(_to_float(report.get("max_single_day_drawdown_pct")) or 0.0),
            "hard_stop_days": int(report.get("hard_stop_days") or 0),
            "total_fills": int(report.get("total_fills") or 0),
            "spread_capture_dominant_source": bool((report.get("pnl_decomposition") or {}).get("spread_capture_dominant_source")),
            "dominant_source": str((report.get("pnl_decomposition") or {}).get("dominant_source", "") or ""),
            "dominant_regime": dominant_regime,
            "gate_pass": bool(gate.get("pass")),
            "gate_failed_criteria": list(gate.get("failed_criteria", [])) if isinstance(gate.get("failed_criteria"), list) else [],
            "warnings": list(report.get("warnings", [])) if isinstance(report.get("warnings"), list) else [],
        }
    )
    payload["days"] = [
        {
            "date": str(day.get("date", "") or ""),
            "net_pnl_quote": float(_to_float(day.get("net_pnl_usdt")) or 0.0),
            "net_pnl_bps": float(_to_float(day.get("net_pnl_bps")) or 0.0),
            "drawdown_pct": float(_to_float(day.get("drawdown_pct")) or 0.0),
            "daily_loss_pct": float(_to_float(day.get("daily_loss_pct")) or 0.0),
            "fills": int(day.get("fills") or 0),
            "turnover_x": float(_to_float(day.get("turnover_x")) or 0.0),
            "dominant_regime": str(day.get("dominant_regime", "") or ""),
            "equity_quote": float(_to_float(day.get("equity_quote")) or 0.0),
        }
        for day in breakdown
        if isinstance(day, dict)
    ]
    payload["regime_breakdown"] = regime_breakdown
    payload["narrative"] = (
        f"{instance_name} weekly review from {summary['period_start']} to {summary['period_end']}: "
        f"net PnL {summary['total_net_pnl_quote']:.4f}, Sharpe {summary['sharpe_annualized']:.3f}, "
        f"win rate {summary['win_rate'] * 100:.1f}%, dominant regime {summary['dominant_regime'] or 'n/a'}."
    )
    return payload


def _build_alerts(account_summary: Dict[str, Any], system: Dict[str, Any]) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    controller_state = str(account_summary.get("controller_state", "") or "").strip().lower()
    risk_reasons = str(account_summary.get("risk_reasons", "") or "").strip()
    if controller_state == "hard_stop":
        alerts.append({"severity": "fail", "title": "Hard stop active", "detail": "Controller runtime is in hard_stop state."})
    if risk_reasons:
        alerts.append({"severity": "warn", "title": "Risk reasons active", "detail": risk_reasons})
    if bool(account_summary.get("order_book_stale")):
        alerts.append({"severity": "warn", "title": "Order book stale", "detail": "Order book freshness flag is stale."})
    if bool(account_summary.get("pnl_governor_active")):
        reason = str(account_summary.get("pnl_governor_reason", "") or "active")
        alerts.append({"severity": "info", "title": "PnL governor active", "detail": reason})
    stream_age_ms = _to_float(system.get("stream_age_ms"))
    if stream_age_ms is not None and stream_age_ms > 15_000:
        alerts.append({"severity": "warn", "title": "Stream stale", "detail": f"Latest stream age {int(stream_age_ms)} ms."})
    if bool(system.get("fallback_active")):
        alerts.append({"severity": "warn", "title": "Fallback active", "detail": "UI is relying on degraded snapshot or CSV fallback."})
    if not bool(system.get("redis_available", True)):
        alerts.append({"severity": "fail", "title": "Redis unavailable", "detail": "Realtime stream dependency is unavailable."})
    if not bool(system.get("db_available", True)):
        alerts.append({"severity": "warn", "title": "DB unavailable", "detail": "Historical read model is unavailable."})
    return alerts


def _summarize_daily_review(day_key: str, minute_rows: List[Dict[str, Any]], fills: List[Dict[str, Any]], account_summary: Dict[str, Any]) -> Dict[str, Any]:
    payload = _daily_review_template(day_key)
    summary = payload["summary"]
    safe_minutes = [row for row in minute_rows if isinstance(row, dict)]
    safe_fills = [row for row in fills if isinstance(row, dict)]

    if safe_minutes:
        equities = [float(_to_float(row.get("equity_quote")) or 0.0) for row in safe_minutes]
        summary["equity_open_quote"] = equities[0]
        summary["equity_close_quote"] = equities[-1]
        summary["equity_high_quote"] = max(equities)
        summary["equity_low_quote"] = min(equities)
        summary["quote_balance_end_quote"] = float(_to_float(safe_minutes[-1].get("quote_balance")) or 0.0)
        summary["realized_pnl_day_quote"] = float(
            _to_float(safe_minutes[-1].get("realized_pnl_today_quote") or safe_minutes[-1].get("net_realized_pnl_today_quote")) or 0.0
        )
        summary["controller_state_end"] = str(safe_minutes[-1].get("state", "") or "")
        summary["regime_end"] = str(safe_minutes[-1].get("regime", "") or "")
        summary["risk_reasons_end"] = str(safe_minutes[-1].get("risk_reasons", "") or "")
        summary["pnl_governor_active_end"] = bool(safe_minutes[-1].get("pnl_governor_active"))
        summary["order_book_stale_end"] = bool(safe_minutes[-1].get("order_book_stale"))
        summary["minute_points"] = len(safe_minutes)
        summary["unrealized_pnl_end_quote"] = max(0.0, summary["equity_close_quote"] - summary["quote_balance_end_quote"])
        payload["equity_curve"] = [
            {
                "ts_ms": int(row.get("timestamp_ms") or 0),
                "equity_quote": float(_to_float(row.get("equity_quote")) or 0.0),
                "mid_price": float(_to_float(row.get("mid")) or 0.0),
                "state": str(row.get("state", "") or ""),
                "regime": str(row.get("regime", "") or ""),
            }
            for row in safe_minutes
            if int(row.get("timestamp_ms") or 0) > 0
        ]
    else:
        summary["equity_open_quote"] = float(_to_float(account_summary.get("equity_open_quote")) or 0.0)
        summary["equity_close_quote"] = float(_to_float(account_summary.get("equity_quote")) or 0.0)
        summary["equity_high_quote"] = float(_to_float(account_summary.get("equity_peak_quote")) or summary["equity_close_quote"])
        summary["equity_low_quote"] = min(summary["equity_open_quote"], summary["equity_close_quote"])
        summary["quote_balance_end_quote"] = float(_to_float(account_summary.get("quote_balance")) or 0.0)
        summary["controller_state_end"] = str(account_summary.get("controller_state", "") or "")
        summary["regime_end"] = str(account_summary.get("regime", "") or "")
        summary["risk_reasons_end"] = str(account_summary.get("risk_reasons", "") or "")
        summary["pnl_governor_active_end"] = bool(account_summary.get("pnl_governor_active"))
        summary["order_book_stale_end"] = bool(account_summary.get("order_book_stale"))

    hourly: Dict[int, Dict[str, Any]] = {}
    maker_count = 0
    for fill in safe_fills:
        ts_ms = int(fill.get("timestamp_ms") or 0)
        if ts_ms <= 0:
            continue
        hour_bucket = (ts_ms // 3_600_000) * 3_600_000
        bucket = hourly.setdefault(
            hour_bucket,
            {
                "hour_ts_ms": hour_bucket,
                "fill_count": 0,
                "buy_count": 0,
                "sell_count": 0,
                "maker_count": 0,
                "maker_ratio": 0.0,
                "realized_pnl_quote": 0.0,
                "notional_quote": 0.0,
                "fees_quote": 0.0,
            },
        )
        side = str(fill.get("side", "") or "").lower()
        amount_base = abs(float(_to_float(fill.get("amount_base")) or 0.0))
        price = float(_to_float(fill.get("price")) or 0.0)
        realized = float(_to_float(fill.get("realized_pnl_quote")) or 0.0)
        fees = float(_to_float(fill.get("fee_quote")) or 0.0)
        is_maker = bool(fill.get("is_maker"))
        summary["fill_count"] += 1
        if side == "buy":
            summary["buy_count"] += 1
        if side == "sell":
            summary["sell_count"] += 1
        if is_maker:
            maker_count += 1
            bucket["maker_count"] += 1
        summary["notional_quote"] += amount_base * price
        summary["fees_quote"] += fees
        bucket["fill_count"] += 1
        if side == "buy":
            bucket["buy_count"] += 1
        if side == "sell":
            bucket["sell_count"] += 1
        bucket["realized_pnl_quote"] += realized
        bucket["notional_quote"] += amount_base * price
        bucket["fees_quote"] += fees

    summary["maker_ratio"] = (float(maker_count) / float(summary["fill_count"])) if summary["fill_count"] > 0 else 0.0
    if summary["realized_pnl_day_quote"] == 0.0 and safe_fills:
        summary["realized_pnl_day_quote"] = float(sum(float(_to_float(fill.get("realized_pnl_quote")) or 0.0) for fill in safe_fills))
    for bucket in hourly.values():
        bucket["maker_ratio"] = (float(bucket["maker_count"]) / float(bucket["fill_count"])) if bucket["fill_count"] > 0 else 0.0
    payload["hourly"] = [hourly[key] for key in sorted(hourly.keys())]
    payload["fills"] = safe_fills[-400:]
    payload["gate_timeline"] = _build_gate_timeline(safe_minutes)
    risk_suffix = f" Risk: {summary['risk_reasons_end']}." if summary["risk_reasons_end"] else ""
    payload["narrative"] = (
        f"{summary['fill_count']} fills on {day_key}, realized PnL {summary['realized_pnl_day_quote']:.4f}, "
        f"close equity {summary['equity_close_quote']:.4f}, regime {summary['regime_end'] or 'n/a'}, "
        f"state {summary['controller_state_end'] or 'n/a'}.{risk_suffix}"
    )
    return payload


def _normalize_fill_activity_row(row: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    fill_count = max(0, int(row.get(f"{prefix}_fill_count") or 0))
    maker_count = max(0, int(row.get(f"{prefix}_maker_count") or 0))
    return {
        "fill_count": fill_count,
        "buy_count": max(0, int(row.get(f"{prefix}_buy_count") or 0)),
        "sell_count": max(0, int(row.get(f"{prefix}_sell_count") or 0)),
        "maker_count": maker_count,
        "maker_ratio": (float(maker_count) / float(fill_count)) if fill_count > 0 else 0.0,
        "volume_base": float(_to_float(row.get(f"{prefix}_volume_base")) or 0.0),
        "notional_quote": float(_to_float(row.get(f"{prefix}_notional_quote")) or 0.0),
        "realized_pnl_quote": float(_to_float(row.get(f"{prefix}_realized_pnl_quote")) or 0.0),
        "avg_fill_size": float(_to_float(row.get(f"{prefix}_avg_fill_size")) or 0.0),
        "avg_fill_price": float(_to_float(row.get(f"{prefix}_avg_fill_price")) or 0.0),
    }


def _summarize_fill_activity(
    fills: List[Dict[str, Any]],
    *,
    now_ms: Optional[int] = None,
    fills_total: int = 0,
) -> Dict[str, Any]:
    reference_ms = int(now_ms or _now_ms())
    latest_fill_ts_ms = 0
    windows: Dict[str, Tuple[int, Dict[str, Any]]] = {
        "window_15m": (15 * 60 * 1000, _window_summary_template()),
        "window_1h": (60 * 60 * 1000, _window_summary_template()),
    }
    for fill in fills or []:
        if not isinstance(fill, dict):
            continue
        ts_ms = int(_to_epoch_ms(fill.get("timestamp_ms") or fill.get("ts")) or 0)
        if ts_ms <= 0:
            continue
        latest_fill_ts_ms = max(latest_fill_ts_ms, ts_ms)
        age_ms = max(0, reference_ms - ts_ms)
        side = str(fill.get("side", "")).strip().lower()
        amount_base = abs(float(_to_float(fill.get("amount_base") or fill.get("amount")) or 0.0))
        price = float(_to_float(fill.get("price")) or 0.0)
        realized_pnl = float(_to_float(fill.get("realized_pnl_quote")) or 0.0)
        is_maker = bool(fill.get("is_maker"))
        notional_quote = amount_base * price
        for window_ms, bucket in windows.values():
            if age_ms > window_ms:
                continue
            bucket["fill_count"] += 1
            if side == "buy":
                bucket["buy_count"] += 1
            elif side == "sell":
                bucket["sell_count"] += 1
            if is_maker:
                bucket["maker_count"] += 1
            bucket["volume_base"] += amount_base
            bucket["notional_quote"] += notional_quote
            bucket["realized_pnl_quote"] += realized_pnl
            bucket["avg_fill_size"] += amount_base
            bucket["avg_fill_price"] += price
    for _, bucket in windows.values():
        fill_count = int(bucket["fill_count"] or 0)
        bucket["maker_ratio"] = (float(bucket["maker_count"]) / float(fill_count)) if fill_count > 0 else 0.0
        if fill_count > 0:
            bucket["avg_fill_size"] = float(bucket["avg_fill_size"]) / float(fill_count)
            bucket["avg_fill_price"] = float(bucket["avg_fill_price"]) / float(fill_count)
        else:
            bucket["avg_fill_size"] = 0.0
            bucket["avg_fill_price"] = 0.0
        for key in ("volume_base", "notional_quote", "realized_pnl_quote", "avg_fill_size", "avg_fill_price"):
            bucket[key] = round(float(bucket[key]), 8)
        bucket["maker_ratio"] = round(float(bucket["maker_ratio"]), 6)
    return {
        "fills_total": max(int(fills_total or 0), len(fills or [])),
        "latest_fill_ts_ms": latest_fill_ts_ms,
        "window_15m": windows["window_15m"][1],
        "window_1h": windows["window_1h"][1],
    }


def _state_key(payload: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(payload.get("instance_name", "")).strip(),
        str(payload.get("controller_id", "")).strip(),
        str(payload.get("trading_pair", "")).strip(),
    )


@dataclass
class RealtimeApiConfig:
    mode: str = field(default_factory=lambda: os.getenv("REALTIME_UI_API_MODE", "disabled").strip().lower())
    bind_host: str = field(default_factory=lambda: os.getenv("REALTIME_UI_API_BIND_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_PORT", "9910")))
    cors_allow_origin: str = field(default_factory=lambda: os.getenv("REALTIME_UI_API_CORS_ALLOW_ORIGIN", "*"))
    allowed_origins: str = field(default_factory=lambda: os.getenv("REALTIME_UI_API_ALLOWED_ORIGINS", "").strip())
    auth_enabled: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    )
    auth_token: str = field(default_factory=lambda: os.getenv("REALTIME_UI_API_AUTH_TOKEN", "").strip())
    allow_query_token: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_ALLOW_QUERY_TOKEN", "false").strip().lower() in {"1", "true", "yes"}
    )
    poll_ms: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_POLL_MS", "200")))
    consumer_group: str = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_CONSUMER_GROUP", "hb_realtime_ui_api_v1").strip()
    )
    consumer_name: str = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_CONSUMER_NAME", "realtime-ui-api-1").strip()
    )
    stream_stale_ms: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_STREAM_STALE_MS", "15000")))
    fallback_enabled: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_FALLBACK_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
    )
    degraded_mode_enabled: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_DEGRADED_MODE_ENABLED", "false").strip().lower()
        in {"1", "true", "yes"}
    )
    fallback_root: Path = field(
        default_factory=lambda: Path(os.getenv("HB_REPORTS_ROOT", "/workspace/hbot/reports")).resolve()
    )
    data_root: Path = field(default_factory=lambda: Path(os.getenv("HB_DATA_ROOT", "/workspace/hbot/data")).resolve())
    max_fills_per_key: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_MAX_FILLS_PER_KEY", "200")))
    max_events_per_key: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_MAX_EVENTS_PER_KEY", "200")))
    max_history_points: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_MAX_HISTORY_POINTS", "5000")))
    max_fallback_fills: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_MAX_FALLBACK_FILLS", "120")))
    max_fallback_orders: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_MAX_FALLBACK_ORDERS", "40")))
    db_enabled: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_DB_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
    )
    csv_failover_only: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_CSV_FAILOVER_ONLY", "true").strip().lower()
        in {"1", "true", "yes"}
    )
    db_lookback_hours: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_DB_LOOKBACK_HOURS", "168")))
    db_max_points_multiplier: int = field(
        default_factory=lambda: int(os.getenv("REALTIME_UI_API_DB_MAX_POINTS_MULTIPLIER", "20"))
    )
    db_statement_timeout_ms: int = field(
        default_factory=lambda: int(os.getenv("REALTIME_UI_API_DB_STATEMENT_TIMEOUT_MS", "1500"))
    )
    db_lock_timeout_ms: int = field(default_factory=lambda: int(os.getenv("REALTIME_UI_API_DB_LOCK_TIMEOUT_MS", "750")))
    sse_enabled: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_SSE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    )

    def normalized_mode(self) -> str:
        if self.mode not in {"disabled", "shadow", "active"}:
            return "disabled"
        return self.mode


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def _validate_runtime_config(cfg: RealtimeApiConfig) -> None:
    if cfg.auth_enabled and not cfg.auth_token:
        raise RuntimeError("REALTIME_UI_API_AUTH_ENABLED requires REALTIME_UI_API_AUTH_TOKEN")
    bind_ip = str(os.getenv("REALTIME_UI_API_BIND_IP", "")).strip()
    externally_exposed = bool(bind_ip and not _is_loopback_host(bind_ip))
    internal_non_loopback = not _is_loopback_host(cfg.bind_host) and str(cfg.bind_host).strip() not in {"0.0.0.0", "::"}
    if cfg.normalized_mode() != "disabled" and (externally_exposed or internal_non_loopback) and not cfg.auth_enabled:
        raise RuntimeError("non-loopback realtime_ui_api bind requires REALTIME_UI_API_AUTH_ENABLED=true")


class OpsDbReadModel:
    def __init__(self, cfg: RealtimeApiConfig):
        self._cfg = cfg
        self._enabled = bool(cfg.db_enabled and psycopg is not None)
        self._last_health_check_ms = 0
        self._last_health_ok = False
        self._rest_candle_cache: Dict[Tuple[str, str, int, int], Tuple[int, List[Dict[str, Any]]]] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _connect(self):
        if not self._enabled:
            return None
        host = os.getenv("OPS_DB_HOST", "postgres")
        port = int(os.getenv("OPS_DB_PORT", "5432"))
        dbname = os.getenv("OPS_DB_NAME", "hbot_ops")
        user = os.getenv("OPS_DB_USER", "hbot")
        password = os.getenv("OPS_DB_PASSWORD", "hbot_dev_password")
        statement_timeout_ms = max(200, int(self._cfg.db_statement_timeout_ms))
        lock_timeout_ms = max(100, int(self._cfg.db_lock_timeout_ms))
        options = f"-c statement_timeout={statement_timeout_ms} -c lock_timeout={lock_timeout_ms}"
        return psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=3,
            options=options,
        )

    def available(self) -> bool:
        if not self._enabled:
            return False
        now = _now_ms()
        if now - self._last_health_check_ms <= 5_000:
            return self._last_health_ok
        ok = False
        try:
            conn = self._connect()
            if conn is not None:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        ok = bool(cur.fetchone())
                finally:
                    conn.close()
        except Exception:
            ok = False
        self._last_health_check_ms = now
        self._last_health_ok = ok
        return ok

    def _query(self, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        try:
            conn = self._connect()
            if conn is None:
                return []
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
                    cols = [desc[0] for desc in cur.description or []]
                out: List[Dict[str, Any]] = []
                for row in rows:
                    if isinstance(row, dict):
                        out.append(row)
                    elif isinstance(row, tuple):
                        out.append({cols[idx]: row[idx] for idx in range(min(len(cols), len(row)))})
                return out
            finally:
                conn.close()
        except Exception:
            return []

    def _pair_candidates(self, trading_pair: str) -> List[str]:
        raw = str(trading_pair or "").strip().upper()
        if not raw:
            return []
        norm = _normalize_pair(raw)
        out = {raw, raw.replace("/", "-"), raw.replace("_", "-")}
        if len(norm) >= 6:
            out.add(norm)
            if "-" not in raw and "/" not in raw and "_" not in raw:
                out.add(f"{norm[:-4]}-{norm[-4:]}")
        return sorted(item for item in out if item)

    def _variant_hint(self, controller_id: str) -> str:
        raw = str(controller_id or "").strip()
        if not raw:
            return ""
        parts = [p for p in raw.split("_") if p]
        tail = parts[-1].lower() if parts else ""
        if len(tail) == 1 and tail.isalpha():
            return tail
        return ""

    def get_candles(self, connector_name: str, trading_pair: str, timeframe_s: int, limit: int) -> List[Dict[str, Any]]:
        if not self.available():
            return []
        limit = max(1, int(limit))
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT EXTRACT(EPOCH FROM bucket_minute_utc) * 1000.0 AS bucket_ms,
                   open_price,
                   high_price,
                   low_price,
                   close_price
            FROM market_quote_bar_minute
            WHERE (%(connector_name)s = '' OR connector_name = %(connector_name)s)
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND bucket_minute_utc >= NOW() - (%(lookback_hours)s::text || ' hours')::interval
            ORDER BY bucket_minute_utc DESC
            LIMIT %(limit)s
            """,
            {
                "connector_name": str(connector_name or "").strip(),
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "lookback_hours": max(1, int(self._cfg.db_lookback_hours)),
                "limit": limit,
            },
        )
        out: List[Dict[str, Any]] = []
        for row in reversed(rows):
            bucket_ms = _to_epoch_ms(row.get("bucket_ms"))
            open_price = _to_float(row.get("open_price"))
            high_price = _to_float(row.get("high_price"))
            low_price = _to_float(row.get("low_price"))
            close_price = _to_float(row.get("close_price"))
            if None in {bucket_ms, open_price, high_price, low_price, close_price}:
                continue
            out.append(
                {
                    "bucket_ms": int(bucket_ms),
                    "open": float(open_price),
                    "high": float(high_price),
                    "low": float(low_price),
                    "close": float(close_price),
                }
            )
        return out[-limit:]

    def get_position(self, instance_name: str, trading_pair: str) -> Dict[str, Any]:
        if not self.available() or not instance_name:
            return {}
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT trading_pair, quantity, avg_entry_price, unrealized_pnl_quote, side, source_ts_utc
            FROM bot_position_current
            WHERE instance_name = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
            ORDER BY source_ts_utc DESC
            LIMIT 1
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
            },
        )
        if not rows:
            return {}
        row = rows[0]
        return {
            "trading_pair": str(row.get("trading_pair", "")),
            "quantity": _to_float(row.get("quantity")) or 0.0,
            "avg_entry_price": _to_float(row.get("avg_entry_price")) or 0.0,
            "unrealized_pnl": _to_float(row.get("unrealized_pnl_quote")) or 0.0,
            "side": str(row.get("side", "")),
            "source_ts_ms": _to_epoch_ms(row.get("source_ts_utc")) or 0,
        }

    def get_rest_backfill_candles(
        self,
        connector_name: str,
        trading_pair: str,
        timeframe_s: int,
        limit: int,
    ) -> List[Dict[str, Any]]:
        exchange_id = _ccxt_exchange_id(connector_name)
        if ccxt is None or not exchange_id:
            return []
        bounded_limit = max(5, min(int(limit), 500))
        cache_key = (exchange_id, _normalize_pair(trading_pair), int(timeframe_s), bounded_limit)
        now_ms = _now_ms()
        cached = self._rest_candle_cache.get(cache_key)
        if cached is not None and (now_ms - int(cached[0])) <= 30_000:
            return list(cached[1])
        try:
            exchange_cls = getattr(ccxt, exchange_id)
            exchange = exchange_cls({"enableRateLimit": True})
            if "testnet" in str(connector_name or "").lower() and hasattr(exchange, "set_sandbox_mode"):
                exchange.set_sandbox_mode(True)
            rows = exchange.fetch_ohlcv(
                _ccxt_symbol(trading_pair),
                timeframe=_ccxt_timeframe(timeframe_s),
                limit=bounded_limit,
            )
        except Exception:
            return []
        candles: List[Dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            bucket_ms = _to_epoch_ms(row[0])
            open_price = _to_float(row[1])
            high_price = _to_float(row[2])
            low_price = _to_float(row[3])
            close_price = _to_float(row[4])
            if None in {bucket_ms, open_price, high_price, low_price, close_price}:
                continue
            candles.append(
                {
                    "bucket_ms": int(bucket_ms),
                    "open": float(open_price),
                    "high": float(high_price),
                    "low": float(low_price),
                    "close": float(close_price),
                }
            )
        self._rest_candle_cache[cache_key] = (now_ms, list(candles))
        return candles

    def get_fills(self, instance_name: str, trading_pair: str, limit: int = 120) -> List[Dict[str, Any]]:
        if not self.available() or not instance_name:
            return []
        limit = max(1, int(limit))
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT ts_utc, side, price, amount_base, realized_pnl_quote, order_id, is_maker
            FROM fills
            WHERE bot = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND ts_utc >= NOW() - (%(lookback_hours)s::text || ' hours')::interval
            ORDER BY ts_utc DESC
            LIMIT %(limit)s
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "lookback_hours": max(1, int(self._cfg.db_lookback_hours)),
                "limit": limit,
            },
        )
        out: List[Dict[str, Any]] = []
        for row in reversed(rows):
            ts_raw = row.get("ts_utc")
            ts_ms = _to_epoch_ms(ts_raw)
            out.append(
                {
                    "ts": str(ts_raw),
                    "timestamp_ms": ts_ms or 0,
                    "side": str(row.get("side", "")).upper(),
                    "price": _to_float(row.get("price")) or 0.0,
                    "amount_base": _to_float(row.get("amount_base")) or 0.0,
                    "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                    "order_id": str(row.get("order_id", "")),
                    "is_maker": bool(row.get("is_maker")),
                }
            )
        return out

    def get_fills_for_day(self, instance_name: str, trading_pair: str, day_key: str, limit: int = 4000) -> List[Dict[str, Any]]:
        if not self.available() or not instance_name:
            return []
        day_key, start_ms, end_ms = _day_bounds_utc(day_key)
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT ts_utc, side, price, amount_base, realized_pnl_quote, order_id, is_maker
            FROM fills
            WHERE bot = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND ts_utc >= %(start_ts)s::timestamptz
              AND ts_utc < %(end_ts)s::timestamptz
            ORDER BY ts_utc ASC
            LIMIT %(limit)s
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "start_ts": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
                "end_ts": datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).isoformat(),
                "limit": max(1, int(limit)),
            },
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            ts_ms = _to_epoch_ms(row.get("ts_utc"))
            if ts_ms is None:
                continue
            price = _to_float(row.get("price"))
            amount_base = _to_float(row.get("amount_base"))
            if price is None:
                continue
            out.append(
                {
                    "ts": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(),
                    "timestamp_ms": ts_ms,
                    "side": str(row.get("side", "")).upper(),
                    "price": price,
                    "amount_base": amount_base if amount_base is not None else 0.0,
                    "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                    "order_id": str(row.get("order_id", "")),
                    "is_maker": bool(row.get("is_maker")),
                }
            )
        return out

    def get_fills_range(
        self,
        instance_name: str,
        trading_pair: str,
        start_day: str = "",
        end_day: str = "",
        limit: int = 10000,
    ) -> List[Dict[str, Any]]:
        if not self.available() or not instance_name:
            return []
        pair_candidates = self._pair_candidates(trading_pair)
        start_ts = None
        end_ts = None
        if str(start_day or "").strip():
            _, start_ms, _ = _day_bounds_utc(start_day)
            start_ts = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat()
        if str(end_day or "").strip():
            _, _, end_ms = _day_bounds_utc(end_day)
            end_ts = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).isoformat()
        rows = self._query(
            """
            SELECT ts_utc, side, price, amount_base, realized_pnl_quote, order_id, is_maker
            FROM fills
            WHERE bot = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND (%(start_ts)s IS NULL OR ts_utc >= %(start_ts)s::timestamptz)
              AND (%(end_ts)s IS NULL OR ts_utc < %(end_ts)s::timestamptz)
            ORDER BY ts_utc ASC
            LIMIT %(limit)s
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "start_ts": start_ts,
                "end_ts": end_ts,
                "limit": max(1, int(limit)),
            },
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            ts_ms = _to_epoch_ms(row.get("ts_utc"))
            if ts_ms is None:
                continue
            price = _to_float(row.get("price"))
            amount_base = _to_float(row.get("amount_base"))
            if price is None:
                continue
            out.append(
                {
                    "ts": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(),
                    "timestamp_ms": ts_ms,
                    "side": str(row.get("side", "")).upper(),
                    "price": price,
                    "amount_base": amount_base if amount_base is not None else 0.0,
                    "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                    "order_id": str(row.get("order_id", "")),
                    "is_maker": bool(row.get("is_maker")),
                }
            )
        return out

    def get_fill_count(self, instance_name: str, trading_pair: str) -> int:
        if not self.available() or not instance_name:
            return 0
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT COUNT(*) AS fill_count
            FROM fills
            WHERE bot = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND ts_utc >= NOW() - (%(lookback_hours)s::text || ' hours')::interval
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "lookback_hours": max(1, int(self._cfg.db_lookback_hours)),
            },
        )
        if not rows:
            return 0
        try:
            return max(0, int(rows[0].get("fill_count") or 0))
        except Exception:
            return 0

    def get_fill_activity(self, instance_name: str, trading_pair: str) -> Dict[str, Any]:
        if not self.available() or not instance_name:
            return {**_summarize_fill_activity([], fills_total=0), "realized_pnl_total_quote": 0.0}
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ) AS m15_fill_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes' AND LOWER(side) = 'buy'
                ) AS m15_buy_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes' AND LOWER(side) = 'sell'
                ) AS m15_sell_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes' AND COALESCE(is_maker, FALSE)
                ) AS m15_maker_count,
                COALESCE(SUM(ABS(COALESCE(amount_base, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ), 0) AS m15_volume_base,
                COALESCE(SUM(ABS(COALESCE(amount_base, 0) * COALESCE(price, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ), 0) AS m15_notional_quote,
                COALESCE(SUM(COALESCE(realized_pnl_quote, 0)) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ), 0) AS m15_realized_pnl_quote,
                COALESCE(AVG(ABS(COALESCE(amount_base, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ), 0) AS m15_avg_fill_size,
                COALESCE(AVG(COALESCE(price, 0)) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '15 minutes'
                ), 0) AS m15_avg_fill_price,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ) AS h1_fill_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour' AND LOWER(side) = 'buy'
                ) AS h1_buy_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour' AND LOWER(side) = 'sell'
                ) AS h1_sell_count,
                COUNT(*) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour' AND COALESCE(is_maker, FALSE)
                ) AS h1_maker_count,
                COALESCE(SUM(ABS(COALESCE(amount_base, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ), 0) AS h1_volume_base,
                COALESCE(SUM(ABS(COALESCE(amount_base, 0) * COALESCE(price, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ), 0) AS h1_notional_quote,
                COALESCE(SUM(COALESCE(realized_pnl_quote, 0)) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ), 0) AS h1_realized_pnl_quote,
                COALESCE(AVG(ABS(COALESCE(amount_base, 0))) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ), 0) AS h1_avg_fill_size,
                COALESCE(AVG(COALESCE(price, 0)) FILTER (
                    WHERE ts_utc >= NOW() - INTERVAL '1 hour'
                ), 0) AS h1_avg_fill_price,
                COUNT(*) AS fills_total,
                COALESCE(SUM(COALESCE(realized_pnl_quote, 0)), 0) AS realized_pnl_total_quote,
                EXTRACT(EPOCH FROM MAX(ts_utc)) * 1000.0 AS latest_fill_ts_ms
            FROM fills
            WHERE bot = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
              AND ts_utc >= NOW() - ((%(lookback_hours)s::int + 1)::text || ' hours')::interval
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "lookback_hours": max(1, int(self._cfg.db_lookback_hours)),
            },
        )
        if not rows:
            return {**_summarize_fill_activity([], fills_total=0), "realized_pnl_total_quote": 0.0}
        row = rows[0]
        return {
            "fills_total": max(0, int(row.get("fills_total") or 0)),
            "latest_fill_ts_ms": int(_to_epoch_ms(row.get("latest_fill_ts_ms")) or 0),
            "realized_pnl_total_quote": float(_to_float(row.get("realized_pnl_total_quote")) or 0.0),
            "window_15m": _normalize_fill_activity_row(row, "m15"),
            "window_1h": _normalize_fill_activity_row(row, "h1"),
        }

    def get_open_orders(self, instance_name: str, trading_pair: str, limit: int = 40) -> List[Dict[str, Any]]:
        if not self.available() or not instance_name:
            return []
        limit = max(1, int(limit))
        pair_candidates = self._pair_candidates(trading_pair)
        rows = self._query(
            """
            SELECT order_id, side, order_type, amount_base, price, state, updated_ts_utc
            FROM paper_exchange_open_order_current
            WHERE instance_name = %(instance_name)s
              AND (%(pair_count)s = 0 OR trading_pair = ANY(%(pairs)s))
            ORDER BY updated_ts_utc DESC
            LIMIT %(limit)s
            """,
            {
                "instance_name": instance_name,
                "pairs": pair_candidates,
                "pair_count": len(pair_candidates),
                "limit": limit,
            },
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "order_id": str(row.get("order_id", "")),
                    "side": str(row.get("side", "")).lower(),
                    "order_type": str(row.get("order_type", "")).lower(),
                    "price": _to_float(row.get("price")) or 0.0,
                    "amount": _to_float(row.get("amount_base")) or 0.0,
                    "quantity": _to_float(row.get("amount_base")) or 0.0,
                    "state": str(row.get("state", "")).lower() or "open",
                    "updated_ts_ms": _to_epoch_ms(row.get("updated_ts_utc")) or 0,
                    "is_estimated": False,
                }
            )
        return out


class DeskSnapshotFallback:
    def __init__(self, reports_root: Path, data_root: Optional[Path] = None):
        self._reports_root = reports_root
        self._data_root = (data_root or Path(os.getenv("HB_DATA_ROOT", "/workspace/hbot/data"))).resolve()

    def _snapshot_path(self, instance_name: str) -> Path:
        return self._reports_root / "desk_snapshot" / instance_name / "latest.json"

    def _read_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def get_snapshot(self, instance_name: str) -> Dict[str, Any]:
        return self._read_json(self._snapshot_path(instance_name))

    def _instance_manifest_path(self, instance_name: str) -> Path:
        return self._data_root / instance_name / "conf" / "instance_meta.json"

    def instance_metadata(self, instance_name: str) -> Dict[str, Any]:
        if not instance_name:
            return {}
        payload = self._read_json(self._instance_manifest_path(instance_name))
        return payload if isinstance(payload, dict) else {}

    def available_instances(self) -> List[str]:
        instances: set[str] = set()
        desk_snapshot_root = self._reports_root / "desk_snapshot"
        if desk_snapshot_root.exists():
            try:
                for entry in desk_snapshot_root.iterdir():
                    if not entry.is_dir() or entry.name.startswith("."):
                        continue
                    if (entry / "latest.json").exists():
                        instances.add(entry.name)
            except Exception:
                pass
        if self._data_root.exists():
            try:
                for entry in self._data_root.iterdir():
                    if not entry.is_dir() or entry.name.startswith("."):
                        continue
                    manifest = self.instance_metadata(entry.name)
                    explicit_visible = bool(
                        manifest
                        and (
                            manifest.get("visible_in_supervision") is True
                            or manifest.get("enabled") is True
                            or manifest.get("discover") is True
                        )
                    )
                    marker_visible = (entry / ".supervision_enabled").exists()
                    if explicit_visible or marker_visible:
                        instances.add(entry.name)
                        continue
                    if any((entry / child).exists() for child in ("conf", "logs", "data", "scripts")):
                        instances.add(entry.name)
            except Exception:
                pass
        return sorted(instances, key=lambda value: value.lower())

    def weekly_strategy_report(self, instance_name: str) -> Dict[str, Any]:
        candidates: List[Path] = []
        if str(instance_name or "").strip().lower() == "bot1":
            candidates.append(self._reports_root / "strategy" / "multi_day_summary_latest.json")
        candidates.append(self._reports_root / "strategy" / "multi_day_summary_latest.json")
        for path in candidates:
            payload = self._read_json(path)
            if payload:
                return payload
        return {}

    def account_summary(self, instance_name: str) -> Dict[str, Any]:
        snapshot = self.get_snapshot(instance_name)
        if not snapshot:
            return _account_summary_template()
        minute = snapshot.get("minute", {}) if isinstance(snapshot.get("minute"), dict) else {}
        daily_state = snapshot.get("daily_state", {}) if isinstance(snapshot.get("daily_state"), dict) else {}
        portfolio = snapshot.get("portfolio", {}) if isinstance(snapshot.get("portfolio"), dict) else {}
        portfolio_inner = portfolio.get("portfolio", {}) if isinstance(portfolio.get("portfolio"), dict) else {}
        gate_summary = _build_quote_gate_summary(minute)
        return {
            "equity_quote": float(_to_float(snapshot.get("equity_quote") or minute.get("equity_quote")) or 0.0),
            "quote_balance": float(_to_float(snapshot.get("quote_balance") or minute.get("quote_balance")) or 0.0),
            "equity_open_quote": float(
                _to_float(
                    snapshot.get("equity_open")
                    or minute.get("equity_open")
                    or daily_state.get("equity_open")
                    or portfolio_inner.get("daily_open_equity")
                )
                or 0.0
            ),
            "equity_peak_quote": float(
                _to_float(
                    snapshot.get("equity_peak")
                    or minute.get("equity_peak")
                    or daily_state.get("equity_peak")
                    or portfolio_inner.get("peak_equity")
                )
                or 0.0
            ),
            "realized_pnl_quote": 0.0,
            "controller_state": str(minute.get("state", "") or ""),
            "regime": str(minute.get("regime", "") or ""),
            "pnl_governor_active": _to_bool(minute.get("pnl_governor_active")),
            "pnl_governor_reason": str(minute.get("pnl_governor_activation_reason", "") or ""),
            "risk_reasons": str(minute.get("risk_reasons", "") or ""),
            "daily_loss_pct": float(_to_float(minute.get("daily_loss_pct")) or 0.0),
            "max_daily_loss_pct_hard": float(_to_float(minute.get("max_daily_loss_pct_hard")) or 0.0),
            "drawdown_pct": float(_to_float(minute.get("drawdown_pct")) or 0.0),
            "max_drawdown_pct_hard": float(_to_float(minute.get("max_drawdown_pct_hard")) or 0.0),
            "order_book_stale": _to_bool(minute.get("order_book_stale")),
            "soft_pause_edge": bool(gate_summary.get("soft_pause_edge")),
            "net_edge_pct": float(gate_summary.get("net_edge_pct") or 0.0),
            "net_edge_gate_pct": float(gate_summary.get("net_edge_gate_pct") or 0.0),
            "adaptive_effective_min_edge_pct": float(gate_summary.get("adaptive_effective_min_edge_pct") or 0.0),
            "spread_pct": float(gate_summary.get("spread_pct") or 0.0),
            "spread_floor_pct": float(gate_summary.get("spread_floor_pct") or 0.0),
            "spread_competitiveness_cap_active": bool(gate_summary.get("spread_competitiveness_cap_active")),
            "orders_active": int(gate_summary.get("orders_active") or 0),
            "quoting_status": str(gate_summary.get("quoting_status") or ""),
            "quoting_reason": str(gate_summary.get("quoting_reason") or ""),
            "quote_gates": list(gate_summary.get("quote_gates") or []),
            "snapshot_ts": str(snapshot.get("source_ts") or minute.get("ts") or ""),
        }

    def _minute_csv_candidates(self, instance_name: str) -> List[Path]:
        if not instance_name:
            return []
        root = self._data_root / instance_name / "logs" / "epp_v24"
        if not root.exists():
            return []
        try:
            return sorted(root.glob("*/minute.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            return list(root.glob("*/minute.csv"))

    def _fills_csv_candidates(self, instance_name: str) -> List[Path]:
        if not instance_name:
            return []
        root = self._data_root / instance_name / "logs" / "epp_v24"
        if not root.exists():
            return []
        try:
            return sorted(root.glob("*/fills.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            return list(root.glob("*/fills.csv"))

    def _paper_exchange_state_snapshot_path(self) -> Path:
        return self._reports_root / "verification" / "paper_exchange_state_snapshot_latest.json"

    def _parse_ts_ms(self, value: Any) -> Optional[int]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            if raw.isdigit():
                parsed = int(raw)
                return parsed if parsed > 10_000_000_000 else parsed * 1000
        except Exception:
            return None
        try:
            normalized = raw.replace("Z", "+00:00")
            return int(datetime.fromisoformat(normalized).timestamp() * 1000)
        except Exception:
            return None

    def candles_from_minute_log(
        self,
        instance_name: str,
        trading_pair: str = "",
        timeframe_s: int = 60,
        limit: int = 300,
    ) -> List[Dict[str, Any]]:
        timeframe_ms = max(1, int(timeframe_s)) * 1000
        limit = max(1, int(limit))
        trading_pair_norm = _normalize_pair(trading_pair)
        minutes_per_bucket = max(1, timeframe_ms // 60_000)
        tail_rows = max(1200, min(50_000, limit * minutes_per_bucket * 8))

        for csv_path in self._minute_csv_candidates(instance_name):
            points: Deque[Tuple[int, float]] = deque(maxlen=tail_rows)
            try:
                with csv_path.open("r", encoding="utf-8", newline="") as fp:
                    reader = csv.DictReader(fp)
                    for row in reader:
                        if not isinstance(row, dict):
                            continue
                        if trading_pair_norm:
                            row_pair = _normalize_pair(row.get("trading_pair"))
                            if row_pair and row_pair != trading_pair_norm:
                                continue
                        ts_ms = self._parse_ts_ms(row.get("ts"))
                        mid = _to_float(row.get("mid"))
                        if ts_ms is None or mid is None:
                            continue
                        points.append((ts_ms, mid))
            except Exception:
                continue

            if not points:
                continue

            buckets: Dict[int, Dict[str, Any]] = {}
            last_close: Optional[float] = None
            last_bucket: Optional[int] = None
            for ts_ms, price in points:
                bucket = (ts_ms // timeframe_ms) * timeframe_ms
                row = buckets.get(bucket)
                if row is None:
                    open_price = price
                    # Minute snapshots contain one mid point per minute; bridge contiguous bars to avoid flat 1m candles.
                    if timeframe_ms <= 60_000 and last_close is not None and last_bucket != bucket:
                        open_price = last_close
                    buckets[bucket] = {
                        "bucket_ms": bucket,
                        "open": open_price,
                        "high": max(open_price, price),
                        "low": min(open_price, price),
                        "close": price,
                    }
                    last_close = price
                    last_bucket = bucket
                    continue
                row["high"] = max(float(row["high"]), price)
                row["low"] = min(float(row["low"]), price)
                row["close"] = price
                last_close = price
                last_bucket = bucket

            candles = [buckets[k] for k in sorted(buckets.keys())]
            if candles:
                return candles[-limit:]
        return []

    def fills_from_csv(
        self,
        instance_name: str,
        trading_pair: str = "",
        limit: int = 120,
    ) -> List[Dict[str, Any]]:
        limit = max(1, int(limit))
        trading_pair_norm = _normalize_pair(trading_pair)
        tail_rows = max(400, min(80_000, limit * 40))
        for csv_path in self._fills_csv_candidates(instance_name):
            rows: Deque[Dict[str, Any]] = deque(maxlen=tail_rows)
            try:
                with csv_path.open("r", encoding="utf-8", newline="") as fp:
                    reader = csv.DictReader(fp)
                    for row in reader:
                        if not isinstance(row, dict):
                            continue
                        row_pair_norm = _normalize_pair(row.get("trading_pair"))
                        if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                            continue
                        ts_ms = self._parse_ts_ms(row.get("ts"))
                        price = _to_float(row.get("price"))
                        amount_base = _to_float(row.get("amount_base"))
                        if ts_ms is None or price is None:
                            continue
                        rows.append(
                            {
                                "ts": str(row.get("ts", "")),
                                "timestamp_ms": ts_ms,
                                "side": str(row.get("side", "")).upper(),
                                "price": price,
                                "amount_base": amount_base if amount_base is not None else 0.0,
                                "notional_quote": _to_float(row.get("notional_quote")) or 0.0,
                                "fee_quote": _to_float(row.get("fee_quote")) or 0.0,
                                "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                                "order_id": str(row.get("order_id", "")),
                                "is_maker": str(row.get("is_maker", "")).strip().lower() in {"1", "true", "yes"},
                            }
                        )
            except Exception:
                continue
            if rows:
                return list(rows)[-limit:]
        return []

    def minute_rows_from_csv(
        self,
        instance_name: str,
        trading_pair: str = "",
        day_key: str = "",
    ) -> List[Dict[str, Any]]:
        trading_pair_norm = _normalize_pair(trading_pair)
        _, start_ms, end_ms = _day_bounds_utc(day_key)
        for csv_path in self._minute_csv_candidates(instance_name):
            rows: List[Dict[str, Any]] = []
            try:
                with csv_path.open("r", encoding="utf-8", newline="") as fp:
                    reader = csv.DictReader(fp)
                    for row in reader:
                        if not isinstance(row, dict):
                            continue
                        row_pair_norm = _normalize_pair(row.get("trading_pair"))
                        if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                            continue
                        ts_ms = self._parse_ts_ms(row.get("ts"))
                        if ts_ms is None or ts_ms < start_ms or ts_ms >= end_ms:
                            continue
                        rows.append(
                            {
                                "ts": str(row.get("ts", "")),
                                "timestamp_ms": ts_ms,
                                "mid": _to_float(row.get("mid")) or 0.0,
                                "equity_quote": _to_float(row.get("equity_quote")) or 0.0,
                                "quote_balance": _to_float(row.get("quote_balance")) or 0.0,
                                "realized_pnl_today_quote": _to_float(row.get("realized_pnl_today_quote")) or 0.0,
                                "net_realized_pnl_today_quote": _to_float(row.get("net_realized_pnl_today_quote")) or 0.0,
                                "state": str(row.get("state", "") or ""),
                                "regime": str(row.get("regime", "") or ""),
                                "risk_reasons": str(row.get("risk_reasons", "") or ""),
                                "pnl_governor_active": _to_bool(row.get("pnl_governor_active")),
                                "order_book_stale": _to_bool(row.get("order_book_stale")),
                                "soft_pause_edge": _to_bool(row.get("soft_pause_edge")),
                                "net_edge_pct": _to_float(row.get("net_edge_pct")) or 0.0,
                                "net_edge_gate_pct": _to_float(row.get("net_edge_gate_pct")) or 0.0,
                                "adaptive_effective_min_edge_pct": _to_float(row.get("adaptive_effective_min_edge_pct")) or 0.0,
                                "spread_pct": _to_float(row.get("spread_pct")) or 0.0,
                                "spread_floor_pct": _to_float(row.get("spread_floor_pct")) or 0.0,
                                "spread_competitiveness_cap_active": _to_bool(row.get("spread_competitiveness_cap_active")),
                                "orders_active": int(_to_float(row.get("orders_active")) or 0),
                                "pnl_governor_activation_reason": str(row.get("pnl_governor_activation_reason", "") or ""),
                            }
                        )
            except Exception:
                continue
            if rows:
                return rows
        return []

    def minute_rows_range(
        self,
        instance_name: str,
        trading_pair: str = "",
        start_day: str = "",
        end_day: str = "",
        limit: int = 20000,
    ) -> List[Dict[str, Any]]:
        trading_pair_norm = _normalize_pair(trading_pair)
        start_ms = None
        end_ms = None
        if str(start_day or "").strip():
            _, start_ms, _ = _day_bounds_utc(start_day)
        if str(end_day or "").strip():
            _, _, end_ms = _day_bounds_utc(end_day)
        limit = max(1, int(limit))
        for csv_path in self._minute_csv_candidates(instance_name):
            rows: List[Dict[str, Any]] = []
            try:
                with csv_path.open("r", encoding="utf-8", newline="") as fp:
                    reader = csv.DictReader(fp)
                    for row in reader:
                        if not isinstance(row, dict):
                            continue
                        row_pair_norm = _normalize_pair(row.get("trading_pair"))
                        if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                            continue
                        ts_ms = self._parse_ts_ms(row.get("ts"))
                        if ts_ms is None:
                            continue
                        if start_ms is not None and ts_ms < start_ms:
                            continue
                        if end_ms is not None and ts_ms >= end_ms:
                            continue
                        rows.append(
                            {
                                "ts": str(row.get("ts", "")),
                                "timestamp_ms": ts_ms,
                                "mid": _to_float(row.get("mid")) or 0.0,
                                "equity_quote": _to_float(row.get("equity_quote")) or 0.0,
                                "quote_balance": _to_float(row.get("quote_balance")) or 0.0,
                                "realized_pnl_today_quote": _to_float(row.get("realized_pnl_today_quote")) or 0.0,
                                "net_realized_pnl_today_quote": _to_float(row.get("net_realized_pnl_today_quote")) or 0.0,
                                "state": str(row.get("state", "") or ""),
                                "regime": str(row.get("regime", "") or ""),
                                "risk_reasons": str(row.get("risk_reasons", "") or ""),
                                "pnl_governor_active": _to_bool(row.get("pnl_governor_active")),
                                "order_book_stale": _to_bool(row.get("order_book_stale")),
                                "soft_pause_edge": _to_bool(row.get("soft_pause_edge")),
                                "net_edge_pct": _to_float(row.get("net_edge_pct")) or 0.0,
                                "net_edge_gate_pct": _to_float(row.get("net_edge_gate_pct")) or 0.0,
                                "adaptive_effective_min_edge_pct": _to_float(row.get("adaptive_effective_min_edge_pct")) or 0.0,
                                "spread_pct": _to_float(row.get("spread_pct")) or 0.0,
                                "spread_floor_pct": _to_float(row.get("spread_floor_pct")) or 0.0,
                                "spread_competitiveness_cap_active": _to_bool(row.get("spread_competitiveness_cap_active")),
                                "orders_active": int(_to_float(row.get("orders_active")) or 0),
                                "pnl_governor_activation_reason": str(row.get("pnl_governor_activation_reason", "") or ""),
                            }
                        )
            except Exception:
                continue
            if rows:
                return rows[-limit:]
        return []

    def fills_from_csv_for_day(
        self,
        instance_name: str,
        trading_pair: str = "",
        day_key: str = "",
        limit: int = 4000,
    ) -> List[Dict[str, Any]]:
        trading_pair_norm = _normalize_pair(trading_pair)
        _, start_ms, end_ms = _day_bounds_utc(day_key)
        limit = max(1, int(limit))
        for csv_path in self._fills_csv_candidates(instance_name):
            rows: List[Dict[str, Any]] = []
            try:
                with csv_path.open("r", encoding="utf-8", newline="") as fp:
                    reader = csv.DictReader(fp)
                    for row in reader:
                        if not isinstance(row, dict):
                            continue
                        row_pair_norm = _normalize_pair(row.get("trading_pair"))
                        if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                            continue
                        ts_ms = self._parse_ts_ms(row.get("ts"))
                        price = _to_float(row.get("price"))
                        amount_base = _to_float(row.get("amount_base"))
                        if ts_ms is None or ts_ms < start_ms or ts_ms >= end_ms or price is None:
                            continue
                        rows.append(
                            {
                                "ts": str(row.get("ts", "")),
                                "timestamp_ms": ts_ms,
                                "side": str(row.get("side", "")).upper(),
                                "price": price,
                                "amount_base": amount_base if amount_base is not None else 0.0,
                                "notional_quote": _to_float(row.get("notional_quote")) or 0.0,
                                "fee_quote": _to_float(row.get("fee_quote")) or 0.0,
                                "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                                "order_id": str(row.get("order_id", "")),
                                "is_maker": _to_bool(row.get("is_maker")),
                            }
                        )
            except Exception:
                continue
            if rows:
                return rows[-limit:]
        return []

    def fills_from_csv_range(
        self,
        instance_name: str,
        trading_pair: str = "",
        start_day: str = "",
        end_day: str = "",
        limit: int = 10000,
    ) -> List[Dict[str, Any]]:
        trading_pair_norm = _normalize_pair(trading_pair)
        start_ms = None
        end_ms = None
        if str(start_day or "").strip():
            _, start_ms, _ = _day_bounds_utc(start_day)
        if str(end_day or "").strip():
            _, _, end_ms = _day_bounds_utc(end_day)
        limit = max(1, int(limit))
        for csv_path in self._fills_csv_candidates(instance_name):
            rows: List[Dict[str, Any]] = []
            try:
                with csv_path.open("r", encoding="utf-8", newline="") as fp:
                    reader = csv.DictReader(fp)
                    for row in reader:
                        if not isinstance(row, dict):
                            continue
                        row_pair_norm = _normalize_pair(row.get("trading_pair"))
                        if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                            continue
                        ts_ms = self._parse_ts_ms(row.get("ts"))
                        price = _to_float(row.get("price"))
                        amount_base = _to_float(row.get("amount_base"))
                        if ts_ms is None or price is None:
                            continue
                        if start_ms is not None and ts_ms < start_ms:
                            continue
                        if end_ms is not None and ts_ms >= end_ms:
                            continue
                        rows.append(
                            {
                                "ts": str(row.get("ts", "")),
                                "timestamp_ms": ts_ms,
                                "side": str(row.get("side", "")).upper(),
                                "price": price,
                                "amount_base": amount_base if amount_base is not None else 0.0,
                                "notional_quote": _to_float(row.get("notional_quote")) or 0.0,
                                "fee_quote": _to_float(row.get("fee_quote")) or 0.0,
                                "realized_pnl_quote": _to_float(row.get("realized_pnl_quote")) or 0.0,
                                "order_id": str(row.get("order_id", "")),
                                "is_maker": _to_bool(row.get("is_maker")),
                            }
                        )
            except Exception:
                continue
            if rows:
                return rows[-limit:]
        return []

    def open_orders_from_state_snapshot(
        self,
        instance_name: str,
        trading_pair: str = "",
        limit: int = 40,
    ) -> List[Dict[str, Any]]:
        path = self._paper_exchange_state_snapshot_path()
        payload = self._read_json(path)
        orders = payload.get("orders", {}) if isinstance(payload.get("orders"), dict) else {}
        if not orders:
            return []
        limit = max(1, int(limit))
        trading_pair_norm = _normalize_pair(trading_pair)
        terminal_states = {"filled", "canceled", "cancelled", "rejected", "expired", "failed", "closed"}
        out: List[Dict[str, Any]] = []
        for _, order in orders.items():
            if not isinstance(order, dict):
                continue
            if instance_name and str(order.get("instance_name", "")).strip() != instance_name:
                continue
            row_pair_norm = _normalize_pair(order.get("trading_pair"))
            if trading_pair_norm and row_pair_norm and row_pair_norm != trading_pair_norm:
                continue
            state_value = str(order.get("state", "")).strip().lower()
            if state_value in terminal_states:
                continue
            price = _to_float(order.get("price"))
            if price is None:
                continue
            out.append(
                {
                    "order_id": str(order.get("order_id", "")),
                    "side": str(order.get("side", "")).lower(),
                    "price": price,
                    "amount": _to_float(order.get("amount_base")) or 0.0,
                    "quantity": _to_float(order.get("amount_base")) or 0.0,
                    "state": state_value or "open",
                    "created_ts_ms": int(_to_float(order.get("created_ts_ms")) or 0),
                    "updated_ts_ms": int(_to_float(order.get("updated_ts_ms")) or 0),
                    "is_estimated": False,
                }
            )
        out.sort(key=lambda row: int(row.get("updated_ts_ms", 0) or 0))
        return out[-limit:]

    def state_from_snapshot(
        self,
        instance_name: str,
        trading_pair: str = "",
        max_fills: int = 120,
        max_orders: int = 40,
        include_csv_fills: bool = True,
        include_estimated_orders: bool = True,
    ) -> Dict[str, Any]:
        snapshot = self.get_snapshot(instance_name)
        minute = snapshot.get("minute", {}) if isinstance(snapshot.get("minute"), dict) else {}
        portfolio = snapshot.get("portfolio", {}) if isinstance(snapshot.get("portfolio"), dict) else {}
        portfolio_inner = portfolio.get("portfolio", {}) if isinstance(portfolio.get("portfolio"), dict) else {}
        requested_pair_norm = _normalize_pair(trading_pair)
        snapshot_orders = snapshot.get("open_orders", []) if isinstance(snapshot.get("open_orders"), list) else []
        open_orders = []
        for order in snapshot_orders:
            if not isinstance(order, dict):
                continue
            if not requested_pair_norm:
                open_orders.append(order)
                continue
            row_pair_norm = _normalize_pair(order.get("trading_pair"))
            if row_pair_norm and row_pair_norm == requested_pair_norm:
                open_orders.append(order)
        if not open_orders:
            open_orders = self.open_orders_from_state_snapshot(instance_name, trading_pair, limit=max_orders)
        positions = portfolio_inner.get("positions", {}) if isinstance(portfolio_inner.get("positions"), dict) else {}
        resolved_position = {}
        if requested_pair_norm:
            for instrument_id, pos in positions.items():
                if not isinstance(pos, dict):
                    continue
                instrument_pair = str(instrument_id).split(":")[1] if ":" in str(instrument_id) else str(instrument_id)
                if requested_pair_norm == _normalize_pair(instrument_pair):
                    resolved_position = pos
                    break
        if not requested_pair_norm and not resolved_position and positions:
            # Fallback to first non-flat position so UI still shows active exposure when pair filter is stale/mismatched.
            for pos in positions.values():
                if not isinstance(pos, dict):
                    continue
                qty = _to_float(pos.get("quantity"))
                if qty is not None and abs(qty) > 0:
                    resolved_position = pos
                    break
        if not requested_pair_norm and not resolved_position and positions:
            first = next(iter(positions.values()), {})
            resolved_position = first if isinstance(first, dict) else {}

        minute_pair_norm = _normalize_pair(minute.get("trading_pair"))
        allow_runtime_estimated_orders = bool(
            not requested_pair_norm or resolved_position or (minute_pair_norm and minute_pair_norm == requested_pair_norm)
        )
        if include_estimated_orders and not open_orders and allow_runtime_estimated_orders:
            orders_active = int(_to_float(minute.get("orders_active")) or 0)
            if orders_active > 0:
                best_bid = _to_float(minute.get("best_bid_price"))
                best_ask = _to_float(minute.get("best_ask_price"))
                qty = _to_float(resolved_position.get("quantity"))
                open_orders = _build_runtime_open_order_placeholders(
                    orders_active=orders_active,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    mid_price=_to_float(minute.get("mid")) or _to_float(minute.get("mid_price")),
                    quantity=qty,
                    trading_pair=trading_pair or str(minute.get("trading_pair") or ""),
                    timestamp_ms=_to_epoch_ms(minute.get("ts")) or _to_epoch_ms(snapshot.get("source_ts")) or _now_ms(),
                    source_label="runtime",
                )

        fills = self.fills_from_csv(instance_name, trading_pair, limit=max_fills) if include_csv_fills else []
        return {
            "snapshot_ts": str(snapshot.get("source_ts", "")),
            "minute": minute,
            "open_orders": open_orders,
            "fills": fills,
            "position": resolved_position,
            "portfolio": portfolio_inner,
        }


class RealtimeState:
    def __init__(self, cfg: RealtimeApiConfig):
        self._cfg = cfg
        self._lock = threading.Lock()
        self._market: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self._depth: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self._market_quote: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._market_depth: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._market_ts_ms: Dict[Tuple[str, str, str], int] = {}
        self._depth_ts_ms: Dict[Tuple[str, str, str], int] = {}
        self._market_quote_ts_ms: Dict[Tuple[str, str], int] = {}
        self._market_depth_ts_ms: Dict[Tuple[str, str], int] = {}
        self._fills_ts_ms: Dict[Tuple[str, str, str], int] = {}
        self._paper_events_ts_ms: Dict[Tuple[str, str, str], int] = {}
        self._fills: Dict[Tuple[str, str, str], Deque[Dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=max(20, cfg.max_fills_per_key))
        )
        self._paper_events: Dict[Tuple[str, str, str], Deque[Dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=max(20, cfg.max_events_per_key))
        )
        self._history: Dict[Tuple[str, str, str], Deque[Tuple[int, float]]] = defaultdict(
            lambda: deque(maxlen=max(100, cfg.max_history_points))
        )
        self._market_history: Dict[Tuple[str, str], Deque[Tuple[int, float]]] = defaultdict(
            lambda: deque(maxlen=max(100, cfg.max_history_points))
        )
        self._stream_watermark_ms: Dict[str, int] = {}
        self._subscribers: List["queue.Queue[str]"] = []
        self._publish_seq = 0

    def _notify(self, event: Dict[str, Any]) -> None:
        payload = _safe_json(event)
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(payload)
            except Exception:
                continue

    def register_subscriber(self) -> "queue.Queue[str]":
        q: "queue.Queue[str]" = queue.Queue(maxsize=200)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unregister_subscriber(self, q: "queue.Queue[str]") -> None:
        with self._lock:
            self._subscribers = [item for item in self._subscribers if item is not q]

    def process(self, stream: str, entry_id: str, payload: Dict[str, Any]) -> None:
        ts_ms = _stream_ms(entry_id)
        key = _state_key(payload)
        pair_key = (
            str(payload.get("connector_name", "")).strip(),
            str(payload.get("trading_pair", "")).strip(),
        )
        event_type = str(payload.get("event_type", "")).strip()

        def _depth_mid(snapshot: Dict[str, Any]) -> Optional[float]:
            best_bid = _to_float(snapshot.get("best_bid"))
            best_ask = _to_float(snapshot.get("best_ask"))
            if best_bid is None or best_ask is None:
                bids = snapshot.get("bids", [])
                asks = snapshot.get("asks", [])
                if isinstance(bids, list) and bids:
                    best_bid = _to_float((bids[0] or {}).get("price"))
                if isinstance(asks, list) and asks:
                    best_ask = _to_float((asks[0] or {}).get("price"))
            if best_bid is None and best_ask is None:
                return None
            if best_bid is None:
                return best_ask
            if best_ask is None:
                return best_bid
            return (best_bid + best_ask) / 2.0

        with self._lock:
            self._stream_watermark_ms[stream] = max(ts_ms, self._stream_watermark_ms.get(stream, 0))
            if stream == MARKET_QUOTE_STREAM or event_type == "market_quote":
                self._market_quote[pair_key] = payload
                self._market_quote_ts_ms[pair_key] = ts_ms
                mid = _to_float(payload.get("mid_price"))
                if mid is not None:
                    self._market_history[pair_key].append((ts_ms, mid))
            elif stream == MARKET_DATA_STREAM or event_type == "market_snapshot":
                self._market[key] = payload
                self._market_ts_ms[key] = ts_ms
                mid = _to_float(payload.get("mid_price"))
                if mid is not None:
                    self._history[key].append((ts_ms, mid))
            elif stream == MARKET_DEPTH_STREAM or event_type == "market_depth_snapshot":
                if pair_key[0] and (not key[0] and not key[1]):
                    self._market_depth[pair_key] = payload
                    self._market_depth_ts_ms[pair_key] = ts_ms
                else:
                    self._depth[key] = payload
                    self._depth_ts_ms[key] = ts_ms
                mid = _depth_mid(payload)
                if mid is not None:
                    if pair_key[0] and (not key[0] and not key[1]):
                        self._market_history[pair_key].append((ts_ms, mid))
                    else:
                        self._history[key].append((ts_ms, mid))
            elif stream == BOT_TELEMETRY_STREAM and event_type == "bot_fill":
                self._fills[key].append(payload)
                self._fills_ts_ms[key] = ts_ms
            elif stream == PAPER_EXCHANGE_EVENT_STREAM:
                self._paper_events[key].append(payload)
                self._paper_events_ts_ms[key] = ts_ms
            self._publish_seq += 1
            seq = self._publish_seq
        self._notify({"seq": seq, "stream": stream, "event_type": event_type, "key": key, "event": payload, "ts_ms": ts_ms})

    def newest_stream_age_ms(self) -> Optional[int]:
        with self._lock:
            if not self._stream_watermark_ms:
                return None
            latest = max(self._stream_watermark_ms.values())
        return max(0, _now_ms() - latest)

    def selected_stream_age_ms(self, instance_name: str = "", controller_id: str = "", trading_pair: str = "") -> Optional[int]:
        requested_pair_norm = _normalize_pair(trading_pair)

        def _match(key: Tuple[str, str, str]) -> bool:
            i, c, p = key
            return (
                (not instance_name or instance_name == i)
                and (not controller_id or controller_id == c)
                and (not requested_pair_norm or requested_pair_norm == _normalize_pair(p))
            )

        with self._lock:
            candidate_ts: List[int] = []
            connector_name = ""
            connector_candidates: List[Tuple[int, str]] = []
            for key, ts_ms in self._market_ts_ms.items():
                if _match(key) and ts_ms > 0:
                    candidate_ts.append(ts_ms)
                    connector = str((self._market.get(key, {}) or {}).get("connector_name", "")).strip()
                    if connector:
                        connector_candidates.append((ts_ms, connector))
            for key, ts_ms in self._depth_ts_ms.items():
                if _match(key) and ts_ms > 0:
                    candidate_ts.append(ts_ms)
                    connector = str((self._depth.get(key, {}) or {}).get("connector_name", "")).strip()
                    if connector:
                        connector_candidates.append((ts_ms, connector))
            for key, ts_ms in self._fills_ts_ms.items():
                if _match(key) and ts_ms > 0:
                    candidate_ts.append(ts_ms)
            for key, ts_ms in self._paper_events_ts_ms.items():
                if _match(key) and ts_ms > 0:
                    candidate_ts.append(ts_ms)
            if connector_candidates:
                connector_name = max(connector_candidates, key=lambda item: item[0])[1]
            if requested_pair_norm:
                if connector_name:
                    pair_key = next(
                        (key for key in self._market_quote_ts_ms.keys() if key[0] == connector_name and requested_pair_norm == _normalize_pair(key[1])),
                        None,
                    )
                    if pair_key is not None:
                        candidate_ts.append(int(self._market_quote_ts_ms.get(pair_key, 0) or 0))
                    depth_pair_key = next(
                        (key for key in self._market_depth_ts_ms.keys() if key[0] == connector_name and requested_pair_norm == _normalize_pair(key[1])),
                        None,
                    )
                    if depth_pair_key is not None:
                        candidate_ts.append(int(self._market_depth_ts_ms.get(depth_pair_key, 0) or 0))
                else:
                    candidate_ts.extend(
                        int(ts_ms)
                        for key, ts_ms in self._market_quote_ts_ms.items()
                        if requested_pair_norm == _normalize_pair(key[1]) and ts_ms > 0
                    )
                    candidate_ts.extend(
                        int(ts_ms)
                        for key, ts_ms in self._market_depth_ts_ms.items()
                        if requested_pair_norm == _normalize_pair(key[1]) and ts_ms > 0
                    )
            latest = max(candidate_ts) if candidate_ts else None
        return None if latest is None else max(0, _now_ms() - latest)

    def resolve_connector_name(self, instance_name: str = "", controller_id: str = "", trading_pair: str = "") -> str:
        requested_pair_norm = _normalize_pair(trading_pair)

        def _match(key: Tuple[str, str, str]) -> bool:
            i, c, p = key
            return (
                (not instance_name or instance_name == i)
                and (not controller_id or controller_id == c)
                and (not requested_pair_norm or requested_pair_norm == _normalize_pair(p))
            )

        with self._lock:
            market_keys = [k for k in self._market.keys() if _match(k)]
            if market_keys:
                freshest_market_key = max(market_keys, key=lambda key: int(self._market_ts_ms.get(key, 0) or 0))
                connector_name = str((self._market.get(freshest_market_key, {}) or {}).get("connector_name", "")).strip()
                if connector_name:
                    return connector_name
            depth_keys = [k for k in self._depth.keys() if _match(k)]
            if depth_keys:
                freshest_depth_key = max(depth_keys, key=lambda key: int(self._depth_ts_ms.get(key, 0) or 0))
                connector_name = str((self._depth.get(freshest_depth_key, {}) or {}).get("connector_name", "")).strip()
                if connector_name:
                    return connector_name
            pair_matches = [k for k in self._market_quote.keys() if (not requested_pair_norm or requested_pair_norm == _normalize_pair(k[1]))]
            if pair_matches:
                freshest_pair_key = max(pair_matches, key=lambda key: int(self._market_quote_ts_ms.get(key, 0) or 0))
                return str(freshest_pair_key[0] or "").strip()
            depth_pair_matches = [k for k in self._market_depth.keys() if (not requested_pair_norm or requested_pair_norm == _normalize_pair(k[1]))]
            if depth_pair_matches:
                freshest_depth_pair_key = max(depth_pair_matches, key=lambda key: int(self._market_depth_ts_ms.get(key, 0) or 0))
                return str(freshest_depth_pair_key[0] or "").strip()
        return ""

    def instance_names(self) -> List[str]:
        with self._lock:
            names = {
                key[0]
                for key in (
                    list(self._market.keys())
                    + list(self._depth.keys())
                    + list(self._fills.keys())
                    + list(self._paper_events.keys())
                )
                if key[0]
            }
        return sorted(names, key=lambda value: value.lower())

    def get_state(self, instance_name: str = "", controller_id: str = "", trading_pair: str = "") -> Dict[str, Any]:
        requested_pair_norm = _normalize_pair(trading_pair)

        def _match(key: Tuple[str, str, str]) -> bool:
            i, c, p = key
            return (
                (not instance_name or instance_name == i)
                and (not controller_id or controller_id == c)
                and (not requested_pair_norm or requested_pair_norm == _normalize_pair(p))
            )

        with self._lock:
            matched_keys_with_ts: List[Tuple[int, Tuple[str, str, str]]] = []
            matched_keys_with_ts.extend((int(self._market_ts_ms.get(k, 0) or 0), k) for k in self._market.keys() if _match(k))
            matched_keys_with_ts.extend((int(self._depth_ts_ms.get(k, 0) or 0), k) for k in self._depth.keys() if _match(k))
            matched_keys_with_ts.extend((int(self._fills_ts_ms.get(k, 0) or 0), k) for k in self._fills.keys() if _match(k))
            matched_keys_with_ts.extend((int(self._paper_events_ts_ms.get(k, 0) or 0), k) for k in self._paper_events.keys() if _match(k))
            key = max(matched_keys_with_ts, key=lambda item: item[0])[1] if matched_keys_with_ts else ("", "", "")
            telemetry_market = self._market.get(key, {})
            telemetry_depth = self._depth.get(key, {})
            fills = list(self._fills.get(key, deque()))
            events = list(self._paper_events.get(key, deque()))
            connector_name = str(telemetry_market.get("connector_name") or telemetry_depth.get("connector_name") or "").strip()
            if not connector_name and requested_pair_norm:
                pair_matches = [k for k in self._market_quote.keys() if requested_pair_norm == _normalize_pair(k[1])]
                if pair_matches:
                    freshest_pair_key = max(pair_matches, key=lambda pair_key: int(self._market_quote_ts_ms.get(pair_key, 0) or 0))
                    connector_name = str(freshest_pair_key[0] or "").strip()
            market = telemetry_market
            depth = telemetry_depth
            if connector_name:
                market_pair_matches = [
                    k for k in self._market_quote.keys()
                    if k[0] == connector_name and (not requested_pair_norm or requested_pair_norm == _normalize_pair(k[1]))
                ]
                if market_pair_matches:
                    freshest_market_pair_key = max(
                        market_pair_matches, key=lambda pair_key: int(self._market_quote_ts_ms.get(pair_key, 0) or 0)
                    )
                    market = self._market_quote.get(freshest_market_pair_key, {}) or telemetry_market
                depth_pair_matches = [
                    k for k in self._market_depth.keys()
                    if k[0] == connector_name and (not requested_pair_norm or requested_pair_norm == _normalize_pair(k[1]))
                ]
                if depth_pair_matches:
                    freshest_depth_pair_key = max(
                        depth_pair_matches, key=lambda pair_key: int(self._market_depth_ts_ms.get(pair_key, 0) or 0)
                    )
                    depth = self._market_depth.get(freshest_depth_pair_key, {}) or telemetry_depth
        return {
            "key": {"instance_name": key[0], "controller_id": key[1], "trading_pair": key[2]},
            "connector_name": connector_name,
            "market": market,
            "bot_market": telemetry_market,
            "depth": depth,
            "fills": fills,
            "fills_total": len(fills),
            "paper_events": events,
        }

    def get_candles(
        self,
        instance_name: str = "",
        controller_id: str = "",
        trading_pair: str = "",
        timeframe_s: int = 60,
        limit: int = 300,
    ) -> List[Dict[str, Any]]:
        timeframe_ms = max(1, int(timeframe_s)) * 1000
        requested_pair_norm = _normalize_pair(trading_pair)

        def _match(key: Tuple[str, str, str]) -> bool:
            i, c, p = key
            return (
                (not instance_name or instance_name == i)
                and (not controller_id or controller_id == c)
                and (not requested_pair_norm or requested_pair_norm == _normalize_pair(p))
            )

        connector_name = self.resolve_connector_name(instance_name, controller_id, trading_pair)
        with self._lock:
            pair_points = []
            if connector_name:
                pair_matches = [
                    k for k in self._market_history.keys()
                    if k[0] == connector_name and (not requested_pair_norm or requested_pair_norm == _normalize_pair(k[1]))
                ]
                if pair_matches:
                    pair_points = list(self._market_history.get(pair_matches[-1], deque()))
            if pair_points:
                return _candles_from_points(pair_points, timeframe_s=timeframe_s, limit=limit)
            keys = [k for k in self._history.keys() if _match(k)]
            if not keys:
                return []
            points = list(self._history[keys[-1]])
        return _candles_from_points(points, timeframe_s=timeframe_s, limit=limit)

    def metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "market_keys": len(self._market),
                "depth_keys": len(self._depth),
                "market_quote_keys": len(self._market_quote),
                "market_depth_keys": len(self._market_depth),
                "fills_keys": len(self._fills),
                "paper_event_keys": len(self._paper_events),
                "subscribers": len(self._subscribers),
            }


def _build_instance_status_rows(
    realtime_state: RealtimeState,
    snapshot_fallback: "DeskSnapshotFallback",
    stream_stale_ms: int,
) -> List[Dict[str, Any]]:
    stream_instances = realtime_state.instance_names()
    artifact_instances = snapshot_fallback.available_instances()
    merged_instances = sorted({*stream_instances, *artifact_instances}, key=lambda value: value.lower())
    rows: List[Dict[str, Any]] = []
    stale_threshold_ms = max(1000, int(stream_stale_ms or 0))
    for instance_name in merged_instances:
        stream_state = realtime_state.get_state(instance_name, "", "")
        key = stream_state.get("key", {}) if isinstance(stream_state.get("key"), dict) else {}
        snapshot = snapshot_fallback.get_snapshot(instance_name)
        minute = snapshot.get("minute", {}) if isinstance(snapshot.get("minute"), dict) else {}
        metadata = snapshot_fallback.instance_metadata(instance_name)
        account_summary = snapshot_fallback.account_summary(instance_name) if instance_name in artifact_instances else _account_summary_template()
        stream_age_ms = realtime_state.selected_stream_age_ms(instance_name, "", "")
        has_stream = instance_name in stream_instances
        has_artifacts = instance_name in artifact_instances
        source_parts: List[str] = []
        if has_stream:
            source_parts.append("stream")
        if has_artifacts:
            source_parts.append("artifacts")
        controller_id = str(key.get("controller_id") or minute.get("controller_id") or metadata.get("controller_id") or "").strip()
        trading_pair = str(
            key.get("trading_pair")
            or (stream_state.get("market", {}) if isinstance(stream_state.get("market"), dict) else {}).get("trading_pair")
            or (stream_state.get("depth", {}) if isinstance(stream_state.get("depth"), dict) else {}).get("trading_pair")
            or minute.get("trading_pair")
            or metadata.get("trading_pair")
            or ""
        ).strip()
        snapshot_ts = str(snapshot.get("source_ts") or minute.get("ts") or account_summary.get("snapshot_ts") or "").strip()
        freshness = "offline"
        tone = "neutral"
        if has_stream and stream_age_ms is not None:
            freshness = "live" if int(stream_age_ms) <= stale_threshold_ms else "stale"
            tone = "ok" if freshness == "live" else "warn"
        elif has_artifacts:
            freshness = "artifact"
            tone = "neutral"
        rows.append(
            {
                "instance_name": instance_name,
                "label": str(metadata.get("label") or instance_name),
                "sources": source_parts,
                "source_label": "+".join(source_parts) if source_parts else "unknown",
                "has_stream": has_stream,
                "has_artifacts": has_artifacts,
                "stream_age_ms": int(stream_age_ms) if stream_age_ms is not None else None,
                "freshness": freshness,
                "tone": tone,
                "controller_id": controller_id,
                "trading_pair": trading_pair,
                "snapshot_ts": snapshot_ts,
                "quoting_status": str(account_summary.get("quoting_status") or "").strip(),
                "quoting_reason": str(account_summary.get("quoting_reason") or "").strip(),
                "orders_active": int(_to_float(account_summary.get("orders_active")) or 0),
                "equity_quote": float(_to_float(account_summary.get("equity_quote")) or 0.0),
                "equity_open_quote": float(_to_float(account_summary.get("equity_open_quote")) or 0.0),
                "equity_peak_quote": float(_to_float(account_summary.get("equity_peak_quote")) or 0.0),
                "realized_pnl_quote": float(_to_float(account_summary.get("realized_pnl_quote")) or 0.0),
                "equity_delta_open_quote": float(
                    (float(_to_float(account_summary.get("equity_quote")) or 0.0) - float(_to_float(account_summary.get("equity_open_quote")) or 0.0))
                    if float(_to_float(account_summary.get("equity_open_quote")) or 0.0) != 0.0
                    else 0.0
                ),
            }
        )
    return rows


class StreamWorker:
    def __init__(self, cfg: RealtimeApiConfig, state: RealtimeState):
        self._cfg = cfg
        self._state = state
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._client = RedisStreamClient(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD", "") or None,
            enabled=os.getenv("EXT_SIGNAL_RISK_ENABLED", "true").strip().lower() in {"1", "true", "yes"},
        )
        self._streams = [
            MARKET_DATA_STREAM,
            MARKET_QUOTE_STREAM,
            MARKET_DEPTH_STREAM,
            BOT_TELEMETRY_STREAM,
            PAPER_EXCHANGE_EVENT_STREAM,
        ]

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="realtime-ui-api-stream-worker")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    @property
    def redis_available(self) -> bool:
        return self._client.enabled and self._client.ping()

    def _run(self) -> None:
        if not self._client.enabled:
            logger.warning("realtime_ui_api stream worker started with Redis disabled; fallback mode only.")
            return
        for stream in self._streams:
            self._client.create_group(stream, self._cfg.consumer_group or DEFAULT_CONSUMER_GROUP)
        while not self._stop.is_set():
            processed = 0
            for stream in self._streams:
                entries = self._client.read_group(
                    stream=stream,
                    group=self._cfg.consumer_group or DEFAULT_CONSUMER_GROUP,
                    consumer=self._cfg.consumer_name or "realtime-ui-api-1",
                    count=200,
                    block_ms=max(1, self._cfg.poll_ms),
                )
                for entry_id, payload in entries:
                    if not isinstance(payload, dict):
                        continue
                    self._state.process(stream=stream, entry_id=entry_id, payload=payload)
                    self._client.ack(stream, self._cfg.consumer_group or DEFAULT_CONSUMER_GROUP, entry_id)
                    processed += 1
            if processed == 0:
                time.sleep(0.05)


def _response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any], cors_origin: str) -> None:
    body = _safe_json(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", cors_origin)
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler: BaseHTTPRequestHandler, status: int, body: str, cors_origin: str, content_type: str) -> None:
    raw = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Access-Control-Allow-Origin", cors_origin)
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def _ws_accept_key(client_key: str) -> str:
    magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    digest = hashlib.sha1((client_key + magic).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def _ws_send_text(handler: BaseHTTPRequestHandler, text: str) -> None:
    payload = text.encode("utf-8")
    header = bytearray()
    header.append(0x81)  # FIN + text frame
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length <= 0xFFFF:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    handler.wfile.write(bytes(header) + payload)
    handler.wfile.flush()


def make_handler(
    cfg: RealtimeApiConfig,
    state: RealtimeState,
    worker: StreamWorker,
    fallback: DeskSnapshotFallback,
    db_reader: OpsDbReadModel,
):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RealtimeUiApi/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover
            logger.info("%s - %s", self.address_string(), fmt % args)

        def _request_origin(self) -> str:
            return str(self.headers.get("Origin", "")).strip()

        def _cors_origin(self) -> str:
            request_origin = self._request_origin()
            allowed = {item.strip() for item in cfg.allowed_origins.split(",") if item.strip()}
            if allowed:
                return request_origin if request_origin in allowed else "null"
            return cfg.cors_allow_origin

        def _is_authorized(self, query_token: str = "") -> bool:
            if not cfg.auth_enabled:
                return True
            expected = cfg.auth_token.strip()
            if not expected:
                return False
            auth = str(self.headers.get("Authorization", "")).strip()
            if auth == f"Bearer {expected}":
                return True
            token = str(query_token or "").strip()
            return bool(cfg.allow_query_token and token and token == expected)

        def _needs_fallback(self, instance_name: str, controller_id: str, trading_pair: str) -> bool:
            age = state.selected_stream_age_ms(instance_name, controller_id, trading_pair)
            if age is None:
                return True
            return age > max(1000, cfg.stream_stale_ms)

        def _fallback_allowed(self) -> bool:
            return bool(cfg.fallback_enabled and cfg.degraded_mode_enabled)

        def _build_state_payload(self, instance_name: str, controller_id: str, trading_pair: str) -> Dict[str, Any]:
            stream_state = state.get_state(instance_name, controller_id, trading_pair)
            connector_name = state.resolve_connector_name(instance_name, controller_id, trading_pair)
            db_available = db_reader.available() if db_reader.enabled else False
            allow_csv = bool(not cfg.csv_failover_only or not db_available)
            account_summary = fallback.account_summary(instance_name) if instance_name else _account_summary_template()
            fallback_state = (
                fallback.state_from_snapshot(
                    instance_name,
                    trading_pair,
                    max_fills=cfg.max_fallback_fills,
                    max_orders=cfg.max_fallback_orders,
                    include_csv_fills=allow_csv,
                    include_estimated_orders=True,
                )
                if (self._fallback_allowed() and instance_name)
                else {}
            )
            db_position = db_reader.get_position(instance_name, trading_pair) if db_available else {}
            db_fills = db_reader.get_fills(instance_name, trading_pair, limit=cfg.max_fallback_fills) if db_available else []
            db_fill_count = db_reader.get_fill_count(instance_name, trading_pair) if db_available else 0
            db_fill_activity = db_reader.get_fill_activity(instance_name, trading_pair) if db_available else {}
            db_open_orders = db_reader.get_open_orders(instance_name, trading_pair, limit=cfg.max_fallback_orders) if db_available else []
            stream_fills = stream_state.get("fills", []) if isinstance(stream_state.get("fills"), list) else []
            if not stream_fills:
                stream_state["fills"] = db_fills or fallback_state.get("fills", [])
            stream_state["fills_total"] = max(
                int(stream_state.get("fills_total", 0) or 0),
                len(stream_fills),
                len(db_fills),
                int(db_fill_count),
            )
            stream_state["position"] = db_position or fallback_state.get("position", {}) or stream_state.get("position", {})
            resolved_open_orders = list(db_open_orders) if isinstance(db_open_orders, list) else []
            if not resolved_open_orders and isinstance(fallback_state.get("open_orders"), list):
                resolved_open_orders = list(fallback_state.get("open_orders", []))
            if not resolved_open_orders:
                runtime_orders_active = int(_to_float(account_summary.get("orders_active")) or 0)
                stream_market = stream_state.get("market", {}) if isinstance(stream_state.get("market"), dict) else {}
                stream_depth = stream_state.get("depth", {}) if isinstance(stream_state.get("depth"), dict) else {}
                state_key = stream_state.get("key", {}) if isinstance(stream_state.get("key"), dict) else {}
                best_bid = _to_float(stream_market.get("best_bid"))
                if best_bid is None:
                    best_bid = _to_float(stream_depth.get("best_bid")) or _to_float(
                        ((stream_depth.get("bids") or [{}])[0] if isinstance(stream_depth.get("bids"), list) else {}).get("price")
                    )
                best_ask = _to_float(stream_market.get("best_ask"))
                if best_ask is None:
                    best_ask = _to_float(stream_depth.get("best_ask")) or _to_float(
                        ((stream_depth.get("asks") or [{}])[0] if isinstance(stream_depth.get("asks"), list) else {}).get("price")
                    )
                mid_price = _to_float(stream_market.get("mid_price")) or _depth_mid(stream_depth)
                runtime_position = stream_state.get("position", {}) if isinstance(stream_state.get("position"), dict) else {}
                runtime_qty = _to_float(runtime_position.get("quantity"))
                resolved_trading_pair = str(
                    trading_pair
                    or state_key.get("trading_pair")
                    or stream_market.get("trading_pair")
                    or stream_depth.get("trading_pair")
                    or runtime_position.get("trading_pair")
                    or ""
                ).strip()
                runtime_order_ts_ms = int(
                    _to_epoch_ms(
                        stream_market.get("ts")
                        or stream_market.get("timestamp_ms")
                        or stream_depth.get("ts")
                        or stream_depth.get("timestamp_ms")
                    )
                    or _now_ms()
                )
                if runtime_orders_active > 0:
                    resolved_open_orders = _build_runtime_open_order_placeholders(
                        orders_active=runtime_orders_active,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        mid_price=mid_price,
                        quantity=runtime_qty,
                        trading_pair=resolved_trading_pair,
                        timestamp_ms=runtime_order_ts_ms,
                        source_label="runtime",
                    )
            stream_state["open_orders"] = resolved_open_orders
            if fallback_state:
                fallback_state["position"] = db_position or fallback_state.get("position", {})
                fallback_state["fills"] = db_fills or fallback_state.get("fills", [])
                fallback_state["open_orders"] = list(resolved_open_orders)
                fallback_state["fills_total"] = max(
                    int(fallback_state.get("fills_total", 0) or 0),
                    len(fallback_state.get("fills", [])) if isinstance(fallback_state.get("fills"), list) else 0,
                    int(db_fill_count),
                )
            selected_stream_age_ms = state.selected_stream_age_ms(instance_name, controller_id, trading_pair)
            fallback_active = bool(self._fallback_allowed() and self._needs_fallback(instance_name, controller_id, trading_pair))
            summary_fills = db_fills
            if not summary_fills and isinstance(stream_state.get("fills"), list):
                summary_fills = stream_state.get("fills", [])
            if not summary_fills and isinstance(fallback_state.get("fills"), list):
                summary_fills = fallback_state.get("fills", [])
            activity = db_fill_activity or _summarize_fill_activity(
                list(summary_fills) if isinstance(summary_fills, list) else [],
                fills_total=max(
                    int(stream_state.get("fills_total", 0) or 0),
                    int(fallback_state.get("fills_total", 0) or 0),
                    int(db_fill_count),
                ),
            )
            account_summary["realized_pnl_quote"] = float(_to_float(activity.get("realized_pnl_total_quote")) or 0.0)
            latest_market_ts_ms = int(
                _to_epoch_ms(
                    (stream_state.get("market", {}) if isinstance(stream_state.get("market"), dict) else {}).get("ts")
                    or (stream_state.get("market", {}) if isinstance(stream_state.get("market"), dict) else {}).get("timestamp_ms")
                    or (stream_state.get("depth", {}) if isinstance(stream_state.get("depth"), dict) else {}).get("ts")
                    or (stream_state.get("depth", {}) if isinstance(stream_state.get("depth"), dict) else {}).get("timestamp_ms")
                )
                or 0
            )
            position_source_ts_ms = int(
                _to_epoch_ms(
                    (db_position if isinstance(db_position, dict) else {}).get("source_ts_ms")
                    or (fallback_state.get("position", {}) if isinstance(fallback_state.get("position"), dict) else {}).get("source_ts_ms")
                )
                or 0
            )
            stream_age_ms = selected_stream_age_ms
            state_metrics = state.metrics()
            system = {
                "redis_available": bool(worker.redis_available),
                "db_available": bool(db_available),
                "fallback_active": fallback_active,
                "stream_age_ms": int(stream_age_ms) if stream_age_ms is not None else None,
                "latest_market_ts_ms": latest_market_ts_ms,
                "latest_fill_ts_ms": int(activity.get("latest_fill_ts_ms") or 0),
                "position_source_ts_ms": position_source_ts_ms,
                "subscriber_count": int(state_metrics.get("subscribers", 0) or 0),
                "market_key_count": int(state_metrics.get("market_quote_keys", 0) or 0),
                "depth_key_count": int(state_metrics.get("market_depth_keys", 0) or 0),
                "fills_key_count": int(state_metrics.get("fills_keys", 0) or 0),
                "paper_event_key_count": int(state_metrics.get("paper_event_keys", 0) or 0),
            }
            alerts = _build_alerts(account_summary, system)
            source_parts: List[str] = []
            if stream_state.get("market") or stream_state.get("depth") or stream_state.get("fills"):
                source_parts.append("stream")
            if db_position or db_fills or db_open_orders:
                source_parts.append("db")
            if fallback_state:
                source_parts.append("degraded_snapshot")
            source = "+".join(dict.fromkeys(source_parts)) if source_parts else "stream"
            if fallback_active and fallback_state and source == "degraded_snapshot":
                source = "degraded_mode"
            return {
                "mode": cfg.normalized_mode(),
                "source": source,
                "fallback_active": fallback_active,
                "data_sources": {
                    "stream": True,
                    "db": db_available,
                    "connector_name": connector_name,
                    "csv_failover_used": bool(allow_csv and fallback_state.get("fills")),
                },
                "summary": {
                    "activity": activity,
                    "account": account_summary,
                    "system": system,
                    "alerts": alerts,
                },
                "stream": stream_state,
                "fallback": fallback_state,
            }

        def _build_instances_payload(self) -> Dict[str, Any]:
            stream_instances = state.instance_names()
            artifact_instances = fallback.available_instances()
            merged = sorted({*stream_instances, *artifact_instances}, key=lambda value: value.lower())
            statuses = _build_instance_status_rows(state, fallback, cfg.stream_stale_ms)
            return {
                "instances": merged,
                "statuses": statuses,
                "sources": {
                    "stream": stream_instances,
                    "artifacts": artifact_instances,
                },
            }

        def _build_daily_review_payload(self, instance_name: str, trading_pair: str, day_key: str) -> Dict[str, Any]:
            if not instance_name:
                return {"status": "error", "reason": "instance_name_required"}
            snapshot = fallback.get_snapshot(instance_name)
            minute = snapshot.get("minute", {}) if isinstance(snapshot.get("minute"), dict) else {}
            daily_state = snapshot.get("daily_state", {}) if isinstance(snapshot.get("daily_state"), dict) else {}
            snapshot_day = str(daily_state.get("day_key") or "") or str(snapshot.get("source_ts", "") or "")[:10]
            resolved_pair = trading_pair or str(minute.get("trading_pair", "") or "")
            resolved_day, _, _ = _day_bounds_utc(day_key or snapshot_day)
            account_summary = fallback.account_summary(instance_name)
            minute_rows = fallback.minute_rows_from_csv(instance_name, resolved_pair, resolved_day)
            db_available = db_reader.available() if db_reader.enabled else False
            fills = db_reader.get_fills_for_day(instance_name, resolved_pair, resolved_day) if db_available else []
            source_parts: List[str] = []
            if fills:
                source_parts.append("db_fills")
            if not fills:
                fills = fallback.fills_from_csv_for_day(instance_name, resolved_pair, resolved_day)
                if fills:
                    source_parts.append("fills_csv")
            if minute_rows:
                source_parts.append("minute_log")
            if not source_parts and snapshot:
                source_parts.append("desk_snapshot")
            review = _summarize_daily_review(resolved_day, minute_rows, fills, account_summary)
            review["instance_name"] = instance_name
            review["trading_pair"] = resolved_pair
            return {
                "mode": cfg.normalized_mode(),
                "source": "+".join(source_parts) if source_parts else "unavailable",
                "review": review,
            }

        def _build_weekly_review_payload(self, instance_name: str) -> Dict[str, Any]:
            if not instance_name:
                return {"status": "error", "reason": "instance_name_required"}
            report = fallback.weekly_strategy_report(instance_name)
            if not report:
                return {
                    "mode": cfg.normalized_mode(),
                    "source": "unavailable",
                    "review": {
                        **_weekly_review_template(),
                        "narrative": f"No weekly report artifact available for {instance_name}.",
                    },
                }
            review = _summarize_weekly_report(instance_name, report)
            return {
                "mode": cfg.normalized_mode(),
                "source": "strategy_multi_day_report",
                "review": review,
            }

        def _build_journal_review_payload(
            self,
            instance_name: str,
            trading_pair: str,
            start_day: str,
            end_day: str,
        ) -> Dict[str, Any]:
            if not instance_name:
                return {"status": "error", "reason": "instance_name_required"}
            snapshot = fallback.get_snapshot(instance_name)
            minute = snapshot.get("minute", {}) if isinstance(snapshot.get("minute"), dict) else {}
            resolved_pair = trading_pair or str(minute.get("trading_pair", "") or "")
            source_parts: List[str] = []
            fills = fallback.fills_from_csv_range(instance_name, resolved_pair, start_day, end_day, limit=12000)
            if fills:
                source_parts.append("fills_csv")
            if not fills:
                db_available = db_reader.available() if db_reader.enabled else False
                fills = db_reader.get_fills_range(instance_name, resolved_pair, start_day, end_day, limit=12000) if db_available else []
                if fills:
                    source_parts.append("db_fills")
            minute_rows = fallback.minute_rows_range(instance_name, resolved_pair, start_day, end_day, limit=20000)
            if minute_rows:
                source_parts.append("minute_log")
            trades = _reconstruct_closed_trades(fills)
            trades = _enrich_closed_trades_with_minute_context(trades, minute_rows)
            review = _summarize_journal_review(trades)
            review["instance_name"] = instance_name
            review["trading_pair"] = resolved_pair
            review["start_day"] = start_day
            review["end_day"] = end_day
            return {
                "mode": cfg.normalized_mode(),
                "source": "+".join(source_parts) if source_parts else "unavailable",
                "review": review,
            }

        def _build_candles_payload(
            self,
            instance_name: str,
            controller_id: str,
            trading_pair: str,
            timeframe_s: int,
            limit: int,
        ) -> Dict[str, Any]:
            connector_name = state.resolve_connector_name(instance_name, controller_id, trading_pair)
            db_available = db_reader.available() if db_reader.enabled else False
            allow_csv = bool(not cfg.csv_failover_only or not db_available)
            db_candles = db_reader.get_candles(connector_name, trading_pair, timeframe_s, limit) if db_available else []
            stream_candles = state.get_candles(instance_name, controller_id, trading_pair, timeframe_s, limit)
            candles = list(db_candles or stream_candles)
            source = "db" if db_candles else "stream"
            if stream_candles:
                merged_by_bucket = {int(c.get("bucket_ms", 0)): c for c in candles}
                merged_by_bucket.update({int(c.get("bucket_ms", 0)): c for c in stream_candles})
                candles = [merged_by_bucket[k] for k in sorted(merged_by_bucket.keys()) if k > 0]
                candles = candles[-max(1, int(limit)) :]
                if db_candles:
                    source = "db+stream"
            if connector_name and len(candles) < max(5, int(limit)):
                rest_candles = db_reader.get_rest_backfill_candles(connector_name, trading_pair, timeframe_s, limit)
                if rest_candles:
                    merged_by_bucket = {int(c.get("bucket_ms", 0)): c for c in rest_candles}
                    merged_by_bucket.update({int(c.get("bucket_ms", 0)): c for c in candles})
                    candles = [merged_by_bucket[k] for k in sorted(merged_by_bucket.keys()) if k > 0]
                    candles = candles[-max(1, int(limit)) :]
                    source = f"{source}+rest_backfill" if source else "rest_backfill"
            if self._fallback_allowed() and instance_name and len(candles) < max(5, int(limit)) and allow_csv:
                fallback_candles = fallback.candles_from_minute_log(instance_name, trading_pair, timeframe_s, limit)
                if fallback_candles:
                    merged_by_bucket = {int(c.get("bucket_ms", 0)): c for c in fallback_candles}
                    merged_by_bucket.update({int(c.get("bucket_ms", 0)): c for c in candles})
                    candles = [merged_by_bucket[k] for k in sorted(merged_by_bucket.keys()) if k > 0]
                    candles = candles[-max(1, int(limit)) :]
                    source = f"{source}+minute_log" if source else "minute_log"
            return {
                "mode": cfg.normalized_mode(),
                "source": source,
                "db_available": db_available,
                "csv_failover_used": bool(allow_csv and source.endswith("minute_log")),
                "candles": candles,
            }

        def _stream_key_matches(
            self,
            event_key: Any,
            instance_name: str,
            controller_id: str,
            trading_pair: str,
        ) -> bool:
            if not isinstance(event_key, (list, tuple)) or len(event_key) < 3:
                return True
            ev_instance = str(event_key[0] or "").strip()
            ev_controller = str(event_key[1] or "").strip()
            ev_pair = str(event_key[2] or "").strip()
            if instance_name and ev_instance and instance_name != ev_instance:
                return False
            if controller_id and ev_controller and controller_id != ev_controller:
                return False
            if trading_pair and _normalize_pair(trading_pair) != _normalize_pair(ev_pair):
                return False
            return True

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self._cors_origin())
            self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET,OPTIONS")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            params = parse_qs(parsed.query, keep_blank_values=False)
            query_token = str(params.get("token", [""])[0]).strip()

            if path == "/health":
                age = state.newest_stream_age_ms()
                db_available = db_reader.available() if db_reader.enabled else False
                _response(
                    self,
                    200,
                    {
                        "status": "ok" if cfg.normalized_mode() != "disabled" else "disabled",
                        "mode": cfg.normalized_mode(),
                        "redis_available": worker.redis_available,
                        "db_enabled": bool(cfg.db_enabled),
                        "db_available": db_available,
                        "stream_age_ms": age,
                        "fallback_active": bool(self._fallback_allowed() and self._needs_fallback()),
                        "metrics": state.metrics(),
                    },
                    self._cors_origin(),
                )
                return

            if not self._is_authorized(query_token):
                _response(self, 401, {"status": "unauthorized"}, self._cors_origin())
                return

            if cfg.normalized_mode() == "disabled":
                _response(
                    self,
                    503,
                    {"status": "disabled", "reason": "REALTIME_UI_API_MODE=disabled"},
                    self._cors_origin(),
                )
                return

            instance_name = str(params.get("instance_name", [""])[0]).strip()
            controller_id = str(params.get("controller_id", [""])[0]).strip()
            trading_pair = str(params.get("trading_pair", [""])[0]).strip()

            if path == "/metrics":
                metrics = state.metrics()
                lines = [
                    "# HELP realtime_ui_api_market_keys market states",
                    "# TYPE realtime_ui_api_market_keys gauge",
                    f"realtime_ui_api_market_keys {metrics.get('market_keys', 0)}",
                    "# HELP realtime_ui_api_market_quote_keys market quote states",
                    "# TYPE realtime_ui_api_market_quote_keys gauge",
                    f"realtime_ui_api_market_quote_keys {metrics.get('market_quote_keys', 0)}",
                    "# HELP realtime_ui_api_depth_keys depth states",
                    "# TYPE realtime_ui_api_depth_keys gauge",
                    f"realtime_ui_api_depth_keys {metrics.get('depth_keys', 0)}",
                    "# HELP realtime_ui_api_subscribers active SSE subscribers",
                    "# TYPE realtime_ui_api_subscribers gauge",
                    f"realtime_ui_api_subscribers {metrics.get('subscribers', 0)}",
                ]
                _text_response(self, 200, "\n".join(lines) + "\n", self._cors_origin(), "text/plain; version=0.0.4")
                return

            if path == "/api/v1/state":
                payload = self._build_state_payload(instance_name, controller_id, trading_pair)
                _response(self, 200, payload, self._cors_origin())
                return

            if path == "/api/v1/instances":
                payload = self._build_instances_payload()
                _response(self, 200, payload, self._cors_origin())
                return

            if path == "/api/v1/candles":
                timeframe_s = int(params.get("timeframe_s", ["60"])[0] or "60")
                limit = int(params.get("limit", ["300"])[0] or "300")
                payload = self._build_candles_payload(instance_name, controller_id, trading_pair, timeframe_s, limit)
                _response(self, 200, payload, self._cors_origin())
                return

            if path == "/api/v1/depth":
                stream_state = state.get_state(instance_name, controller_id, trading_pair)
                depth = stream_state.get("depth", {})
                _response(
                    self,
                    200,
                    {"mode": cfg.normalized_mode(), "source": "stream", "depth": depth},
                    self._cors_origin(),
                )
                return

            if path == "/api/v1/positions":
                if not instance_name:
                    _response(self, 400, {"status": "error", "reason": "instance_name_required"}, self._cors_origin())
                    return
                db_available = db_reader.available() if db_reader.enabled else False
                fallback_state = {}
                used_degraded_snapshot = False
                if self._fallback_allowed():
                    fallback_state = fallback.state_from_snapshot(
                        instance_name,
                        trading_pair,
                        max_fills=cfg.max_fallback_fills,
                        max_orders=cfg.max_fallback_orders,
                        include_csv_fills=False,
                        include_estimated_orders=False,
                    )
                    used_degraded_snapshot = bool(fallback_state)
                if db_available:
                    fallback_state["position"] = db_reader.get_position(instance_name, trading_pair) or fallback_state.get("position", {})
                _response(
                    self,
                    200,
                    {
                        "mode": cfg.normalized_mode(),
                        "source": "db+degraded_snapshot" if db_available and used_degraded_snapshot else ("db" if db_available else "degraded_snapshot"),
                        **fallback_state,
                    },
                    self._cors_origin(),
                )
                return

            if path == "/api/v1/review/daily":
                if not instance_name:
                    _response(self, 400, {"status": "error", "reason": "instance_name_required"}, self._cors_origin())
                    return
                day_key = str(params.get("day", [""])[0]).strip()
                payload = self._build_daily_review_payload(instance_name, trading_pair, day_key)
                _response(self, 200, payload, self._cors_origin())
                return

            if path == "/api/v1/review/weekly":
                if not instance_name:
                    _response(self, 400, {"status": "error", "reason": "instance_name_required"}, self._cors_origin())
                    return
                payload = self._build_weekly_review_payload(instance_name)
                _response(self, 200, payload, self._cors_origin())
                return

            if path == "/api/v1/review/journal":
                if not instance_name:
                    _response(self, 400, {"status": "error", "reason": "instance_name_required"}, self._cors_origin())
                    return
                start_day = str(params.get("start_day", [""])[0]).strip()
                end_day = str(params.get("end_day", [""])[0]).strip()
                payload = self._build_journal_review_payload(instance_name, trading_pair, start_day, end_day)
                _response(self, 200, payload, self._cors_origin())
                return

            if path == "/api/v1/ws":
                ws_key = str(self.headers.get("Sec-WebSocket-Key", "")).strip()
                ws_upgrade = str(self.headers.get("Upgrade", "")).strip().lower()
                if not ws_key or ws_upgrade != "websocket":
                    _response(self, 400, {"status": "error", "reason": "websocket_upgrade_required"}, self._cors_origin())
                    return
                timeframe_s = int(params.get("timeframe_s", ["60"])[0] or "60")
                candle_limit = int(params.get("limit", ["300"])[0] or "300")
                q = state.register_subscriber()
                try:
                    self.send_response(101, "Switching Protocols")
                    self.send_header("Upgrade", "websocket")
                    self.send_header("Connection", "Upgrade")
                    self.send_header("Sec-WebSocket-Accept", _ws_accept_key(ws_key))
                    self.end_headers()

                    snapshot_msg = {
                        "type": "snapshot",
                        "ts_ms": _now_ms(),
                        "state": self._build_state_payload(instance_name, controller_id, trading_pair),
                        "candles": self._build_candles_payload(
                            instance_name, controller_id, trading_pair, timeframe_s, candle_limit
                        ).get("candles", []),
                    }
                    _ws_send_text(self, _safe_json(snapshot_msg))

                    last_snapshot_ms = _now_ms()
                    while True:
                        try:
                            raw = q.get(timeout=5.0)
                            evt = json.loads(raw) if isinstance(raw, str) else {}
                            event_key = evt.get("key")
                            if not self._stream_key_matches(event_key, instance_name, controller_id, trading_pair):
                                continue
                            _ws_send_text(self, _safe_json({"type": "event", **evt}))
                        except queue.Empty:
                            _ws_send_text(self, _safe_json({"type": "keepalive", "ts_ms": _now_ms()}))
                        now_ms = _now_ms()
                        if now_ms - last_snapshot_ms >= 10_000:
                            periodic_msg = {
                                "type": "snapshot",
                                "ts_ms": now_ms,
                                "state": self._build_state_payload(instance_name, controller_id, trading_pair),
                                "candles": self._build_candles_payload(
                                    instance_name, controller_id, trading_pair, timeframe_s, candle_limit
                                ).get("candles", []),
                            }
                            _ws_send_text(self, _safe_json(periodic_msg))
                            last_snapshot_ms = now_ms
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
                finally:
                    state.unregister_subscriber(q)
                return

            if path == "/api/v1/stream":
                if not cfg.sse_enabled:
                    _response(self, 404, {"status": "not_found", "path": path}, self._cors_origin())
                    return
                q = state.register_subscriber()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.send_header("Access-Control-Allow-Origin", self._cors_origin())
                    self.end_headers()
                    self.wfile.write(b"event: ready\ndata: {\"status\":\"ok\"}\n\n")
                    self.wfile.flush()
                    while True:
                        try:
                            payload = q.get(timeout=15.0)
                            self.wfile.write(f"event: update\ndata: {payload}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                finally:
                    state.unregister_subscriber(q)
                return

            _response(self, 404, {"status": "not_found", "path": path}, self._cors_origin())

    return Handler


def run() -> None:
    cfg = RealtimeApiConfig()
    _validate_runtime_config(cfg)
    state = RealtimeState(cfg)
    worker = StreamWorker(cfg, state)
    fallback = DeskSnapshotFallback(cfg.fallback_root, cfg.data_root)
    db_reader = OpsDbReadModel(cfg)
    worker.start()

    handler_cls = make_handler(cfg, state, worker, fallback, db_reader)
    server = ThreadingHTTPServer((cfg.bind_host, cfg.port), handler_cls)
    logger.info(
        "realtime_ui_api starting host=%s port=%s mode=%s fallback_enabled=%s degraded_mode_enabled=%s",
        cfg.bind_host,
        cfg.port,
        cfg.normalized_mode(),
        cfg.fallback_enabled,
        cfg.degraded_mode_enabled,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        logger.info("realtime_ui_api stopping (keyboard interrupt)")
    finally:
        worker.stop()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream-first realtime UI API with fallback to desk snapshots.")
    parser.add_argument("--once", action="store_true", help="Unused compatibility flag; kept for service symmetry.")
    _ = parser.parse_args()
    run()


if __name__ == "__main__":
    main()
