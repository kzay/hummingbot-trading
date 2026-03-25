from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import queue
import time
from datetime import UTC, datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Optional

import orjson

from platform_lib.logging.logging_config import configure_logging
from platform_lib.market_data.market_history_provider_impl import MarketHistoryProviderImpl, market_bars_to_candles
from platform_lib.market_data.market_history_types import MarketBarKey
from services.realtime_ui_api._helpers import (
    RealtimeApiConfig,
    _account_summary_template,
    _build_alerts,
    _build_bot_gates,
    _build_gate_timeline,
    _build_quote_gate_summary,
    _build_runtime_open_order_placeholders,
    _build_trade_fill_contribution,
    _candle_dicts_to_market_bars,
    _candles_from_points,
    _compare_candle_sets,
    _daily_review_template,
    _day_bounds_utc,
    _depth_mid,
    _enrich_closed_trades_with_minute_context,
    _history_quality_from_candles,
    _infer_trade_exit_reason,
    _is_loopback_host,
    _journal_review_template,
    _merge_activity_window,
    _merge_fill_activity,
    _nearest_context_row,
    _normalize_fill_activity_row,
    _normalize_pair,
    _now_ms,
    _read_paper_exchange_active_orders,
    _reconstruct_closed_trades,
    _resolve_realized_pnl,
    _sample_trade_path_from_fills,
    _sample_trade_path_points,
    _sanitize_path_param,
    _split_risk_reasons,
    _state_key,
    _stream_ms,
    _summarize_daily_review,
    _summarize_fill_activity,
    _summarize_journal_review,
    _summarize_weekly_report,
    _sync_account_summary_with_open_orders,
    _to_bool,
    _to_epoch_ms,
    _to_float,
    _validate_runtime_config,
    _weekly_review_template,
    _window_summary_template,
)
from services.realtime_ui_api.fallback_readers import (
    DeskSnapshotFallback,
    OpsDbReadModel,
)
from services.realtime_ui_api.state import RealtimeState
from services.realtime_ui_api.stream_consumer import StreamWorker

configure_logging()
logger = logging.getLogger(__name__)


def _operator_api_csv_fallback_allowed(cfg: RealtimeApiConfig, db_available: bool) -> bool:
    """Allow reads from minute.csv / fills.csv only when explicitly enabled (debug / backup).

    When ``use_csv_for_operator_api`` is true, ``csv_failover_only`` still applies: with
    failover on, CSV supplements only if the DB path is unavailable.
    """
    if not cfg.use_csv_for_operator_api:
        return False
    return bool(not cfg.csv_failover_only or not db_available)


# ---------------------------------------------------------------------------
# orjson helpers — 3-10x faster than stdlib json.dumps
# ---------------------------------------------------------------------------

def _json_bytes(payload: Any) -> bytes:
    """Serialize *payload* to UTF-8 JSON bytes via orjson."""
    return orjson.dumps(payload, option=orjson.OPT_NON_STR_KEYS)


def _json_str(payload: Any) -> str:
    """Serialize *payload* to a JSON string via orjson."""
    return _json_bytes(payload).decode("utf-8")


# Keep _safe_json available for callers that import it from this module.
_safe_json = _json_str


# ---------------------------------------------------------------------------
# Shared helpers (auth, fallback, stream key matching)
# ---------------------------------------------------------------------------

def _is_authorized(cfg: RealtimeApiConfig, request) -> bool:
    if not cfg.auth_enabled:
        return True
    expected = cfg.auth_token.strip()
    if not expected:
        return False
    auth = request.headers.get("authorization", "")
    if auth == f"Bearer {expected}":
        return True
    token = request.query_params.get("token", "").strip()
    return bool(cfg.allow_query_token and token and token == expected)


def _needs_fallback(cfg: RealtimeApiConfig, state: RealtimeState,
                    instance_name: str, controller_id: str, trading_pair: str) -> bool:
    age = state.selected_stream_age_ms(instance_name, controller_id, trading_pair)
    if age is None:
        return True
    return age > max(1000, cfg.stream_stale_ms)


def _fallback_allowed(cfg: RealtimeApiConfig) -> bool:
    return bool(cfg.fallback_enabled and cfg.degraded_mode_enabled)


def _cors_origin(cfg: RealtimeApiConfig, request) -> str:
    request_origin = request.headers.get("origin", "").strip()
    allowed = {item.strip() for item in cfg.allowed_origins.split(",") if item.strip()}
    if allowed:
        return request_origin if request_origin in allowed else "null"
    return cfg.cors_allow_origin


def _stream_key_matches(
    event_key: Any,
    instance_name: str,
    controller_id: str,
    trading_pair: str,
) -> bool:
    if isinstance(event_key, dict):
        ev_instance = str(event_key.get("instance_name", "") or "").strip()
        ev_controller = str(event_key.get("controller_id", "") or "").strip()
        ev_pair = str(event_key.get("trading_pair", "") or "").strip()
    elif isinstance(event_key, (list, tuple)) and len(event_key) >= 3:
        ev_instance = str(event_key[0] or "").strip()
        ev_controller = str(event_key[1] or "").strip()
        ev_pair = str(event_key[2] or "").strip()
    else:
        return True
    if instance_name and ev_instance and instance_name != ev_instance:
        return False
    if controller_id and ev_controller and controller_id != ev_controller:
        return False
    return not (trading_pair and _normalize_pair(trading_pair) != _normalize_pair(ev_pair))


# ---------------------------------------------------------------------------
# Health payload (unchanged logic, now standalone)
# ---------------------------------------------------------------------------

def _build_health_payload(
    cfg: RealtimeApiConfig,
    state: RealtimeState,
    worker: StreamWorker,
    fallback: DeskSnapshotFallback,
    db_reader: OpsDbReadModel,
) -> tuple[int, dict[str, Any]]:
    mode = cfg.normalized_mode()
    age = state.newest_stream_age_ms()
    db_available = db_reader.available() if db_reader.enabled else False
    fallback_allowed_flag = bool(cfg.fallback_enabled and cfg.degraded_mode_enabled)
    fallback_candidate = bool(fallback.available_instances())
    stale_threshold_ms = max(1000, int(cfg.stream_stale_ms or 0))
    fallback_active = bool(fallback_allowed_flag and fallback_candidate and (age is None or age > stale_threshold_ms))

    status = "ok"
    http_status = 200
    reasons: list[str] = []
    if mode == "disabled":
        status = "disabled"
        http_status = 503
        reasons.append("mode_disabled")
    if not worker.redis_available:
        status = "degraded"
        http_status = 503
        reasons.append("redis_unavailable")
    if mode != "disabled":
        if age is None:
            status = "degraded"
            http_status = 503
            reasons.append("no_stream_data")
        elif age > stale_threshold_ms:
            status = "degraded"
            http_status = 503
            reasons.append(f"stream_stale_{age}ms")
    if fallback_active:
        http_status = 503
        reasons.append("fallback_active")
    return http_status, {
        "status": status,
        "mode": mode,
        "redis_available": worker.redis_available,
        "db_enabled": db_reader.enabled,
        "db_available": db_available,
        "stream_age_ms": int(age) if age is not None else None,
        "stream_stale_threshold_ms": stale_threshold_ms,
        "fallback_active": fallback_active,
        "degraded_reasons": reasons,
        "metrics": state.metrics(),
    }


# ---------------------------------------------------------------------------
# Instance status rows
# ---------------------------------------------------------------------------

def _build_instance_status_rows(
    realtime_state: RealtimeState,
    snapshot_fallback: DeskSnapshotFallback,
    stream_stale_ms: int,
) -> list[dict[str, Any]]:
    stream_instances = realtime_state.instance_names()
    artifact_instances = snapshot_fallback.available_instances()
    merged_instances = sorted({*stream_instances, *artifact_instances}, key=lambda value: value.lower())
    rows: list[dict[str, Any]] = []
    stale_threshold_ms = max(1000, int(stream_stale_ms or 0))
    for instance_name in merged_instances:
        stream_state = realtime_state.get_state(instance_name, "", "")
        key = stream_state.get("key", {}) if isinstance(stream_state.get("key"), dict) else {}
        snapshot = snapshot_fallback.get_snapshot(instance_name)
        minute = snapshot.get("minute", {}) if isinstance(snapshot.get("minute"), dict) else {}
        metadata = snapshot_fallback.instance_metadata(instance_name)
        account_summary = snapshot_fallback.account_summary(instance_name) if instance_name in artifact_instances else _account_summary_template()
        _live = realtime_state.get_bot_snapshot(instance_name)
        if _live:
            _live_pos = _live.get("position") if isinstance(_live.get("position"), dict) else {}
            for _lk in ("equity_quote", "quote_balance", "realized_pnl_quote", "controller_state", "regime"):
                _lv = _live.get(_lk)
                if _lv is not None:
                    account_summary[_lk] = float(_lv) if _lk.endswith("_quote") else str(_lv)
            if isinstance(_live_pos, dict) and _live_pos:
                account_summary["position_base"] = float(_to_float(_live_pos.get("quantity")) or 0.0)
        _resolved_pair = str(
            key.get("trading_pair")
            or minute.get("trading_pair", "")
            or metadata.get("trading_pair", "")
            or ""
        ).strip()
        stream_age_ms = realtime_state.selected_stream_age_ms(instance_name, trading_pair=_resolved_pair)
        stream_fresh = stream_age_ms is not None and stream_age_ms <= stale_threshold_ms
        # Derive freshness label expected by frontend
        if stream_fresh:
            freshness = "live"
        elif stream_age_ms is not None:
            freshness = "stale"
        elif bool(snapshot) or instance_name in artifact_instances:
            freshness = "artifact"
        else:
            freshness = "offline"
        # Derive source_label
        source_parts: list[str] = []
        if stream_age_ms is not None:
            source_parts.append("stream")
        if bool(snapshot):
            source_parts.append("artifacts")
        source_label = "+".join(source_parts) or "none"
        # Compute equity_delta_open_quote
        eq = float(_to_float(account_summary.get("equity_quote")) or 0.0)
        eq_open = float(_to_float(account_summary.get("equity_open_quote")) or 0.0)
        equity_delta = eq - eq_open if eq and eq_open else 0.0
        # Count active orders from stream, fall back to artifact minute snapshot
        open_orders = stream_state.get("open_orders", []) if isinstance(stream_state.get("open_orders"), list) else []
        orders_active = len(open_orders) or int(_to_float(minute.get("orders_active")) or 0)
        # Flatten: merge account_summary fields at top level
        row: dict[str, Any] = {
            "instance_name": instance_name,
            "controller_id": key.get("controller_id") or str(metadata.get("controller_id", "") or ""),
            "trading_pair": key.get("trading_pair") or str(minute.get("trading_pair", "")) or str(metadata.get("trading_pair", "") or ""),
            "stream_fresh": stream_fresh,
            "stream_age_ms": int(stream_age_ms) if stream_age_ms is not None else None,
            "has_artifact": bool(snapshot),
            "metadata": metadata,
            "freshness": freshness,
            "source_label": source_label,
            "orders_active": orders_active,
            "equity_delta_open_quote": round(equity_delta, 6),
        }
        # Flatten account_summary fields onto the row
        for _ak in ("equity_quote", "quote_balance", "equity_open_quote", "equity_peak_quote",
                     "realized_pnl_quote", "unrealized_pnl_quote", "controller_state", "regime",
                     "quoting_status", "quoting_reason", "position_base"):
            _av = account_summary.get(_ak)
            if _av is not None:
                row[_ak] = _av
        # Keep nested account for backward compat
        row["account"] = account_summary
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Business logic — extracted from Handler class methods.
# All functions take explicit dependencies (no self).
# ---------------------------------------------------------------------------

def _build_state_payload(
    cfg: RealtimeApiConfig,
    state: RealtimeState,
    worker: StreamWorker,
    fallback: DeskSnapshotFallback,
    db_reader: OpsDbReadModel,
    instance_name: str,
    controller_id: str,
    trading_pair: str,
) -> dict[str, Any]:
    stream_state = state.get_state(instance_name, controller_id, trading_pair)
    connector_name = state.resolve_connector_name(instance_name, controller_id, trading_pair)
    db_available = bool(db_reader.enabled and db_reader._last_health_ok)
    allow_csv_fallback = _operator_api_csv_fallback_allowed(cfg, db_available)
    resolved_trading_pair = str(
        trading_pair
        or (stream_state.get("key", {}) if isinstance(stream_state.get("key"), dict) else {}).get("trading_pair")
        or (stream_state.get("market", {}) if isinstance(stream_state.get("market"), dict) else {}).get("trading_pair")
        or (stream_state.get("depth", {}) if isinstance(stream_state.get("depth"), dict) else {}).get("trading_pair")
        or ""
    ).strip()

    # Fallback: resolve trading pair from disk snapshot when stream is empty
    # (e.g. bot not running but artifacts exist).
    if not resolved_trading_pair and instance_name:
        _fb_snap = fallback.get_snapshot(instance_name)
        _fb_minute = _fb_snap.get("minute", {}) if isinstance(_fb_snap.get("minute"), dict) else {}
        resolved_trading_pair = str(_fb_minute.get("trading_pair", "")).strip()

    # If we resolved a pair but the stream lacks market data, pull shared
    # market data (instance_name="") so the UI gets live prices.
    if resolved_trading_pair and instance_name:
        _market_dict = stream_state.get("market", {}) if isinstance(stream_state.get("market"), dict) else {}
        _has_market = bool(_market_dict.get("mid_price") or _market_dict.get("last_trade_price"))
        if not _has_market:
            shared_state = state.get_state("", "", resolved_trading_pair)
            shared_market = shared_state.get("market", {}) if isinstance(shared_state.get("market"), dict) else {}
            if shared_market.get("mid_price") or shared_market.get("last_trade_price"):
                stream_state["market"] = dict(shared_market)
            shared_depth = shared_state.get("depth", {}) if isinstance(shared_state.get("depth"), dict) else {}
            if shared_depth and not (stream_state.get("depth", {}) if isinstance(stream_state.get("depth"), dict) else {}):
                stream_state["depth"] = dict(shared_depth)
            if not connector_name:
                connector_name = state.resolve_connector_name("", "", resolved_trading_pair)

    # Ensure stream_state.key reflects the resolved pair so the frontend
    # can bootstrap its activePair correctly.
    if resolved_trading_pair:
        _existing_key = stream_state.get("key", {}) if isinstance(stream_state.get("key"), dict) else {}
        if not _existing_key.get("trading_pair"):
            stream_state["key"] = {
                "instance_name": instance_name,
                "controller_id": controller_id,
                "trading_pair": resolved_trading_pair,
            }

    account_summary = fallback.account_summary(instance_name) if instance_name else _account_summary_template()
    live_snap = state.get_bot_snapshot(instance_name) if instance_name else None
    _snap_age_ms = (
        int(_now_ms()) - int(live_snap.get("source_ts_ms") or 0)
        if live_snap and live_snap.get("source_ts_ms")
        else None
    )
    _snap_fresh = live_snap is not None and (_snap_age_ms is None or _snap_age_ms < 300_000)
    if _snap_fresh and live_snap:
        live_pos = live_snap.get("position") if isinstance(live_snap.get("position"), dict) else {}
        _eq = _to_float(live_snap.get("equity_quote"))
        if _eq is not None:
            account_summary["equity_quote"] = float(_eq)
        _qb = _to_float(live_snap.get("quote_balance"))
        if _qb is not None:
            account_summary["quote_balance"] = float(_qb)
        _eo = _to_float(live_snap.get("equity_open_quote"))
        if _eo is not None:
            account_summary["equity_open_quote"] = float(_eo)
        _ep = _to_float(live_snap.get("equity_peak_quote"))
        if _ep is not None:
            account_summary["equity_peak_quote"] = float(_ep)
        _rp = _to_float(live_snap.get("realized_pnl_quote"))
        if _rp is not None:
            account_summary["realized_pnl_quote"] = float(_rp)
        for _sk in ("controller_state", "regime"):
            _sv = live_snap.get(_sk)
            if _sv is not None:
                account_summary[_sk] = str(_sv)
        _risk = live_snap.get("risk_reasons")
        if _risk is not None:
            parts = _split_risk_reasons(_risk)
            account_summary["risk_reasons"] = ",".join(parts) if isinstance(parts, list) else str(parts)
        for _bk in ("daily_loss_pct", "drawdown_pct", "max_daily_loss_pct_hard", "max_drawdown_pct_hard"):
            _bv = _to_float(live_snap.get(_bk))
            if _bv is not None:
                account_summary[_bk] = float(_bv)
        if live_snap.get("order_book_stale") is not None:
            account_summary["order_book_stale"] = _to_bool(live_snap.get("order_book_stale"))
        _fc = live_snap.get("fills_count_today")
        if _fc is not None:
            account_summary["fills_count_today"] = int(_fc)
        _snap_ts_ms = int(live_snap.get("source_ts_ms") or 0)
        if _snap_ts_ms > 0:
            account_summary["snapshot_ts"] = datetime.fromtimestamp(_snap_ts_ms / 1000, tz=UTC).isoformat()
        for _pgk in ("pnl_governor_active", "pnl_governor_reason"):
            _pgv = live_snap.get(_pgk)
            if _pgv is not None:
                account_summary[_pgk] = _to_bool(_pgv) if _pgk.endswith("_active") else str(_pgv)
        if isinstance(live_pos, dict) and live_pos:
            for _pk in ("quantity", "side", "avg_entry_price", "unrealized_pnl"):
                _pval = live_pos.get(_pk)
                if _pval is not None:
                    stream_state.setdefault("position", {})[_pk] = _pval
    # _build_quote_gate_summary expects a minute-like dict keyed "state" (not "controller_state").
    _gate_minute = dict(account_summary)
    _gate_minute.setdefault("state", _gate_minute.get("controller_state", ""))
    _strategy_type = str(live_snap.get("strategy_type", "")) if live_snap else None
    quote_gates = _build_quote_gate_summary(_gate_minute, strategy_type=_strategy_type or None)
    account_summary["quote_gates"] = quote_gates
    # Per-bot gate metrics from telemetry payload.
    _raw_bot_gates = (live_snap.get("bot_gates") or {}) if live_snap else {}
    account_summary["bot_gates"] = _build_bot_gates(_raw_bot_gates, _strategy_type)
    fallback_state = (
        fallback.state_from_snapshot(
            instance_name,
            resolved_trading_pair,
            max_fills=cfg.max_fallback_fills,
            max_orders=cfg.max_fallback_orders,
            include_csv_fills=allow_csv_fallback,
            include_estimated_orders=True,
        )
        if (_fallback_allowed(cfg) and instance_name)
        else {}
    )
    db_fills = (
        db_reader.get_fills(instance_name, resolved_trading_pair, limit=cfg.max_fallback_fills)
        if (db_available and instance_name)
        else []
    )
    db_fill_activity = (
        db_reader.get_fill_activity(instance_name, resolved_trading_pair)
        if (db_available and instance_name)
        else {}
    )
    raw_stream_fills = fallback.filter_fill_rows_for_instance(
        instance_name,
        stream_state.get("fills", []) if isinstance(stream_state.get("fills"), list) else [],
    )
    for _sf in raw_stream_fills:
        if isinstance(_sf, dict) and not _sf.get("timestamp_ms"):
            _ts = _to_epoch_ms(_sf.get("ts_utc") or _sf.get("ts"))
            if _ts:
                _sf["timestamp_ms"] = _ts
    stream_fills = raw_stream_fills
    paper_fills: list[dict[str, Any]] = []
    for pe in (stream_state.get("paper_events", []) if isinstance(stream_state.get("paper_events"), list) else []):
        if not isinstance(pe, dict) or str(pe.get("command", "")).strip() != "order_fill":
            continue
        meta = pe.get("metadata", {}) if isinstance(pe.get("metadata"), dict) else {}
        paper_fills.append({
            "order_id": pe.get("order_id") or meta.get("order_id", ""),
            "trading_pair": pe.get("trading_pair") or meta.get("trading_pair", ""),
            "instance_name": pe.get("instance_name", ""),
            "side": meta.get("side", ""),
            "price": meta.get("fill_price", 0),
            "amount_base": meta.get("fill_amount_base", 0),
            "amount": meta.get("fill_amount_base", 0),
            "notional_quote": meta.get("fill_notional_quote", 0),
            "fee_quote": meta.get("fill_fee_quote", 0),
            "realized_pnl_quote": meta.get("realized_pnl_quote", 0),
            "is_maker": meta.get("is_maker") in ("1", "true", True),
            "timestamp_ms": int(_to_epoch_ms(pe.get("ts") or pe.get("timestamp_ms")) or 0),
            "source": "paper_exchange",
        })
    stream_fill_order_ids = {str(f.get("order_id", "")) for f in stream_fills if f.get("order_id")}
    deduped_paper_fills = [f for f in paper_fills if str(f.get("order_id", "")) not in stream_fill_order_ids]
    all_stream_fills = list(stream_fills) + deduped_paper_fills
    stream_state["fills"] = list(all_stream_fills)
    fallback_fills = list(fallback_state.get("fills", [])) if isinstance(fallback_state.get("fills"), list) else []
    summary_fills = list(all_stream_fills) or list(db_fills) or list(fallback_fills)
    if not all_stream_fills:
        stream_state["fills"] = list(summary_fills)
    fills_total = max(
        int(stream_state.get("fills_total", 0) or 0),
        int(db_fill_activity.get("fills_total", 0) or 0),
        int(fallback_state.get("fills_total", 0) or 0),
        len(db_fills),
        len(summary_fills),
        len(paper_fills),
    )
    _today_key = datetime.now(UTC).strftime("%Y-%m-%d")
    _today_fills = [
        f for f in summary_fills
        if str(f.get("ts_utc") or f.get("ts") or "").startswith(_today_key)
    ]
    stream_activity = _summarize_fill_activity(list(summary_fills), fills_total=max(0, int(fills_total)))
    stream_activity["realized_pnl_total_quote"] = float(
        sum(float(_to_float(fill.get("realized_pnl_quote")) or 0.0) for fill in _today_fills)
    )
    if int(db_fill_activity.get("fills_total", 0) or 0) > 0:
        activity = _merge_fill_activity(db_fill_activity, stream_activity)
    else:
        activity = stream_activity
    stream_state["fills_total"] = max(
        int(stream_state.get("fills_total", 0) or 0),
        len(all_stream_fills),
        len(db_fills),
        len(fallback_fills),
        len(summary_fills),
        len(paper_fills),
        int(db_fill_activity.get("fills_total", 0) or 0),
    )
    stream_position = stream_state.get("position", {}) if isinstance(stream_state.get("position"), dict) else {}
    fallback_position = fallback_state.get("position", {}) if isinstance(fallback_state.get("position"), dict) else {}
    resolved_position = stream_position or fallback_position
    if not resolved_position and instance_name:
        snap_state = fallback.state_from_snapshot(
            instance_name, resolved_trading_pair,
            max_fills=0, max_orders=0,
            include_csv_fills=False, include_estimated_orders=False,
        )
        snap_pos = snap_state.get("position", {}) if isinstance(snap_state.get("position"), dict) else {}
        if snap_pos:
            resolved_position = dict(snap_pos)
    if not resolved_position and db_available and instance_name:
        resolved_position = db_reader.get_position(instance_name, resolved_trading_pair) or {}

    # Cross-validate: if the bot reports flat but the paper exchange holds a
    # real position, prefer the paper exchange (it is the authoritative ledger).
    if instance_name:
        _pe_pos = fallback.paper_exchange_position(instance_name, resolved_trading_pair)
        _pe_qty = abs(float(_pe_pos.get("quantity", 0) or 0)) if _pe_pos else 0.0
        _stream_qty = abs(float(_to_float(resolved_position.get("quantity")) or 0.0))
        if _pe_qty > 1e-12 and _stream_qty < 1e-12:
            logger.warning(
                "POSITION_DESYNC instance=%s: bot reports flat but paper exchange has qty=%.8f — adopting authoritative position",
                instance_name, _pe_qty,
            )
            resolved_position = dict(_pe_pos)
        elif _pe_qty > 1e-12 and _stream_qty > 1e-12:
            _pe_side = str(_pe_pos.get("side", "")).strip().lower()
            _stream_side = str(resolved_position.get("side", "")).strip().lower()
            if _pe_side != _stream_side and _pe_side in ("long", "short"):
                logger.warning(
                    "POSITION_DESYNC instance=%s: bot says side=%s but paper exchange says side=%s — adopting authoritative position",
                    instance_name, _stream_side, _pe_side,
                )
                resolved_position = dict(_pe_pos)

    if resolved_position:
        qty_val = _to_float(resolved_position.get("quantity"))
        if qty_val is not None:
            side_str = str(resolved_position.get("side", "")).strip().lower()
            if (not side_str or side_str == "flat") and abs(qty_val) > 1e-12:
                resolved_position["side"] = "short" if qty_val < 0 else "long"
            resolved_position["quantity"] = abs(qty_val)
    stream_state["position"] = resolved_position
    stream_open_orders = list(stream_state.get("open_orders", [])) if isinstance(stream_state.get("open_orders"), list) else []
    resolved_open_orders = list(stream_open_orders)
    if not resolved_open_orders and isinstance(fallback_state.get("open_orders"), list):
        resolved_open_orders = list(fallback_state.get("open_orders", []))
    if not resolved_open_orders and db_available and instance_name:
        resolved_open_orders = db_reader.get_open_orders(instance_name, resolved_trading_pair)
    if not resolved_open_orders and instance_name:
        paper_active = _read_paper_exchange_active_orders(
            fallback, instance_name, resolved_trading_pair,
        )
        if paper_active:
            resolved_open_orders = paper_active
    if not resolved_open_orders and instance_name and _fallback_allowed(cfg):
        runtime_placeholders = _build_runtime_open_order_placeholders(
            fallback, instance_name, resolved_trading_pair,
        )
        if runtime_placeholders:
            resolved_open_orders = runtime_placeholders
    stream_state["open_orders"] = resolved_open_orders
    account_summary = _sync_account_summary_with_open_orders(account_summary, resolved_open_orders, strategy_type=_strategy_type)
    if fallback_state:
        fallback_state["position"] = fallback_state.get("position", {})
        fallback_state["fills"] = list(summary_fills) or fallback_state.get("fills", [])
        fallback_state["open_orders"] = list(resolved_open_orders)
        fallback_state["fills_total"] = max(
            int(fallback_state.get("fills_total", 0) or 0),
            len(fallback_state.get("fills", [])) if isinstance(fallback_state.get("fills"), list) else 0,
            len(summary_fills),
        )
    selected_stream_age_ms = state.selected_stream_age_ms(instance_name, controller_id, resolved_trading_pair or trading_pair)
    fallback_active = bool(_fallback_allowed(cfg) and _needs_fallback(cfg, state, instance_name, controller_id, resolved_trading_pair or trading_pair))
    snapshot_pnl = float(_to_float(account_summary.get("realized_pnl_quote")) or 0.0)
    fill_based_pnl = float(_to_float(activity.get("realized_pnl_total_quote")) or 0.0)
    _snap_has_data = bool(account_summary.get("snapshot_ts"))
    account_summary["realized_pnl_quote"] = (
        snapshot_pnl if _snap_has_data else (fill_based_pnl if bool(_today_fills) else 0.0)
    )
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
            (stream_state.get("position", {}) if isinstance(stream_state.get("position"), dict) else {}).get("source_ts_ms")
            or (fallback_state.get("position", {}) if isinstance(fallback_state.get("position"), dict) else {}).get("source_ts_ms")
        )
        or 0
    )
    stream_age_ms = selected_stream_age_ms
    state_metrics = state.metrics()
    stale_threshold_ms = max(1000, int(cfg.stream_stale_ms or 0))
    system = {
        "redis_available": bool(worker.redis_available),
        "db_available": bool(db_available),
        "fallback_active": fallback_active,
        "stream_age_ms": int(stream_age_ms) if stream_age_ms is not None else None,
        "stream_stale_threshold_ms": stale_threshold_ms,
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
    source_parts: list[str] = []
    if stream_state.get("market") or stream_state.get("depth") or stream_state.get("fills"):
        source_parts.append("stream")
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
            "csv_failover_used": bool(allow_csv_fallback and fallback_state.get("fills")),
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


def _build_instances_payload(
    cfg: RealtimeApiConfig,
    state: RealtimeState,
    fallback: DeskSnapshotFallback,
) -> dict[str, Any]:
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


def _build_candles_payload(
    cfg: RealtimeApiConfig,
    state: RealtimeState,
    fallback: DeskSnapshotFallback,
    db_reader: OpsDbReadModel,
    history_provider: MarketHistoryProviderImpl | None,
    instance_name: str,
    controller_id: str,
    trading_pair: str,
    timeframe_s: int,
    limit: int,
) -> dict[str, Any]:
    legacy = _build_legacy_candles(cfg, state, fallback, db_reader, instance_name, controller_id, trading_pair, timeframe_s, limit)
    mode = cfg.normalized_history_ui_read_mode()
    if mode == "legacy":
        return legacy
    shared = _build_provider_candles(cfg, state, fallback, db_reader, history_provider, instance_name, controller_id, trading_pair, timeframe_s, limit)
    if mode == "shadow":
        legacy["shadow"] = {
            "mode": "shadow",
            "provider": {
                "source": shared.get("source"),
                "source_chain": shared.get("source_chain", []),
                "quality": shared.get("quality", {}),
            },
            "parity": _compare_candle_sets(
                legacy.get("candles", []) if isinstance(legacy.get("candles"), list) else [],
                shared.get("candles", []) if isinstance(shared.get("candles"), list) else [],
            ),
        }
        return legacy
    return shared if shared.get("candles") else legacy


def _build_legacy_candles(
    cfg: RealtimeApiConfig,
    state: RealtimeState,
    fallback: DeskSnapshotFallback,
    db_reader: OpsDbReadModel,
    instance_name: str,
    controller_id: str,
    trading_pair: str,
    timeframe_s: int,
    limit: int,
) -> dict[str, Any]:
    resolved_trading_pair = state.resolve_trading_pair(instance_name, controller_id, trading_pair)
    connector_name = state.resolve_connector_name(instance_name, controller_id, resolved_trading_pair)
    db_available = db_reader.available() if db_reader.enabled else False
    allow_csv_fallback = _operator_api_csv_fallback_allowed(cfg, db_available)
    candles: list[dict[str, Any]] = []
    source = ""
    if connector_name and resolved_trading_pair:
        rest_candles = db_reader.get_rest_backfill_candles(connector_name, resolved_trading_pair, timeframe_s, limit)
        if rest_candles:
            candles = list(rest_candles)
            source = "rest_ohlc"
    db_candles = db_reader.get_candles(connector_name, resolved_trading_pair, timeframe_s, limit) if db_available else []
    if db_candles:
        merged_by_bucket = {int(c.get("bucket_ms", 0)): c for c in candles}
        for c in db_candles:
            bk = int(c.get("bucket_ms", 0))
            if bk > 0 and bk not in merged_by_bucket:
                merged_by_bucket[bk] = c
        candles = [merged_by_bucket[k] for k in sorted(merged_by_bucket.keys()) if k > 0]
        candles = candles[-max(1, int(limit)):]
        source = f"{source}+db" if source else "db"
    stream_candles = state.get_candles(instance_name, controller_id, resolved_trading_pair, timeframe_s, limit)
    if stream_candles:
        merged_by_bucket = {int(c.get("bucket_ms", 0)): c for c in candles}
        for c in stream_candles:
            bk = int(c.get("bucket_ms", 0))
            if bk > 0 and bk not in merged_by_bucket:
                merged_by_bucket[bk] = c
        candles = [merged_by_bucket[k] for k in sorted(merged_by_bucket.keys()) if k > 0]
        candles = candles[-max(1, int(limit)):]
        source = f"{source}+stream" if source else "stream"
    if _fallback_allowed(cfg) and instance_name and resolved_trading_pair and len(candles) < max(5, int(limit)) and allow_csv_fallback:
        fallback_candles = fallback.candles_from_minute_log(instance_name, resolved_trading_pair, timeframe_s, limit)
        if fallback_candles:
            merged_by_bucket = {int(c.get("bucket_ms", 0)): c for c in candles}
            for c in fallback_candles:
                bk = int(c.get("bucket_ms", 0))
                if bk > 0 and bk not in merged_by_bucket:
                    merged_by_bucket[bk] = c
            candles = [merged_by_bucket[k] for k in sorted(merged_by_bucket.keys()) if k > 0]
            candles = candles[-max(1, int(limit)):]
            source = f"{source}+minute_log" if source else "minute_log"
    return {
        "mode": cfg.normalized_mode(),
        "source": source or "empty",
        "trading_pair": resolved_trading_pair,
        "db_available": db_available,
        "csv_failover_used": bool(allow_csv_fallback and source.endswith("minute_log")),
        "candles": candles,
    }


def _build_provider_candles(
    cfg: RealtimeApiConfig,
    state: RealtimeState,
    fallback: DeskSnapshotFallback,
    db_reader: OpsDbReadModel,
    history_provider: MarketHistoryProviderImpl | None,
    instance_name: str,
    controller_id: str,
    trading_pair: str,
    timeframe_s: int,
    limit: int,
) -> dict[str, Any]:
    resolved_trading_pair = state.resolve_trading_pair(instance_name, controller_id, trading_pair)
    connector_name = state.resolve_connector_name(instance_name, controller_id, resolved_trading_pair)
    if history_provider is None:
        return {
            "mode": cfg.normalized_mode(),
            "source": "provider_unavailable",
            "db_available": db_reader.available() if db_reader.enabled else False,
            "csv_failover_used": False,
            "source_chain": [],
            "quality": {
                "status": "empty",
                "freshness_ms": 0,
                "max_gap_s": 0,
                "coverage_ratio": 0.0,
                "source_used": "provider_unavailable",
                "degraded_reason": "provider_unavailable",
                "bars_returned": 0,
                "bars_requested": int(limit),
            },
            "candles": [],
        }
    key = MarketBarKey(
        connector_name=str(connector_name or "").strip(),
        trading_pair=str(resolved_trading_pair or "").strip(),
        bar_source="quote_mid",
    )
    bars, status = history_provider.get_bars(
        key=key,
        bar_interval_s=int(timeframe_s),
        limit=int(limit),
        require_closed=True,
    )
    candles = market_bars_to_candles(bars)
    source_chain = [part for part in str(status.source_used or "").split("+") if part]
    quality = {
        "status": str(status.status),
        "freshness_ms": int(status.freshness_ms),
        "max_gap_s": int(status.max_gap_s),
        "coverage_ratio": float(status.coverage_ratio),
        "source_used": str(status.source_used or "empty"),
        "degraded_reason": str(status.degraded_reason or ""),
        "bars_returned": int(status.bars_returned or len(candles)),
        "bars_requested": int(status.bars_requested),
    }
    if (
        _fallback_allowed(cfg)
        and instance_name
        and resolved_trading_pair
        and len(candles) < max(5, int(limit))
        and _operator_api_csv_fallback_allowed(cfg, db_reader.available() if db_reader.enabled else False)
    ):
        fallback_candles = fallback.candles_from_minute_log(instance_name, resolved_trading_pair, timeframe_s, limit)
        if fallback_candles:
            merged_by_bucket = {int(c.get("bucket_ms", 0)): c for c in fallback_candles}
            merged_by_bucket.update({int(c.get("bucket_ms", 0)): c for c in candles})
            candles = [merged_by_bucket[k] for k in sorted(merged_by_bucket.keys()) if k > 0]
            candles = candles[-max(1, int(limit)):]
            if "minute_log" not in source_chain:
                source_chain.append("minute_log")
            quality = _history_quality_from_candles(
                candles,
                bar_interval_s=int(timeframe_s),
                bars_requested=int(status.bars_requested),
                source_used="+".join(source_chain) if source_chain else str(status.source_used or "empty"),
                degraded_reason=str(status.degraded_reason or "minute_log"),
            )
            if quality["status"] == "fresh":
                quality["status"] = "degraded"
            if not str(quality.get("degraded_reason", "")).strip():
                quality["degraded_reason"] = "minute_log"
    return {
        "mode": cfg.normalized_mode(),
        "source": "+".join(source_chain) if source_chain else str(status.source_used or "empty"),
        "trading_pair": resolved_trading_pair,
        "db_available": db_reader.available() if db_reader.enabled else False,
        "csv_failover_used": "minute_log" in source_chain,
        "source_chain": source_chain,
        "quality": quality,
        "candles": candles,
    }


def _build_daily_review_payload(
    cfg: RealtimeApiConfig,
    fallback: DeskSnapshotFallback,
    db_reader: OpsDbReadModel,
    instance_name: str,
    trading_pair: str,
    day_key: str,
) -> dict[str, Any]:
    if not instance_name:
        return {"status": "error", "reason": "instance_name_required"}
    snapshot = fallback.get_snapshot(instance_name)
    minute = snapshot.get("minute", {}) if isinstance(snapshot.get("minute"), dict) else {}
    daily_state = snapshot.get("daily_state", {}) if isinstance(snapshot.get("daily_state"), dict) else {}
    snapshot_day = str(daily_state.get("day_key") or "") or str(snapshot.get("source_ts", "") or "")[:10]
    resolved_pair = trading_pair or str(minute.get("trading_pair", "") or "")
    resolved_day, _, _ = _day_bounds_utc(day_key or snapshot_day)
    account_summary = fallback.account_summary(instance_name)
    minute_rows = (
        fallback.minute_rows_from_csv(instance_name, resolved_pair, resolved_day)
        if cfg.use_csv_for_operator_api
        else []
    )
    db_available = db_reader.available() if db_reader.enabled else False
    fills = (
        fallback.filter_fill_rows_for_instance(
            instance_name,
            db_reader.get_fills_for_day(instance_name, resolved_pair, resolved_day),
        )
        if db_available
        else []
    )
    source_parts: list[str] = []
    if fills:
        source_parts.append("db_fills")
    if not fills and _operator_api_csv_fallback_allowed(cfg, db_available):
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


def _build_weekly_review_payload(
    cfg: RealtimeApiConfig,
    fallback: DeskSnapshotFallback,
    instance_name: str,
) -> dict[str, Any]:
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
    cfg: RealtimeApiConfig,
    fallback: DeskSnapshotFallback,
    db_reader: OpsDbReadModel,
    instance_name: str,
    trading_pair: str,
    start_day: str,
    end_day: str,
) -> dict[str, Any]:
    if not instance_name:
        return {"status": "error", "reason": "instance_name_required"}
    snapshot = fallback.get_snapshot(instance_name)
    minute = snapshot.get("minute", {}) if isinstance(snapshot.get("minute"), dict) else {}
    resolved_pair = trading_pair or str(minute.get("trading_pair", "") or "")
    source_parts: list[str] = []
    db_available = db_reader.available() if db_reader.enabled else False
    fills = (
        fallback.filter_fill_rows_for_instance(
            instance_name,
            db_reader.get_fills_range(instance_name, resolved_pair, start_day, end_day, limit=12000),
        )
        if db_available
        else []
    )
    if fills:
        source_parts.append("db_fills")
    if not fills and _operator_api_csv_fallback_allowed(cfg, db_available):
        fills = fallback.fills_from_csv_range(instance_name, resolved_pair, start_day, end_day, limit=12000)
        if fills:
            source_parts.append("fills_csv")
    minute_rows = (
        fallback.minute_rows_range(instance_name, resolved_pair, start_day, end_day, limit=20000)
        if cfg.use_csv_for_operator_api
        else []
    )
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


# ---------------------------------------------------------------------------
# Starlette application factory
# ---------------------------------------------------------------------------

def create_app(
    cfg: RealtimeApiConfig,
    state: RealtimeState,
    worker: StreamWorker,
    fallback: DeskSnapshotFallback,
    db_reader: OpsDbReadModel,
    history_provider: MarketHistoryProviderImpl | None,
):
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.routing import Route, WebSocketRoute
    from starlette.websockets import WebSocket, WebSocketDisconnect

    # Parse allowed origins for CORS middleware.
    allowed_origins = [item.strip() for item in cfg.allowed_origins.split(",") if item.strip()]
    if not allowed_origins:
        allowed_origins = [cfg.cors_allow_origin] if cfg.cors_allow_origin and cfg.cors_allow_origin != "*" else ["*"]

    loop: asyncio.AbstractEventLoop | None = None

    def _get_loop() -> asyncio.AbstractEventLoop:
        nonlocal loop
        if loop is None:
            loop = asyncio.get_event_loop()
        return loop

    # ── Helpers ──────────────────────────────────────────────────────────

    def _json_response(payload: Any, status_code: int = 200) -> Response:
        return Response(
            content=_json_bytes(payload),
            status_code=status_code,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    def _check_auth(request: Request) -> Response | None:
        if not _is_authorized(cfg, request):
            return _json_response({"status": "unauthorized"}, 401)
        return None

    def _check_disabled() -> Response | None:
        if cfg.normalized_mode() == "disabled":
            return _json_response({"status": "disabled", "reason": "REALTIME_UI_API_MODE=disabled"}, 503)
        return None

    def _params(request: Request) -> tuple[str, str, str]:
        instance_name = _sanitize_path_param(request.query_params.get("instance_name", ""))
        controller_id = request.query_params.get("controller_id", "").strip()
        trading_pair = request.query_params.get("trading_pair", "").strip()
        return instance_name, controller_id, trading_pair

    # ── Route handlers ──────────────────────────────────────────────────

    async def health(request: Request) -> Response:
        status_code, payload = await _get_loop().run_in_executor(
            None, _build_health_payload, cfg, state, worker, fallback, db_reader,
        )
        return _json_response(payload, status_code)

    async def get_state(request: Request) -> Response:
        denied = _check_auth(request) or _check_disabled()
        if denied:
            return denied
        instance_name, controller_id, trading_pair = _params(request)
        payload = await _get_loop().run_in_executor(
            None,
            partial(_build_state_payload, cfg, state, worker, fallback, db_reader, instance_name, controller_id, trading_pair),
        )
        return _json_response(payload)

    async def get_instances(request: Request) -> Response:
        denied = _check_auth(request) or _check_disabled()
        if denied:
            return denied
        payload = await _get_loop().run_in_executor(
            None, partial(_build_instances_payload, cfg, state, fallback),
        )
        return _json_response(payload)

    async def get_candles(request: Request) -> Response:
        denied = _check_auth(request) or _check_disabled()
        if denied:
            return denied
        instance_name, controller_id, trading_pair = _params(request)
        timeframe_s = int(request.query_params.get("timeframe_s", "60") or "60")
        limit = int(request.query_params.get("limit", "300") or "300")
        payload = await _get_loop().run_in_executor(
            None,
            partial(
                _build_candles_payload, cfg, state, fallback, db_reader, history_provider,
                instance_name, controller_id, trading_pair, timeframe_s, limit,
            ),
        )
        return _json_response(payload)

    async def get_depth(request: Request) -> Response:
        denied = _check_auth(request) or _check_disabled()
        if denied:
            return denied
        instance_name, controller_id, trading_pair = _params(request)
        stream_state = state.get_state(instance_name, controller_id, trading_pair)
        depth = stream_state.get("depth", {})
        return _json_response({"mode": cfg.normalized_mode(), "source": "stream", "depth": depth})

    async def get_positions(request: Request) -> Response:
        denied = _check_auth(request) or _check_disabled()
        if denied:
            return denied
        instance_name, _, trading_pair = _params(request)
        if not instance_name:
            return _json_response({"status": "error", "reason": "instance_name_required"}, 400)
        db_available = db_reader.available() if db_reader.enabled else False
        fallback_state = {}
        used_degraded_snapshot = False
        if _fallback_allowed(cfg):
            fallback_state = fallback.state_from_snapshot(
                instance_name, trading_pair,
                max_fills=cfg.max_fallback_fills, max_orders=cfg.max_fallback_orders,
                include_csv_fills=False, include_estimated_orders=False,
            )
            used_degraded_snapshot = bool(fallback_state)
        if db_available:
            fallback_state["position"] = db_reader.get_position(instance_name, trading_pair) or fallback_state.get("position", {})
        return _json_response({
            "mode": cfg.normalized_mode(),
            "source": "db+degraded_snapshot" if db_available and used_degraded_snapshot else ("db" if db_available else "degraded_snapshot"),
            **fallback_state,
        })

    async def get_metrics(request: Request) -> Response:
        denied = _check_auth(request) or _check_disabled()
        if denied:
            return denied
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
        return Response(
            content=("\n".join(lines) + "\n").encode(),
            status_code=200,
            media_type="text/plain; version=0.0.4",
            headers={"Cache-Control": "no-store"},
        )

    async def review_daily(request: Request) -> Response:
        denied = _check_auth(request) or _check_disabled()
        if denied:
            return denied
        instance_name, _, trading_pair = _params(request)
        if not instance_name:
            return _json_response({"status": "error", "reason": "instance_name_required"}, 400)
        day_key = request.query_params.get("day", "").strip()
        payload = await _get_loop().run_in_executor(
            None,
            partial(_build_daily_review_payload, cfg, fallback, db_reader, instance_name, trading_pair, day_key),
        )
        return _json_response(payload)

    async def review_weekly(request: Request) -> Response:
        denied = _check_auth(request) or _check_disabled()
        if denied:
            return denied
        instance_name, _, _ = _params(request)
        if not instance_name:
            return _json_response({"status": "error", "reason": "instance_name_required"}, 400)
        payload = await _get_loop().run_in_executor(
            None,
            partial(_build_weekly_review_payload, cfg, fallback, instance_name),
        )
        return _json_response(payload)

    async def review_journal(request: Request) -> Response:
        denied = _check_auth(request) or _check_disabled()
        if denied:
            return denied
        instance_name, _, trading_pair = _params(request)
        if not instance_name:
            return _json_response({"status": "error", "reason": "instance_name_required"}, 400)
        start_day = request.query_params.get("start_day", "").strip()
        end_day = request.query_params.get("end_day", "").strip()
        payload = await _get_loop().run_in_executor(
            None,
            partial(_build_journal_review_payload, cfg, fallback, db_reader, instance_name, trading_pair, start_day, end_day),
        )
        return _json_response(payload)

    # ── WebSocket handler (replaces hand-rolled RFC 6455) ───────────────

    async def ws_handler(websocket: WebSocket) -> None:
        # Auth check via query params (WS can't send custom headers easily).
        token = websocket.query_params.get("token", "").strip()
        auth_header = websocket.headers.get("authorization", "")
        authorized = not cfg.auth_enabled
        if not authorized:
            expected = cfg.auth_token.strip()
            if expected:
                authorized = (auth_header == f"Bearer {expected}") or (cfg.allow_query_token and token == expected)
        if not authorized:
            await websocket.close(code=4001, reason="unauthorized")
            return
        if cfg.normalized_mode() == "disabled":
            await websocket.close(code=4003, reason="disabled")
            return

        instance_name = _sanitize_path_param(websocket.query_params.get("instance_name", ""))
        controller_id = websocket.query_params.get("controller_id", "").strip()
        trading_pair = websocket.query_params.get("trading_pair", "").strip()
        timeframe_s = int(websocket.query_params.get("timeframe_s", "60") or "60")
        candle_limit = int(websocket.query_params.get("limit", "300") or "300")

        # Resolve pair from fallback if not provided (bot may not be running).
        resolved_pair = trading_pair
        if not resolved_pair and instance_name:
            _fb_snap = fallback.get_snapshot(instance_name)
            _fb_minute = _fb_snap.get("minute", {}) if isinstance(_fb_snap.get("minute"), dict) else {}
            resolved_pair = str(_fb_minute.get("trading_pair", "")).strip()

        await websocket.accept()

        q = state.register_subscriber(instance_name, controller_id, resolved_pair or trading_pair)
        try:
            # Send initial snapshot.
            snapshot_payload = await _get_loop().run_in_executor(
                None,
                partial(_build_state_payload, cfg, state, worker, fallback, db_reader, instance_name, controller_id, resolved_pair or trading_pair),
            )
            candles_payload = await _get_loop().run_in_executor(
                None,
                partial(
                    _build_candles_payload, cfg, state, fallback, db_reader, history_provider,
                    instance_name, controller_id, resolved_pair or trading_pair, timeframe_s, candle_limit,
                ),
            )
            # Extract the final resolved pair from the payload stream key.
            _snap_stream = snapshot_payload.get("stream", {}) if isinstance(snapshot_payload.get("stream"), dict) else {}
            _snap_key = _snap_stream.get("key", {}) if isinstance(_snap_stream.get("key"), dict) else {}
            _snap_market = _snap_stream.get("market", {}) if isinstance(_snap_stream.get("market"), dict) else {}
            effective_pair = str(
                resolved_pair
                or _snap_key.get("trading_pair", "")
                or _snap_market.get("trading_pair", "")
                or trading_pair
            ).strip()

            snapshot_msg = {
                "type": "snapshot",
                "ts_ms": _now_ms(),
                "instance_name": instance_name,
                "controller_id": controller_id,
                "trading_pair": effective_pair,
                "key": {"instance_name": instance_name, "controller_id": controller_id, "trading_pair": effective_pair},
                "state": snapshot_payload,
                "candles": candles_payload.get("candles", []),
            }
            await websocket.send_text(_json_str(snapshot_msg))

            last_snapshot_ms = _now_ms()

            while True:
                # Bridge blocking queue.get() to async via executor.
                try:
                    raw = await asyncio.wait_for(
                        _get_loop().run_in_executor(None, partial(q.get, timeout=2.0)),
                        timeout=6.0,
                    )
                    evt = json.loads(raw) if isinstance(raw, str) else {}
                    event_key = evt.get("key")
                    if not _stream_key_matches(event_key, instance_name, controller_id, effective_pair or trading_pair):
                        continue
                    await websocket.send_text(_json_str({"type": "event", **evt}))
                except (TimeoutError, queue.Empty):
                    await websocket.send_text(_json_str({"type": "keepalive", "ts_ms": _now_ms()}))

                now_ms = _now_ms()
                if now_ms - last_snapshot_ms >= 60_000:
                    periodic_state = await _get_loop().run_in_executor(
                        None,
                        partial(_build_state_payload, cfg, state, worker, fallback, db_reader, instance_name, controller_id, effective_pair or trading_pair),
                    )
                    periodic_candles = await _get_loop().run_in_executor(
                        None,
                        partial(
                            _build_candles_payload, cfg, state, fallback, db_reader, history_provider,
                            instance_name, controller_id, effective_pair or trading_pair, timeframe_s, candle_limit,
                        ),
                    )
                    periodic_msg = {
                        "type": "snapshot",
                        "ts_ms": now_ms,
                        "instance_name": instance_name,
                        "controller_id": controller_id,
                        "trading_pair": effective_pair,
                        "key": {"instance_name": instance_name, "controller_id": controller_id, "trading_pair": effective_pair},
                        "state": periodic_state,
                        "candles": periodic_candles.get("candles", []),
                    }
                    await websocket.send_text(_json_str(periodic_msg))
                    last_snapshot_ms = now_ms

        except WebSocketDisconnect:
            pass
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            state.unregister_subscriber(q)

    # ── SSE stream handler ──────────────────────────────────────────────

    async def sse_stream(request: Request) -> Response:
        denied = _check_auth(request) or _check_disabled()
        if denied:
            return denied
        if not cfg.sse_enabled:
            return _json_response({"status": "not_found", "path": "/api/v1/stream"}, 404)

        instance_name, controller_id, trading_pair = _params(request)
        q = state.register_subscriber(instance_name, controller_id, trading_pair)

        from starlette.responses import StreamingResponse

        async def _event_generator():
            try:
                yield "event: ready\ndata: {\"status\":\"ok\"}\n\n"
                while True:
                    try:
                        payload = await asyncio.wait_for(
                            _get_loop().run_in_executor(None, partial(q.get, timeout=10.0)),
                            timeout=16.0,
                        )
                        yield f"event: update\ndata: {payload}\n\n"
                    except (TimeoutError, queue.Empty):
                        yield ": keepalive\n\n"
            except (BrokenPipeError, ConnectionResetError, asyncio.CancelledError):
                pass
            finally:
                state.unregister_subscriber(q)

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # ── Backtest API routes ─────────────────────────────────────────────

    from services.realtime_ui_api.backtest_api import create_backtest_routes
    backtest_routes = create_backtest_routes(auth_check=_check_auth)

    from services.common.research_api import create_research_routes
    research_routes = create_research_routes(auth_check=_check_auth)

    # ── Routes ──────────────────────────────────────────────────────────

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/metrics", get_metrics, methods=["GET"]),
        Route("/api/v1/state", get_state, methods=["GET"]),
        Route("/api/v1/instances", get_instances, methods=["GET"]),
        Route("/api/v1/candles", get_candles, methods=["GET"]),
        Route("/api/v1/depth", get_depth, methods=["GET"]),
        Route("/api/v1/positions", get_positions, methods=["GET"]),
        Route("/api/v1/review/daily", review_daily, methods=["GET"]),
        Route("/api/v1/review/weekly", review_weekly, methods=["GET"]),
        Route("/api/v1/review/journal", review_journal, methods=["GET"]),
        Route("/api/v1/stream", sse_stream, methods=["GET"]),
        WebSocketRoute("/api/v1/ws", ws_handler),
        *backtest_routes,
        *research_routes,
    ]

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        ),
    ]

    return Starlette(routes=routes, middleware=middleware)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

def run() -> None:
    import uvicorn

    cfg = RealtimeApiConfig()
    _validate_runtime_config(cfg)
    state = RealtimeState(cfg)
    worker = StreamWorker(cfg, state)
    fallback = DeskSnapshotFallback(cfg.fallback_root, cfg.data_root)
    db_reader = OpsDbReadModel(cfg)
    history_provider: MarketHistoryProviderImpl | None = None

    if cfg.normalized_history_ui_read_mode() in {"shadow", "shared"}:
        def _db_bar_reader(connector_name, trading_pair, bar_interval_s, limit):
            return _candle_dicts_to_market_bars(
                db_reader.get_market_bars(connector_name, trading_pair, bar_interval_s, limit),
                bar_interval_s=bar_interval_s,
                bar_source="db",
            )

        def _stream_bar_reader(connector_name, trading_pair, bar_interval_s, limit):
            return _candle_dicts_to_market_bars(
                state.get_candles("", "", trading_pair, bar_interval_s, limit),
                bar_interval_s=bar_interval_s,
                bar_source="stream",
            )

        def _rest_bar_reader(connector_name, trading_pair, bar_interval_s, limit):
            return _candle_dicts_to_market_bars(
                db_reader.get_rest_backfill_candles(connector_name, trading_pair, bar_interval_s, limit),
                bar_interval_s=bar_interval_s,
                bar_source="rest_ohlc",
            )

        history_provider = MarketHistoryProviderImpl(
            db_reader=_db_bar_reader,
            stream_reader=_stream_bar_reader,
            rest_reader=_rest_bar_reader,
            now_ms_reader=_now_ms,
        )
    worker.start()

    app = create_app(cfg, state, worker, fallback, db_reader, history_provider)

    logger.info(
        "realtime_ui_api starting host=%s port=%s mode=%s fallback_enabled=%s degraded_mode_enabled=%s",
        cfg.bind_host,
        cfg.port,
        cfg.normalized_mode(),
        cfg.fallback_enabled,
        cfg.degraded_mode_enabled,
    )

    try:
        uvicorn.run(
            app,
            host=cfg.bind_host,
            port=cfg.port,
            log_level="info",
            access_log=True,
            ws="auto",
            lifespan="off",
        )
    finally:
        worker.stop()
        try:
            from services.realtime_ui_api.backtest_api import shutdown_backtest_subprocesses

            shutdown_backtest_subprocesses()
        except Exception:
            logger.debug("backtest subprocess shutdown skipped", exc_info=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream-first realtime UI API with fallback to desk snapshots.")
    parser.add_argument("--once", action="store_true", help="Unused compatibility flag; kept for service symmetry.")
    _ = parser.parse_args()
    run()


if __name__ == "__main__":
    main()
