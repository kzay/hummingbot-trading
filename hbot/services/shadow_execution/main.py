from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from services.common.log_namespace import iter_bot_log_files
from services.common.activity_scope import active_bots_from_minute_logs
from services.common.utils import (
    safe_bool as _safe_bool,
    safe_float as _safe_float,
    today_utc as _today,
    utc_now as _utc_now,
)


def _to_ms(value: object) -> Optional[int]:
    if value in (None, ""):
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.isdigit():
            return int(s)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _read_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _read_latest_csv_row(path: Path) -> Optional[Dict[str, str]]:
    if not path.exists():
        return None
    latest: Optional[Dict[str, str]] = None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if isinstance(row, dict):
                    latest = row
    except Exception:
        return None
    return latest


def _load_controller_market_rows(data_root: Path) -> Dict[str, Dict[str, object]]:
    rows: Dict[str, Dict[str, object]] = {}
    for minute_file in iter_bot_log_files(data_root, "minute.csv"):
        try:
            bot = minute_file.parts[-5]
        except Exception:
            continue
        latest = _read_latest_csv_row(minute_file)
        if not latest:
            continue
        rows[bot] = {
            "minute_path": str(minute_file),
            "ts": str(latest.get("ts", "")),
            "connector_name": str(latest.get("connector_name", latest.get("exchange", ""))),
            "trading_pair": str(latest.get("trading_pair", "")),
            "mid": _safe_float(latest.get("mid"), 0.0),
            "best_bid": _safe_float(latest.get("best_bid"), 0.0),
            "best_ask": _safe_float(latest.get("best_ask"), 0.0),
            "spread_pct": _safe_float(latest.get("spread_pct"), 0.0),
            "state": str(latest.get("state", "")),
        }
    return rows


def _load_latest_fill_rows(data_root: Path) -> Dict[str, Dict[str, object]]:
    rows: Dict[str, Dict[str, object]] = {}
    for fills_file in iter_bot_log_files(data_root, "fills.csv"):
        try:
            bot = fills_file.parts[-5]
        except Exception:
            continue
        latest = _read_latest_csv_row(fills_file)
        if not latest:
            continue
        rows[bot] = {
            "fills_path": str(fills_file),
            "ts": str(latest.get("ts", latest.get("timestamp", ""))),
            "side": str(latest.get("side", "")),
            "price": _safe_float(latest.get("price"), 0.0),
            "mid_ref": _safe_float(latest.get("mid_ref"), 0.0),
            "fee_quote": _safe_float(latest.get("fee_quote"), 0.0),
            "is_maker": str(latest.get("is_maker", "")),
        }
    return rows


def _load_latest_stream_market_rows(event_path: Path) -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}
    if not event_path.exists():
        return out
    try:
        with event_path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = str(event.get("event_type", "")).strip().lower()
                if event_type not in {"market_quote", "market_depth_snapshot"}:
                    continue
                bot = str(event.get("instance_name", "")).strip()
                if not bot:
                    continue
                payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else event
                ts_ms = _to_ms(payload.get("timestamp_ms")) or _to_ms(event.get("ts_utc")) or 0
                prev_ts = int(out.get(bot, {}).get("timestamp_ms", 0) or 0)
                if ts_ms < prev_ts:
                    continue
                out[bot] = {
                    "event_type": event_type,
                    "timestamp_ms": ts_ms,
                    "connector_name": str(payload.get("connector_name", "")),
                    "trading_pair": str(payload.get("trading_pair", "")),
                    "mid_price": _safe_float(payload.get("mid_price"), 0.0),
                    "best_bid": _safe_float(payload.get("best_bid"), 0.0),
                    "best_ask": _safe_float(payload.get("best_ask"), 0.0),
                    "best_bid_size": _safe_float(payload.get("best_bid_size"), 0.0),
                    "best_ask_size": _safe_float(payload.get("best_ask_size"), 0.0),
                    "exchange_ts_ms": _to_ms(payload.get("exchange_ts_ms")) or 0,
                    "ingest_ts_ms": _to_ms(payload.get("ingest_ts_ms")) or 0,
                    "market_sequence": int(_safe_float(payload.get("market_sequence"), 0.0)),
                }
    except Exception:
        return out
    return out


def _load_paper_service_pair_rows(path: Path) -> Dict[str, Dict[str, object]]:
    payload = _read_json(path, {})
    raw_pairs = payload.get("pairs", {})
    if not isinstance(raw_pairs, dict):
        return {}
    out: Dict[str, Dict[str, object]] = {}
    for row in raw_pairs.values():
        if not isinstance(row, dict):
            continue
        bot = str(row.get("instance_name", "")).strip()
        if not bot:
            continue
        out[bot] = {
            "connector_name": str(row.get("connector_name", "")),
            "trading_pair": str(row.get("trading_pair", "")),
            "timestamp_ms": _to_ms(row.get("timestamp_ms")) or 0,
            "freshness_ts_ms": _to_ms(row.get("freshness_ts_ms")) or 0,
            "mid_price": _safe_float(row.get("mid_price"), 0.0),
            "best_bid": _safe_float(row.get("best_bid"), 0.0),
            "best_ask": _safe_float(row.get("best_ask"), 0.0),
            "best_bid_size": _safe_float(row.get("best_bid_size"), 0.0),
            "best_ask_size": _safe_float(row.get("best_ask_size"), 0.0),
            "source_event_type": str(row.get("source_event_type", "")),
            "market_sequence": int(_safe_float(row.get("market_sequence"), 0.0)),
        }
    return out


def _load_thresholds(path: Path) -> Dict[str, object]:
    default = {
        "version": 1,
        "defaults": {
            "enabled": True,
            "fail_closed_for_active_bots": True,
            "min_actionable_intents_for_core": 1,
            "min_fills_for_slippage": 1,
            "expected_fill_ratio": 0.0,
            "max_fill_ratio_delta": 0.25,
            "expected_slippage_bps": 2.0,
            "max_slippage_delta_bps": 5.0,
            "expected_reject_rate": 0.0,
            "max_reject_rate_delta": 0.20,
            "expected_realized_pnl_quote": 0.0,
            "max_realized_pnl_delta_quote": 500.0,
        },
        "bots": {},
    }
    payload = _read_json(path, default)
    defaults = payload.get("defaults", default["defaults"]) if isinstance(payload.get("defaults"), dict) else default["defaults"]
    bots = payload.get("bots", {}) if isinstance(payload.get("bots"), dict) else {}
    return {"version": payload.get("version", 1), "defaults": defaults, "bots": bots}


def _bot_cfg(cfg: Dict[str, object], bot: str) -> Dict[str, float]:
    defaults = cfg.get("defaults", {}) if isinstance(cfg.get("defaults"), dict) else {}
    bots = cfg.get("bots", {}) if isinstance(cfg.get("bots"), dict) else {}
    row = bots.get(bot, {}) if isinstance(bots.get(bot, {}), dict) else {}
    return {
        "enabled": _safe_bool(row.get("enabled"), _safe_bool(defaults.get("enabled"), True)),
        "fail_closed_for_active_bots": _safe_bool(
            row.get("fail_closed_for_active_bots"), _safe_bool(defaults.get("fail_closed_for_active_bots"), True)
        ),
        "min_actionable_intents_for_core": max(
            1,
            int(
                _safe_float(
                    row.get("min_actionable_intents_for_core"),
                    _safe_float(defaults.get("min_actionable_intents_for_core"), 1),
                )
            ),
        ),
        "min_fills_for_slippage": max(
            1,
            int(_safe_float(row.get("min_fills_for_slippage"), _safe_float(defaults.get("min_fills_for_slippage"), 1))),
        ),
        "expected_fill_ratio": _safe_float(row.get("expected_fill_ratio"), _safe_float(defaults.get("expected_fill_ratio"), 0.0)),
        "max_fill_ratio_delta": _safe_float(row.get("max_fill_ratio_delta"), _safe_float(defaults.get("max_fill_ratio_delta"), 0.25)),
        "expected_slippage_bps": _safe_float(row.get("expected_slippage_bps"), _safe_float(defaults.get("expected_slippage_bps"), 2.0)),
        "max_slippage_delta_bps": _safe_float(
            row.get("max_slippage_delta_bps"), _safe_float(defaults.get("max_slippage_delta_bps"), 5.0)
        ),
        "expected_reject_rate": _safe_float(row.get("expected_reject_rate"), _safe_float(defaults.get("expected_reject_rate"), 0.0)),
        "max_reject_rate_delta": _safe_float(
            row.get("max_reject_rate_delta"), _safe_float(defaults.get("max_reject_rate_delta"), 0.20)
        ),
        "expected_realized_pnl_quote": _safe_float(
            row.get("expected_realized_pnl_quote"), _safe_float(defaults.get("expected_realized_pnl_quote"), 0.0)
        ),
        "max_realized_pnl_delta_quote": _safe_float(
            row.get("max_realized_pnl_delta_quote"), _safe_float(defaults.get("max_realized_pnl_delta_quote"), 500.0)
        ),
    }


def _read_minute_equity_series(
    path: Path, now_ms: int, lookback_min: int
) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    if not path.exists():
        return None, None, None
    first: Optional[float] = None
    last: Optional[float] = None
    last_ts: Optional[int] = None
    min_ts = now_ms - max(1, lookback_min) * 60 * 1000
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_ms = _to_ms(row.get("ts"))
                if ts_ms is None or ts_ms < min_ts:
                    continue
                v = _safe_float(row.get("equity_quote"), float("nan"))
                if v != v:
                    continue
                if first is None:
                    first = v
                last = v
                last_ts = ts_ms
    except Exception:
        return None, None, None
    return first, last, last_ts


def _latest_market_mid(markets: List[Tuple[int, float]], ts_ms: int) -> Optional[float]:
    best: Optional[float] = None
    best_ts = -1
    for item_ts, mid in markets:
        if item_ts <= ts_ms and item_ts > best_ts:
            best_ts = item_ts
            best = mid
    return best


def _metric_result(
    name: str,
    value: Optional[float],
    expected: float,
    max_abs_delta: float,
    *,
    informative: bool,
    fail_when_missing: bool,
) -> Dict[str, object]:
    if value is None or not informative:
        return {
            "metric": name,
            "value": None,
            "expected": expected,
            "delta": None,
            "max_abs_delta": max_abs_delta,
            "pass": not fail_when_missing,
            "note": "insufficient_data",
        }
    delta = value - expected
    return {
        "metric": name,
        "value": value,
        "expected": expected,
        "delta": delta,
        "max_abs_delta": max_abs_delta,
        "pass": abs(delta) <= max_abs_delta,
    }


def _compute_bot_parity(
    bot: str,
    metrics: Dict[str, object],
    cfg: Dict[str, float],
    *,
    active_window: bool,
) -> Dict[str, object]:
    intents_total = int(metrics.get("intents_total", 0))
    actionable_intents = int(metrics.get("actionable_intents", 0))
    fills_total = int(metrics.get("fills_total", 0))
    order_failed_total = int(metrics.get("order_failed_total", 0))
    denied_risk_total = int(metrics.get("risk_denied_total", 0))

    fill_ratio_realized: Optional[float] = None
    if actionable_intents > 0:
        fill_ratio_realized = fills_total / actionable_intents

    denom = fills_total + order_failed_total
    reject_rate_realized: Optional[float] = None
    if denom > 0:
        reject_rate_realized = order_failed_total / denom

    slippage_samples = metrics.get("slippage_samples_bps", [])
    slippage_realized: Optional[float] = None
    if isinstance(slippage_samples, list) and slippage_samples:
        slippage_realized = sum(float(x) for x in slippage_samples) / len(slippage_samples)

    first_eq = metrics.get("equity_first")
    last_eq = metrics.get("equity_last")
    pnl_realized: Optional[float] = None
    if isinstance(first_eq, float) and isinstance(last_eq, float):
        pnl_realized = last_eq - first_eq

    min_actionable = max(1, int(cfg.get("min_actionable_intents_for_core", 1)))
    min_fills_for_slippage = max(1, int(cfg.get("min_fills_for_slippage", 1)))
    fail_closed = bool(cfg.get("fail_closed_for_active_bots", True))
    fill_ratio_informative = actionable_intents >= min_actionable
    reject_informative = denom >= min_actionable
    slippage_informative = fills_total >= min_fills_for_slippage and isinstance(slippage_samples, list) and bool(slippage_samples)
    pnl_informative = isinstance(first_eq, float) and isinstance(last_eq, float)

    rows = [
        _metric_result(
            name="fill_ratio_delta",
            value=fill_ratio_realized,
            expected=cfg["expected_fill_ratio"],
            max_abs_delta=cfg["max_fill_ratio_delta"],
            informative=fill_ratio_informative,
            fail_when_missing=bool(active_window and fail_closed),
        ),
        _metric_result(
            name="slippage_delta_bps",
            value=slippage_realized,
            expected=cfg["expected_slippage_bps"],
            max_abs_delta=cfg["max_slippage_delta_bps"],
            informative=slippage_informative,
            fail_when_missing=bool(active_window and fail_closed),
        ),
        _metric_result(
            name="reject_rate_delta",
            value=reject_rate_realized,
            expected=cfg["expected_reject_rate"],
            max_abs_delta=cfg["max_reject_rate_delta"],
            informative=reject_informative,
            fail_when_missing=bool(active_window and fail_closed),
        ),
        _metric_result(
            name="realized_pnl_delta_quote",
            value=pnl_realized,
            expected=cfg["expected_realized_pnl_quote"],
            max_abs_delta=cfg["max_realized_pnl_delta_quote"],
            informative=pnl_informative,
            fail_when_missing=False,
        ),
    ]

    passed = all(bool(r.get("pass")) for r in rows)
    return {
        "bot": bot,
        "pass": passed,
        "summary": {
            "intents_total": intents_total,
            "actionable_intents": actionable_intents,
            "fills_total": fills_total,
            "order_failed_total": order_failed_total,
            "risk_denied_total": denied_risk_total,
            "equity_first": first_eq,
            "equity_last": last_eq,
            "active_window": bool(active_window),
            "fill_ratio_informative": bool(fill_ratio_informative),
            "slippage_informative": bool(slippage_informative),
            "reject_rate_informative": bool(reject_informative),
            "fail_closed_for_active_bots": bool(fail_closed),
        },
        "metrics": rows,
    }


def _build_drift_audit(
    *,
    today: str,
    parity_report: Dict[str, object],
    reconciliation: Dict[str, object],
    active_bots: Dict[str, Dict[str, object]],
    data_root: Path,
    event_path: Path,
    pair_snapshot_path: Path,
) -> Dict[str, object]:
    controller_rows = _load_controller_market_rows(data_root)
    latest_fill_rows = _load_latest_fill_rows(data_root)
    stream_rows = _load_latest_stream_market_rows(event_path)
    pair_rows = _load_paper_service_pair_rows(pair_snapshot_path)
    reconciliation_findings = reconciliation.get("findings", [])
    recon_by_bot: Dict[str, List[Dict[str, object]]] = {}
    if isinstance(reconciliation_findings, list):
        for finding in reconciliation_findings:
            if not isinstance(finding, dict):
                continue
            bot = str(finding.get("bot", "")).strip()
            if not bot:
                continue
            recon_by_bot.setdefault(bot, []).append(finding)

    drift_rows: List[Dict[str, object]] = []
    for row in parity_report.get("bots", []):
        if not isinstance(row, dict):
            continue
        bot = str(row.get("bot", "")).strip()
        metrics = row.get("metrics", [])
        metric_map = {
            str(metric.get("metric", "")).strip(): metric
            for metric in metrics
            if isinstance(metric, dict)
        } if isinstance(metrics, list) else {}
        summary = row.get("summary", {}) if isinstance(row.get("summary"), dict) else {}
        controller_row = controller_rows.get(bot, {})
        stream_row = stream_rows.get(bot, {})
        pair_row = pair_rows.get(bot, {})
        fill_row = latest_fill_rows.get(bot, {})
        buckets: List[str] = []
        if str(metric_map.get("fill_ratio_delta", {}).get("note", "")) == "insufficient_data":
            buckets.append("fill_path_insufficient_evidence")
        if str(metric_map.get("slippage_delta_bps", {}).get("note", "")) == "insufficient_data":
            buckets.append("market_data_or_fill_alignment_insufficient")
        if any(not bool(metric.get("pass")) for metric in metric_map.values() if isinstance(metric, dict)):
            buckets.append("parity_threshold_breach")
        if bot in recon_by_bot:
            buckets.append("reconciliation_findings_present")
        if bot in active_bots and not bool(summary.get("active_window")):
            buckets.append("active_bot_scope_mismatch")
        controller_mid = _safe_float(controller_row.get("mid"), 0.0)
        stream_mid = _safe_float(stream_row.get("mid_price"), 0.0)
        pair_mid = _safe_float(pair_row.get("mid_price"), 0.0)
        if controller_mid > 0 and stream_mid > 0 and abs(controller_mid - stream_mid) / max(abs(stream_mid), 1.0) > 0.0005:
            buckets.append("market_data_drift")
        if stream_mid > 0 and pair_mid > 0 and abs(stream_mid - pair_mid) / max(abs(stream_mid), 1.0) > 0.0005:
            buckets.append("fill_model_drift")
        if _safe_float(fill_row.get("fee_quote"), 0.0) < 0:
            buckets.append("fee_accounting_drift")
        if pair_row and pair_row.get("source_event_type") == "market_snapshot":
            buckets.append("restart_state_drift")
        drift_rows.append(
            {
                "bot": bot,
                "pass": bool(row.get("pass")),
                "buckets": buckets,
                "summary": summary,
                "metrics": metrics,
                "controller_local": controller_row,
                "canonical_stream": stream_row,
                "paper_service_snapshot": pair_row,
                "latest_fill": fill_row,
                "reconciliation_findings": recon_by_bot.get(bot, []),
                "minute_log_activity": active_bots.get(bot, {}),
            }
        )

    return {
        "ts_utc": _utc_now(),
        "status": parity_report.get("status", "fail"),
        "day_utc": today,
        "reconciliation_status": reconciliation.get("status", "unknown"),
        "active_bots": sorted(active_bots.keys()),
        "event_store_file": str(event_path),
        "paper_pair_snapshot_path": str(pair_snapshot_path),
        "bots": drift_rows,
    }


def run(once: bool = False) -> None:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports_root = root / "reports" / "parity"
    reports_root.mkdir(parents=True, exist_ok=True)
    data_root = Path(os.getenv("HB_DATA_ROOT", str(root / "data")))
    active_bot_window_min = max(1, int(os.getenv("PARITY_ACTIVE_BOT_WINDOW_MIN", "30")))
    interval_sec = int(os.getenv("PARITY_INTERVAL_SEC", "300"))
    pnl_lookback_min = int(os.getenv("PARITY_PNL_LOOKBACK_MIN", "180"))
    thresholds_path = Path(os.getenv("PARITY_THRESHOLDS_PATH", str(root / "config" / "parity_thresholds.json")))
    reconciliation_path = Path(
        os.getenv("PARITY_RECONCILIATION_PATH", str(root / "reports" / "reconciliation" / "latest.json"))
    )
    pair_snapshot_path = Path(
        os.getenv(
            "PARITY_PAPER_PAIR_SNAPSHOT_PATH",
            str(root / "reports" / "verification" / "paper_exchange_pair_snapshot_latest.json"),
        )
    )

    while True:
        cfg = _load_thresholds(thresholds_path)
        today = _today()
        event_path = root / "reports" / "event_store" / f"events_{today}.jsonl"
        reconciliation = _read_json(reconciliation_path, {})
        active_bots = active_bots_from_minute_logs(data_root, active_within_minutes=active_bot_window_min)

        per_bot: Dict[str, Dict[str, object]] = {}
        for bot, activity in active_bots.items():
            per_bot[bot] = {
                "intents_total": 0,
                "actionable_intents": 0,
                "fills_total": 0,
                "order_failed_total": 0,
                "risk_denied_total": 0,
                "slippage_samples_bps": [],
                "markets": [],
                "minute_log_activity": activity,
            }

        if event_path.exists():
            try:
                with event_path.open("r", encoding="utf-8") as f:
                    for raw in f:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            event = json.loads(raw)
                        except Exception:
                            continue
                        bot = str(event.get("instance_name") or "").strip()
                        if not bot:
                            continue
                        if bot not in per_bot:
                            per_bot[bot] = {
                                "intents_total": 0,
                                "actionable_intents": 0,
                                "fills_total": 0,
                                "order_failed_total": 0,
                                "risk_denied_total": 0,
                                "slippage_samples_bps": [],
                                "markets": [],
                            }

                        row = per_bot[bot]
                        event_type = str(event.get("event_type") or "").strip()
                        stream_name = str(event.get("stream") or "").strip()
                        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
                        ts_ms = _to_ms(payload.get("timestamp_ms")) or _to_ms(event.get("ts_utc")) or 0

                        if event_type == "market_snapshot":
                            mid = _safe_float(payload.get("mid_price"), 0.0)
                            if mid > 0 and ts_ms > 0:
                                row["markets"].append((ts_ms, mid))
                        elif event_type == "execution_intent":
                            row["intents_total"] = int(row.get("intents_total", 0)) + 1
                            action = str(payload.get("action") or "").strip().lower()
                            if action and action not in {"soft_pause", "hard_stop", "hold", "noop"}:
                                row["actionable_intents"] = int(row.get("actionable_intents", 0)) + 1
                        elif event_type == "order_filled":
                            # local.backfill is synthetic replay coverage, not real execution
                            # evidence for parity intent/fill ratio gates.
                            if stream_name == "local.backfill":
                                continue
                            row["fills_total"] = int(row.get("fills_total", 0)) + 1
                            fill_price = _safe_float(payload.get("fill_price"), _safe_float(payload.get("price"), 0.0))
                            if fill_price > 0 and ts_ms > 0:
                                markets = row.get("markets", [])
                                if isinstance(markets, list):
                                    ref = _latest_market_mid(markets, ts_ms)
                                    if ref and ref > 0:
                                        bps = abs((fill_price - ref) / ref) * 10000.0
                                        row["slippage_samples_bps"].append(bps)
                        elif event_type == "order_failed":
                            row["order_failed_total"] = int(row.get("order_failed_total", 0)) + 1
                        elif event_type == "risk_decision":
                            approved = _safe_bool(payload.get("approved"), True)
                            if not approved:
                                row["risk_denied_total"] = int(row.get("risk_denied_total", 0)) + 1
            except Exception:
                pass

        # Add equity path from minute.csv for realized PnL proxy.
        now_ms = int(time.time() * 1000)
        for minute_file in iter_bot_log_files(data_root, "minute.csv"):
            bot = minute_file.parts[-5]
            if bot not in per_bot:
                per_bot[bot] = {
                    "intents_total": 0,
                    "actionable_intents": 0,
                    "fills_total": 0,
                    "order_failed_total": 0,
                    "risk_denied_total": 0,
                    "slippage_samples_bps": [],
                    "markets": [],
                }
            first_eq, last_eq, last_ts = _read_minute_equity_series(
                minute_file, now_ms=now_ms, lookback_min=pnl_lookback_min
            )
            if first_eq is None or last_eq is None or last_ts is None:
                continue
            prev_ts = per_bot[bot].get("equity_last_ts")
            if isinstance(prev_ts, int) and prev_ts > last_ts:
                continue
            per_bot[bot]["equity_first"] = first_eq
            per_bot[bot]["equity_last"] = last_eq
            per_bot[bot]["equity_last_ts"] = last_ts

        bot_reports: List[Dict[str, object]] = []
        for bot in sorted(per_bot.keys()):
            bcfg = _bot_cfg(cfg, bot)
            if not bcfg["enabled"]:
                continue
            bot_reports.append(
                _compute_bot_parity(
                    bot=bot,
                    metrics=per_bot[bot],
                    cfg=bcfg,
                    active_window=bot in active_bots,
                )
            )

        fail_count = sum(1 for row in bot_reports if not bool(row.get("pass")))
        status = "fail" if fail_count > 0 else "pass"

        report = {
            "ts_utc": _utc_now(),
            "status": status,
            "failed_bots": fail_count,
            "checked_bots": len(bot_reports),
            "event_store_file": str(event_path),
            "reconciliation_status": reconciliation.get("status", "unknown"),
            "thresholds_path": str(thresholds_path),
            "thresholds_version": cfg.get("version", 1),
            "active_bot_window_min": active_bot_window_min,
            "active_bots": sorted(active_bots.keys()),
            "bots": bot_reports,
        }
        drift_audit = _build_drift_audit(
            today=today,
            parity_report=report,
            reconciliation=reconciliation,
            active_bots=active_bots,
            data_root=data_root,
            event_path=event_path,
            pair_snapshot_path=pair_snapshot_path,
        )

        day_dir = reports_root / today
        day_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = day_dir / f"parity_{stamp}.json"
        drift_out_path = day_dir / f"drift_audit_{stamp}.json"
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        drift_out_path.write_text(json.dumps(drift_audit, indent=2), encoding="utf-8")
        (reports_root / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (reports_root / "drift_audit_latest.json").write_text(json.dumps(drift_audit, indent=2), encoding="utf-8")

        if once:
            break
        time.sleep(max(30, interval_sec))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single parity cycle and exit.")
    args = parser.parse_args()
    run(once=args.once)
