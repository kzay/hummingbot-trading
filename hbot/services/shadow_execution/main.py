from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


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


def _load_thresholds(path: Path) -> Dict[str, object]:
    default = {
        "version": 1,
        "defaults": {
            "enabled": True,
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


def _metric_result(name: str, value: Optional[float], expected: float, max_abs_delta: float) -> Dict[str, object]:
    if value is None:
        return {
            "metric": name,
            "value": None,
            "expected": expected,
            "delta": None,
            "max_abs_delta": max_abs_delta,
            "pass": True,
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

    rows = [
        _metric_result(
            name="fill_ratio_delta",
            value=fill_ratio_realized,
            expected=cfg["expected_fill_ratio"],
            max_abs_delta=cfg["max_fill_ratio_delta"],
        ),
        _metric_result(
            name="slippage_delta_bps",
            value=slippage_realized,
            expected=cfg["expected_slippage_bps"],
            max_abs_delta=cfg["max_slippage_delta_bps"],
        ),
        _metric_result(
            name="reject_rate_delta",
            value=reject_rate_realized,
            expected=cfg["expected_reject_rate"],
            max_abs_delta=cfg["max_reject_rate_delta"],
        ),
        _metric_result(
            name="realized_pnl_delta_quote",
            value=pnl_realized,
            expected=cfg["expected_realized_pnl_quote"],
            max_abs_delta=cfg["max_realized_pnl_delta_quote"],
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
        },
        "metrics": rows,
    }


def run(once: bool = False) -> None:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports_root = root / "reports" / "parity"
    reports_root.mkdir(parents=True, exist_ok=True)
    data_root = Path(os.getenv("HB_DATA_ROOT", str(root / "data")))
    interval_sec = int(os.getenv("PARITY_INTERVAL_SEC", "300"))
    pnl_lookback_min = int(os.getenv("PARITY_PNL_LOOKBACK_MIN", "180"))
    thresholds_path = Path(os.getenv("PARITY_THRESHOLDS_PATH", str(root / "config" / "parity_thresholds.json")))
    reconciliation_path = Path(
        os.getenv("PARITY_RECONCILIATION_PATH", str(root / "reports" / "reconciliation" / "latest.json"))
    )

    while True:
        cfg = _load_thresholds(thresholds_path)
        today = _today()
        event_path = root / "reports" / "event_store" / f"events_{today}.jsonl"
        reconciliation = _read_json(reconciliation_path, {})

        per_bot: Dict[str, Dict[str, object]] = {}

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
                            row["fills_total"] = int(row.get("fills_total", 0)) + 1
                            fill_price = _safe_float(payload.get("fill_price"), 0.0)
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
        for minute_file in data_root.glob("*/logs/epp_v24/*/minute.csv"):
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
            bot_reports.append(_compute_bot_parity(bot=bot, metrics=per_bot[bot], cfg=bcfg))

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
            "bots": bot_reports,
        }

        day_dir = reports_root / today
        day_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = day_dir / f"parity_{stamp}.json"
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        (reports_root / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

        if once:
            break
        time.sleep(max(30, interval_sec))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single parity cycle and exit.")
    args = parser.parse_args()
    run(once=args.once)
