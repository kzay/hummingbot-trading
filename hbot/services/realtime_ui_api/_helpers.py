from __future__ import annotations

import json
import logging
import os
import re as _re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    import ccxt  # type: ignore
except Exception:
    ccxt = None  # type: ignore[assignment]

from platform_lib.market_data.market_history_provider_impl import MarketHistoryProviderImpl
from platform_lib.market_data.market_history_types import MarketBar

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _depth_mid(snapshot: dict[str, Any]) -> float | None:
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


def _to_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _normalize_pair(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "").replace("-", "").replace("_", "")


_SAFE_NAME_RE = _re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-\.]{0,63}$")


def _sanitize_path_param(value: str) -> str:
    """Validate path-sensitive parameters (instance_name, etc.) against traversal attacks.

    Rejects values containing '..', '/', '\\', or characters outside [a-zA-Z0-9_-.].
    Returns the stripped value if safe, empty string otherwise.
    """
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
        return ""
    if not _SAFE_NAME_RE.match(cleaned):
        return ""
    return cleaned


def _candle_dicts_to_market_bars(
    candles: list[dict[str, Any]],
    *,
    bar_interval_s: int,
    bar_source: str,
) -> list[MarketBar]:
    out: list[MarketBar] = []
    for candle in candles:
        bucket_ms = _to_epoch_ms(candle.get("bucket_ms"))
        open_price = candle.get("open")
        high_price = candle.get("high")
        low_price = candle.get("low")
        close_price = candle.get("close")
        if None in {bucket_ms, open_price, high_price, low_price, close_price}:
            continue
        out.append(
            MarketBar(
                bucket_start_ms=int(bucket_ms),
                bar_interval_s=int(bar_interval_s),
                open=Decimal(str(open_price)),
                high=Decimal(str(high_price)),
                low=Decimal(str(low_price)),
                close=Decimal(str(close_price)),
                is_closed=True,
                bar_source=bar_source,
            )
        )
    return out


def _history_quality_from_candles(
    candles: list[dict[str, Any]],
    *,
    bar_interval_s: int,
    bars_requested: int,
    source_used: str,
    degraded_reason: str = "",
    now_ms: int | None = None,
) -> dict[str, Any]:
    provider = MarketHistoryProviderImpl(now_ms_reader=_now_ms)
    status = provider._build_status(
        bars=_candle_dicts_to_market_bars(
            candles,
            bar_interval_s=max(60, int(bar_interval_s)),
            bar_source="quote_mid",
        ),
        bar_interval_s=max(60, int(bar_interval_s)),
        requested=max(1, int(bars_requested)),
        source_used=str(source_used or "empty"),
        degraded_reason=str(degraded_reason or ""),
        now_ms=int(now_ms or _now_ms()),
    )
    return {
        "status": str(status.status or "empty"),
        "freshness_ms": int(status.freshness_ms),
        "max_gap_s": int(status.max_gap_s),
        "coverage_ratio": float(status.coverage_ratio),
        "source_used": str(status.source_used or source_used or "empty"),
        "degraded_reason": str(status.degraded_reason or ""),
        "bars_returned": int(status.bars_returned or len(candles)),
        "bars_requested": int(status.bars_requested or bars_requested),
    }


def _compare_candle_sets(legacy: list[dict[str, Any]], shared: list[dict[str, Any]]) -> dict[str, Any]:
    legacy_by_bucket = {int(c.get("bucket_ms", 0) or 0): c for c in legacy if int(c.get("bucket_ms", 0) or 0) > 0}
    shared_by_bucket = {int(c.get("bucket_ms", 0) or 0): c for c in shared if int(c.get("bucket_ms", 0) or 0) > 0}
    buckets = sorted(set(legacy_by_bucket.keys()) | set(shared_by_bucket.keys()))
    max_abs_close_delta = 0.0
    mismatched_buckets = 0
    missing_in_shared = 0
    missing_in_legacy = 0
    for bucket in buckets:
        legacy_row = legacy_by_bucket.get(bucket)
        shared_row = shared_by_bucket.get(bucket)
        if legacy_row is None:
            missing_in_legacy += 1
            mismatched_buckets += 1
            continue
        if shared_row is None:
            missing_in_shared += 1
            mismatched_buckets += 1
            continue
        close_delta = abs(float(legacy_row.get("close", 0.0) or 0.0) - float(shared_row.get("close", 0.0) or 0.0))
        max_abs_close_delta = max(max_abs_close_delta, close_delta)
        if any(abs(float(legacy_row.get(k, 0.0) or 0.0) - float(shared_row.get(k, 0.0) or 0.0)) > 1e-9 for k in ("open", "high", "low", "close")):
            mismatched_buckets += 1
    return {
        "bucket_count_legacy": len(legacy_by_bucket),
        "bucket_count_shared": len(shared_by_bucket),
        "missing_in_shared": missing_in_shared,
        "missing_in_legacy": missing_in_legacy,
        "mismatched_buckets": mismatched_buckets,
        "max_abs_close_delta": max_abs_close_delta,
    }


def _to_epoch_ms(value: Any) -> int | None:
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


def _candles_from_points(points: list[tuple[int, float]], timeframe_s: int, limit: int) -> list[dict[str, Any]]:
    timeframe_ms = max(1, int(timeframe_s)) * 1000
    buckets: dict[int, dict[str, Any]] = {}
    last_close: float | None = None
    last_bucket: int | None = None
    for ts_ms, price in points:
        if price is None or price <= 0:
            continue
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


def _window_summary_template() -> dict[str, Any]:
    return {
        "fill_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "maker_count": 0,
        "maker_ratio": 0.0,
        "volume_base": 0.0,
        "notional_quote": 0.0,
        "realized_pnl_quote": 0.0,
        "fees_quote": 0.0,
        "avg_fill_size": 0.0,
        "avg_fill_price": 0.0,
    }


def _resolve_realized_pnl(
    minute: dict[str, Any],
    daily_state: dict[str, Any],
    daily_state_current: bool,
) -> float:
    """Return today's realized PnL using an explicit None-aware priority chain.

    Python ``or`` treats ``0.0`` as falsy, so a genuine 0-PnL day would
    otherwise fall through to all-time cumulative sources (wrong).  This
    helper stops at the first key that is *present* in its source dict,
    even when the value is zero.
    """
    def _field_or_none(d: dict[str, Any], key: str) -> float | None:
        v = d.get(key)
        if v is None:
            return None
        s = str(v).strip()
        if not s or s.lower() in ("none", "null", "nan", ""):
            return None
        try:
            return float(s)
        except (ValueError, TypeError):
            return None

    for key in ("net_realized_pnl_today_quote", "realized_pnl_today_quote"):
        val = _field_or_none(minute, key)
        if val is not None:
            return val
    if daily_state_current:
        for key in ("realized_pnl_day_quote", "realized_pnl"):
            val = _field_or_none(daily_state, key)
            if val is not None:
                return val
    return 0.0


def _account_summary_template() -> dict[str, Any]:
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


def _day_bounds_utc(day_key: str) -> tuple[str, int, int]:
    normalized = str(day_key or "").strip()
    if normalized:
        start_dt = datetime.fromisoformat(f"{normalized}T00:00:00+00:00")
    else:
        now = datetime.now(UTC)
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        normalized = start_dt.date().isoformat()
    end_dt = start_dt + timedelta(days=1)
    return normalized, int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)


def _daily_review_template(day_key: str) -> dict[str, Any]:
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


def _weekly_review_template() -> dict[str, Any]:
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


def _journal_review_template() -> dict[str, Any]:
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
    fill: dict[str, Any],
    amount_base: float,
    fee_quote: float,
    realized_pnl_quote: float,
    role: str,
) -> dict[str, Any]:
    price = float(_to_float(fill.get("price")) or 0.0)
    ts_ms = int(fill.get("timestamp_ms") or 0)
    return {
        "ts": str(fill.get("ts") or (datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat() if ts_ms > 0 else "")),
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


def _reconstruct_closed_trades(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_fills = [row for row in fills if isinstance(row, dict)]
    safe_fills.sort(key=lambda row: int(row.get("timestamp_ms") or 0))
    trades: list[dict[str, Any]] = []
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
    trade_fills: list[dict[str, Any]] = []
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
                "entry_ts": datetime.fromtimestamp(entry_ts_ms / 1000, tz=UTC).isoformat() if entry_ts_ms > 0 else "",
                "exit_ts": datetime.fromtimestamp(exit_ts_ms / 1000, tz=UTC).isoformat() if exit_ts_ms > 0 else "",
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


def _nearest_context_row(target_ms: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    nearest: dict[str, Any] = {}
    nearest_distance: int | None = None
    for row in rows:
        ts_ms = int(row.get("timestamp_ms") or 0)
        if ts_ms <= 0:
            continue
        distance = abs(ts_ms - target_ms)
        if nearest_distance is None or distance < nearest_distance:
            nearest = row
            nearest_distance = distance
    return nearest


def _split_risk_reasons(raw: Any) -> list[str]:
    parts = [part.strip() for part in str(raw or "").split("|")]
    return [part for part in parts if part]


def _build_quote_gate_summary(minute: dict[str, Any], orders_active_override: int | None = None, strategy_type: str | None = None) -> dict[str, Any]:
    controller_state = str(minute.get("state", "") or "").strip().lower()
    risk_reasons = _split_risk_reasons(minute.get("risk_reasons"))
    order_book_stale = _to_bool(minute.get("order_book_stale"))
    pnl_governor_active = _to_bool(minute.get("pnl_governor_active"))
    spread_cap_active = _to_bool(minute.get("spread_competitiveness_cap_active"))
    soft_pause_edge = _to_bool(minute.get("soft_pause_edge"))
    orders_active = (
        max(0, int(orders_active_override or 0))
        if orders_active_override is not None
        else int(_to_float(minute.get("orders_active")) or 0)
    )
    net_edge_pct = float(_to_float(minute.get("net_edge_pct")) or 0.0)
    net_edge_gate_pct = float(_to_float(minute.get("net_edge_gate_pct")) or 0.0)
    adaptive_effective_min_edge_pct = float(_to_float(minute.get("adaptive_effective_min_edge_pct")) or 0.0)
    edge_threshold = max(net_edge_gate_pct, adaptive_effective_min_edge_pct)
    spread_pct = float(_to_float(minute.get("spread_pct")) or 0.0)
    spread_floor_pct = float(_to_float(minute.get("spread_floor_pct")) or 0.0)

    quote_gates: list[dict[str, Any]] = [
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

    # Directional bots don't use spread/edge gating — filter out MM-only gates.
    _MM_ONLY_GATE_KEYS = {"edge", "spread", "spread_cap"}
    if strategy_type == "directional":
        quote_gates = [g for g in quote_gates if g["key"] not in _MM_ONLY_GATE_KEYS]

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


_BOT_GATE_DEFINITIONS: dict[str, list[tuple[str, str]]] = {
    "bot1": [
        ("state", "Bot1 signal gate"),
        ("signal_side", "Signal side"),
        ("signal_score", "Signal score"),
    ],
    "bot5": [
        ("state", "Bot5 signal gate"),
        ("conviction", "Flow conviction"),
    ],
    "bot6": [
        ("state", "Bot6 signal gate"),
        ("score_ratio", "Signal score"),
        ("cvd_divergence_ratio", "CVD divergence"),
        ("adx", "ADX"),
        ("hedge_state", "Hedge state"),
    ],
    "bot7": [
        ("state", "Bot7 signal gate"),
        ("adx", "ADX"),
        ("rsi", "RSI"),
    ],
}

_BOT_STRATEGY_TYPE: dict[str, str] = {
    "bot1": "mm",
    "bot5": "directional",
    "bot6": "directional",
    "bot7": "directional",
}


def _derive_gate_status(key: str, value: Any) -> str:
    if key == "state":
        raw = str(value or "").strip().lower()
        if raw == "blocked":
            return "fail"
        if raw == "active":
            return "pass"
        if raw == "idle":
            return "warn"
        return "warn"
    return "info"


def _build_bot_gates(
    raw_bot_gates: dict[str, Any],
    strategy_type_override: str | None = None,
) -> list[dict[str, Any]]:
    """Convert raw bot_gates telemetry dict into structured per-bot gate groups.

    Returns a list of ``{bot_id, strategy_type, gates: [{key, label, status, detail}]}``
    entries sorted by bot_id.
    """
    if not raw_bot_gates or not isinstance(raw_bot_gates, dict):
        return []
    result: list[dict[str, Any]] = []
    for bot_id in sorted(raw_bot_gates.keys()):
        bot_data = raw_bot_gates[bot_id]
        if not isinstance(bot_data, dict):
            continue
        gate_defs = _BOT_GATE_DEFINITIONS.get(bot_id, [])
        if not gate_defs:
            gate_defs = [("gate_state", f"{bot_id} gate")]
        st = strategy_type_override or _BOT_STRATEGY_TYPE.get(bot_id, "")
        gates: list[dict[str, Any]] = []
        for field_key, label in gate_defs:
            raw_val = bot_data.get(field_key)
            detail = str(raw_val) if raw_val is not None else ""
            if isinstance(raw_val, float):
                detail = f"{raw_val:.4f}" if abs(raw_val) < 100 else f"{raw_val:.2f}"
            status = _derive_gate_status(field_key, raw_val)
            gates.append({"key": field_key, "label": label, "status": status, "detail": detail})
        result.append({"bot_id": bot_id, "strategy_type": st, "gates": gates})
    return result


def _sync_account_summary_with_open_orders(account_summary: dict[str, Any], resolved_open_orders: list[dict[str, Any]], strategy_type: str | None = None) -> dict[str, Any]:
    safe = dict(account_summary or {})
    orders_active = len([row for row in resolved_open_orders if isinstance(row, dict)])
    gate_summary = _build_quote_gate_summary(
        {
            "state": safe.get("controller_state"),
            "risk_reasons": safe.get("risk_reasons"),
            "order_book_stale": safe.get("order_book_stale"),
            "pnl_governor_active": safe.get("pnl_governor_active"),
            "pnl_governor_activation_reason": safe.get("pnl_governor_reason"),
            "spread_competitiveness_cap_active": safe.get("spread_competitiveness_cap_active"),
            "soft_pause_edge": safe.get("soft_pause_edge"),
            "net_edge_pct": safe.get("net_edge_pct"),
            "net_edge_gate_pct": safe.get("net_edge_gate_pct"),
            "adaptive_effective_min_edge_pct": safe.get("adaptive_effective_min_edge_pct"),
            "spread_pct": safe.get("spread_pct"),
            "spread_floor_pct": safe.get("spread_floor_pct"),
            "orders_active": orders_active,
        },
        orders_active_override=orders_active,
        strategy_type=strategy_type,
    )
    safe["orders_active"] = int(gate_summary.get("orders_active") or 0)
    safe["quoting_status"] = str(gate_summary.get("quoting_status") or "")
    safe["quoting_reason"] = str(gate_summary.get("quoting_reason") or "")
    safe["quote_gates"] = list(gate_summary.get("quote_gates") or [])
    return safe


_PAPER_ACTIVE_STATES = {"working", "open", "partially_filled"}


def _read_paper_exchange_active_orders(
    snapshot_path: Path,
    instance_name: str,
    trading_pair: str,
) -> list[dict[str, Any]]:
    """Read real active order details from the paper exchange state snapshot.

    Returns order dicts in UI format, filtered to the given instance and
    trading pair.  Returns an empty list if the snapshot is unavailable,
    stale (> 120 s), or contains no matching active orders.
    """
    try:
        if not snapshot_path.exists():
            return []
        stat = snapshot_path.stat()
        age_s = time.time() - stat.st_mtime
        if age_s > 120:
            return []
        with snapshot_path.open() as fh:
            payload = json.load(fh)
        orders_raw = payload.get("orders", {})
        if not isinstance(orders_raw, dict):
            return []
        inst_norm = str(instance_name or "").strip().lower()
        pair_norm = str(trading_pair or "").strip().upper()
        out: list[dict[str, Any]] = []
        for order in orders_raw.values():
            if not isinstance(order, dict):
                continue
            if str(order.get("instance_name", "")).strip().lower() != inst_norm:
                continue
            if pair_norm and str(order.get("trading_pair", "")).strip().upper() != pair_norm:
                continue
            if str(order.get("state", "")).strip().lower() not in _PAPER_ACTIVE_STATES:
                continue
            price = _to_float(order.get("price"))
            amount = _to_float(order.get("amount_base"))
            side = str(order.get("side", "")).strip().lower()
            order_id = str(order.get("order_id", "")).strip()
            ts_ms = int(order.get("updated_ts_ms") or order.get("created_ts_ms") or _now_ms())
            out.append({
                "order_id": order_id,
                "side": side,
                "price": price,
                "amount": amount,
                "quantity": amount,
                "state": "open",
                "trading_pair": str(order.get("trading_pair", trading_pair)),
                "is_estimated": False,
                "estimate_source": "paper_state_snapshot",
                "price_hint_source": "paper_state_snapshot",
                "updated_ts_ms": ts_ms,
            })
        return out
    except Exception:
        return []


def _build_runtime_open_order_placeholders(
    orders_active: int,
    best_bid: float | None,
    best_ask: float | None,
    mid_price: float | None,
    quantity: float | None,
    trading_pair: str = "",
    timestamp_ms: int | None = None,
    source_label: str = "runtime",
) -> list[dict[str, Any]]:
    count = max(0, int(orders_active or 0))
    if count <= 0:
        return []
    ts_ms = int(timestamp_ms or _now_ms())
    qty_abs = abs(float(quantity)) if quantity is not None else None
    pair = str(trading_pair or "")
    bid_hint = best_bid if best_bid is not None else mid_price
    ask_hint = best_ask if best_ask is not None else mid_price
    price_hint_source = "book" if best_bid is not None or best_ask is not None else "mid" if mid_price is not None else "none"
    out: list[dict[str, Any]] = []
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


def _build_gate_timeline(minute_rows: list[dict[str, Any]], max_segments: int = 200) -> list[dict[str, Any]]:
    safe_rows = [row for row in minute_rows if isinstance(row, dict)]
    safe_rows.sort(key=lambda row: int(row.get("timestamp_ms") or 0))
    if not safe_rows:
        return []
    segments: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
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
                        "start_ts": datetime.fromtimestamp(int(active["start_ts_ms"]) / 1000, tz=UTC).isoformat(),
                        "end_ts": datetime.fromtimestamp(int(active["end_ts_ms"]) / 1000, tz=UTC).isoformat(),
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
                "start_ts": datetime.fromtimestamp(int(active["start_ts_ms"]) / 1000, tz=UTC).isoformat(),
                "end_ts": datetime.fromtimestamp(int(active["end_ts_ms"]) / 1000, tz=UTC).isoformat(),
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
    risk_reasons: list[str],
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


def _sample_trade_path_points(window: list[dict[str, Any]], max_points: int = 120) -> list[dict[str, Any]]:
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


def _sample_trade_path_from_fills(fill_rows: list[dict[str, Any]], max_points: int = 120) -> list[dict[str, Any]]:
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
    trades: list[dict[str, Any]],
    minute_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    safe_minutes = [row for row in minute_rows if isinstance(row, dict)]
    safe_minutes.sort(key=lambda row: int(row.get("timestamp_ms") or 0))
    enriched: list[dict[str, Any]] = []
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
        risk_tags: list[str] = []
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
            best_quote: float | None = None
            worst_quote: float | None = None
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
            mfe_ts = datetime.fromtimestamp(best_ts / 1000, tz=UTC).isoformat() if best_ts > 0 else ""
            mae_ts = datetime.fromtimestamp(worst_ts / 1000, tz=UTC).isoformat() if worst_ts > 0 else ""
        elif qty > 0.0 and entry_price > 0.0 and direction != 0.0 and trade_fill_rows:
            best_quote: float | None = None
            worst_quote: float | None = None
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
            mfe_ts = datetime.fromtimestamp(best_ts / 1000, tz=UTC).isoformat() if best_ts > 0 else ""
            mae_ts = datetime.fromtimestamp(worst_ts / 1000, tz=UTC).isoformat() if worst_ts > 0 else ""
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


def _summarize_journal_review(trades: list[dict[str, Any]]) -> dict[str, Any]:
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
    entry_regime_breakdown: dict[str, int] = defaultdict(int)
    exit_reason_breakdown: dict[str, int] = defaultdict(int)
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


def _summarize_weekly_report(instance_name: str, report: dict[str, Any]) -> dict[str, Any]:
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


def _build_alerts(account_summary: dict[str, Any], system: dict[str, Any]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
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
    stale_threshold = int(system.get("stream_stale_threshold_ms") or 15_000)
    if stream_age_ms is not None and stream_age_ms > stale_threshold:
        alerts.append({"severity": "warn", "title": "Stream stale", "detail": f"Latest stream age {int(stream_age_ms)} ms (threshold {stale_threshold} ms)."})
    if bool(system.get("fallback_active")):
        alerts.append({"severity": "warn", "title": "Fallback active", "detail": "UI is relying on degraded snapshot or CSV fallback."})
    if not bool(system.get("redis_available", True)):
        alerts.append({"severity": "fail", "title": "Redis unavailable", "detail": "Realtime stream dependency is unavailable."})
    if not bool(system.get("db_available", True)):
        alerts.append({"severity": "warn", "title": "DB unavailable", "detail": "Historical read model is unavailable."})
    return alerts


def _summarize_daily_review(day_key: str, minute_rows: list[dict[str, Any]], fills: list[dict[str, Any]], account_summary: dict[str, Any]) -> dict[str, Any]:
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

    hourly: dict[int, dict[str, Any]] = {}
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


def _normalize_fill_activity_row(row: dict[str, Any], prefix: str) -> dict[str, Any]:
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
        "fees_quote": float(_to_float(row.get(f"{prefix}_fees_quote")) or 0.0),
        "avg_fill_size": float(_to_float(row.get(f"{prefix}_avg_fill_size")) or 0.0),
        "avg_fill_price": float(_to_float(row.get(f"{prefix}_avg_fill_price")) or 0.0),
    }


def _summarize_fill_activity(
    fills: list[dict[str, Any]],
    *,
    now_ms: int | None = None,
    fills_total: int = 0,
) -> dict[str, Any]:
    reference_ms = int(now_ms or _now_ms())
    latest_fill_ts_ms = 0
    windows: dict[str, tuple[int, dict[str, Any]]] = {
        "window_15m": (15 * 60 * 1000, _window_summary_template()),
        "window_1h": (60 * 60 * 1000, _window_summary_template()),
    }
    for fill in fills or []:
        if not isinstance(fill, dict):
            continue
        ts_ms = int(_to_epoch_ms(fill.get("timestamp_ms") or fill.get("ts_utc") or fill.get("ts")) or 0)
        if ts_ms <= 0:
            continue
        latest_fill_ts_ms = max(latest_fill_ts_ms, ts_ms)
        age_ms = max(0, reference_ms - ts_ms)
        side = str(fill.get("side", "")).strip().lower()
        amount_base = abs(float(_to_float(fill.get("amount_base") or fill.get("amount")) or 0.0))
        price = float(_to_float(fill.get("price")) or 0.0)
        realized_pnl = float(_to_float(fill.get("realized_pnl_quote")) or 0.0)
        fee_quote = float(_to_float(fill.get("fee_quote")) or 0.0)
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
            bucket["fees_quote"] += fee_quote
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
        for key in ("volume_base", "notional_quote", "realized_pnl_quote", "fees_quote", "avg_fill_size", "avg_fill_price"):
            bucket[key] = round(float(bucket[key]), 8)
        bucket["maker_ratio"] = round(float(bucket["maker_ratio"]), 6)
    return {
        "fills_total": max(int(fills_total or 0), len(fills or [])),
        "latest_fill_ts_ms": latest_fill_ts_ms,
        "window_15m": windows["window_15m"][1],
        "window_1h": windows["window_1h"][1],
    }


def _merge_activity_window(db_window: dict[str, Any], stream_window: dict[str, Any]) -> dict[str, Any]:
    """Merge a DB-sourced activity window with a stream-sourced one.

    The DB batch-ingests from CSV periodically, so recent fills may be missing.
    Stream fills are real-time but only cover the current session.  Take the
    source with the higher fill count for each window so the UI never shows
    stale zeros while real-time fills are available.
    """
    db_count = int(db_window.get("fill_count") or 0)
    stream_count = int(stream_window.get("fill_count") or 0)
    if stream_count > db_count:
        return dict(stream_window)
    return dict(db_window)


def _merge_fill_activity(db_activity: dict[str, Any], stream_activity: dict[str, Any]) -> dict[str, Any]:
    """Merge DB and stream fill activity, preferring the richer source per window."""
    db_w15 = db_activity.get("window_15m", {}) if isinstance(db_activity.get("window_15m"), dict) else {}
    db_w1h = db_activity.get("window_1h", {}) if isinstance(db_activity.get("window_1h"), dict) else {}
    st_w15 = stream_activity.get("window_15m", {}) if isinstance(stream_activity.get("window_15m"), dict) else {}
    st_w1h = stream_activity.get("window_1h", {}) if isinstance(stream_activity.get("window_1h"), dict) else {}
    return {
        "fills_total": max(
            int(db_activity.get("fills_total") or 0),
            int(stream_activity.get("fills_total") or 0),
        ),
        "latest_fill_ts_ms": max(
            int(db_activity.get("latest_fill_ts_ms") or 0),
            int(stream_activity.get("latest_fill_ts_ms") or 0),
        ),
        "realized_pnl_total_quote": float(
            stream_activity.get("realized_pnl_total_quote")
            or db_activity.get("realized_pnl_total_quote")
            or 0.0
        ),
        "window_15m": _merge_activity_window(db_w15, st_w15),
        "window_1h": _merge_activity_window(db_w1h, st_w1h),
    }


def _state_key(payload: dict[str, Any]) -> tuple[str, str, str]:
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
    use_csv_for_operator_api: bool = field(
        default_factory=lambda: os.getenv("REALTIME_UI_API_USE_CSV", "false").strip().lower()
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
    history_ui_read_mode: str = field(
        default_factory=lambda: os.getenv("HB_HISTORY_UI_READ_MODE", "legacy").strip().lower()
    )

    def normalized_mode(self) -> str:
        if self.mode not in {"disabled", "shadow", "active"}:
            return "disabled"
        return self.mode

    def normalized_history_ui_read_mode(self) -> str:
        if self.history_ui_read_mode not in {"legacy", "shadow", "shared"}:
            return "legacy"
        return self.history_ui_read_mode


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


# ---------------------------------------------------------------------------
# Backward-compat re-exports — callers that import from _helpers still work.
# ---------------------------------------------------------------------------
from services.realtime_ui_api.review_builders import (  # noqa: E402, F811
    _build_alerts as _build_alerts,
    _build_bot_gates as _build_bot_gates,
    _build_gate_timeline as _build_gate_timeline,
    _build_quote_gate_summary as _build_quote_gate_summary,
    _build_runtime_open_order_placeholders as _build_runtime_open_order_placeholders,
    _build_trade_fill_contribution as _build_trade_fill_contribution,
    _daily_review_template as _daily_review_template,
    _day_bounds_utc as _day_bounds_utc,
    _derive_gate_status as _derive_gate_status,
    _enrich_closed_trades_with_minute_context as _enrich_closed_trades_with_minute_context,
    _infer_trade_exit_reason as _infer_trade_exit_reason,
    _journal_review_template as _journal_review_template,
    _merge_activity_window as _merge_activity_window,
    _merge_fill_activity as _merge_fill_activity,
    _nearest_context_row as _nearest_context_row,
    _normalize_fill_activity_row as _normalize_fill_activity_row,
    _read_paper_exchange_active_orders as _read_paper_exchange_active_orders,
    _reconstruct_closed_trades as _reconstruct_closed_trades,
    _sample_trade_path_from_fills as _sample_trade_path_from_fills,
    _sample_trade_path_points as _sample_trade_path_points,
    _split_risk_reasons as _split_risk_reasons,
    _summarize_daily_review as _summarize_daily_review,
    _summarize_fill_activity as _summarize_fill_activity,
    _summarize_journal_review as _summarize_journal_review,
    _summarize_weekly_report as _summarize_weekly_report,
    _sync_account_summary_with_open_orders as _sync_account_summary_with_open_orders,
    _weekly_review_template as _weekly_review_template,
)
from services.realtime_ui_api.api_config import (  # noqa: E402, F811
    RealtimeApiConfig as RealtimeApiConfig,
    _is_loopback_host as _is_loopback_host,
    _state_key as _state_key,
    _validate_runtime_config as _validate_runtime_config,
)
