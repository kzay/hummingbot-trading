from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen


from services.common.utils import (
    count_csv_rows as _count_csv_rows,
    read_last_csv_row as _read_last_csv_row,
    read_last_n_csv_rows as _read_last_n_csv_rows,
    safe_bool as _safe_bool,
    safe_float as _safe_float,
    today_utc as _today,
    utc_now as _utc_now,
)


def _count_event_fills(path: Path, bot: str) -> int:
    if not path.exists():
        return 0
    count = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                if str(event.get("event_type")) != "order_filled":
                    continue
                if str(event.get("instance_name", "")) != bot:
                    continue
                count += 1
    except Exception:
        return count
    return count


def _severity(level: str, check_name: str, message: str, bot: str, details: Dict[str, object]) -> Dict[str, object]:
    return {
        "severity": level,
        "check": check_name,
        "message": message,
        "bot": bot,
        "details": details,
    }


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _alert_rank(level: str) -> int:
    return {"ok": 0, "warning": 1, "critical": 2}.get(level, 0)


def _emit_webhook_alert(report: Dict[str, object], webhook_url: str, min_severity: str) -> bool:
    status = str(report.get("status", "ok"))
    if _alert_rank(status) < _alert_rank(min_severity):
        return False
    payload = {
        "source": "reconciliation_service",
        "status": status,
        "critical_count": int(report.get("critical_count", 0)),
        "warning_count": int(report.get("warning_count", 0)),
        "ts_utc": report.get("ts_utc"),
        "findings": report.get("findings", []),
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = Request(webhook_url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=5) as resp:
            return int(getattr(resp, "status", 500)) < 300
    except Exception:
        return False


def _apply_exchange_snapshot_check(
    findings: List[Dict[str, object]],
    bot: str,
    base_pct: float,
    exchange_snapshot_path: Path,
    exchange_warn: float,
    exchange_critical: float,
) -> None:
    if not exchange_snapshot_path.exists():
        findings.append(
            _severity(
                "warning",
                "exchange_snapshot",
                "exchange_snapshot_missing",
                bot,
                {"path": str(exchange_snapshot_path)},
            )
        )
        return
    try:
        snap = json.loads(exchange_snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        findings.append(
            _severity(
                "warning",
                "exchange_snapshot",
                "exchange_snapshot_unreadable",
                bot,
                {"path": str(exchange_snapshot_path)},
            )
        )
        return
    bot_key = str(bot)
    bot_snap = snap.get("bots", {}).get(bot_key, {})
    exchange_base_pct = _safe_float(bot_snap.get("base_pct"), base_pct)
    drift = abs(base_pct - exchange_base_pct)
    if drift >= exchange_critical:
        findings.append(
            _severity(
                "critical",
                "exchange_snapshot",
                "exchange_vs_local_base_pct_drift_critical",
                bot,
                {
                    "local_base_pct": base_pct,
                    "exchange_base_pct": exchange_base_pct,
                    "drift": drift,
                    "warn_threshold": exchange_warn,
                    "critical_threshold": exchange_critical,
                },
            )
        )
    elif drift >= exchange_warn:
        findings.append(
            _severity(
                "warning",
                "exchange_snapshot",
                "exchange_vs_local_base_pct_drift_warning",
                bot,
                {
                    "local_base_pct": base_pct,
                    "exchange_base_pct": exchange_base_pct,
                    "drift": drift,
                    "warn_threshold": exchange_warn,
                    "critical_threshold": exchange_critical,
                },
            )
        )


def _load_thresholds(path: Path) -> Dict[str, object]:
    default = {
        "defaults": {
            "inventory_warn": 0.25,
            "inventory_critical": 0.45,
            "exchange_drift_warn": 0.10,
            "exchange_drift_critical": 0.20,
        },
        "bots": {},
    }
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return default
        return {
            "defaults": payload.get("defaults", default["defaults"]),
            "bots": payload.get("bots", {}),
        }
    except Exception:
        return default


def _bot_thresholds(cfg: Dict[str, object], bot: str) -> Dict[str, float]:
    defaults = cfg.get("defaults", {}) if isinstance(cfg.get("defaults"), dict) else {}
    bots = cfg.get("bots", {}) if isinstance(cfg.get("bots"), dict) else {}
    row = bots.get(bot, {}) if isinstance(bots.get(bot, {}), dict) else {}
    return {
        "inventory_warn": _safe_float(row.get("inventory_warn"), _safe_float(defaults.get("inventory_warn"), 0.25)),
        "inventory_critical": _safe_float(
            row.get("inventory_critical"), _safe_float(defaults.get("inventory_critical"), 0.45)
        ),
        "exchange_drift_warn": _safe_float(
            row.get("exchange_drift_warn"), _safe_float(defaults.get("exchange_drift_warn"), 0.10)
        ),
        "exchange_drift_critical": _safe_float(
            row.get("exchange_drift_critical"), _safe_float(defaults.get("exchange_drift_critical"), 0.20)
        ),
        "enabled": _safe_bool(row.get("enabled"), _safe_bool(defaults.get("enabled"), True)),
        "inventory_check_enabled": _safe_bool(
            row.get("inventory_check_enabled"), _safe_bool(defaults.get("inventory_check_enabled"), True)
        ),
        "exchange_check_enabled": _safe_bool(
            row.get("exchange_check_enabled"), _safe_bool(defaults.get("exchange_check_enabled"), True)
        ),
        "fill_parity_check_enabled": _safe_bool(
            row.get("fill_parity_check_enabled"), _safe_bool(defaults.get("fill_parity_check_enabled"), True)
        ),
        "accounting_check_enabled": _safe_bool(
            row.get("accounting_check_enabled"), _safe_bool(defaults.get("accounting_check_enabled"), True)
        ),
        "fee_drop_warn": _safe_float(row.get("fee_drop_warn"), _safe_float(defaults.get("fee_drop_warn"), 0.05)),
        "fee_drop_critical": _safe_float(
            row.get("fee_drop_critical"), _safe_float(defaults.get("fee_drop_critical"), 0.20)
        ),
        "turnover_fee_gap_warn": _safe_float(
            row.get("turnover_fee_gap_warn"), _safe_float(defaults.get("turnover_fee_gap_warn"), 0.05)
        ),
    }


def run(once: bool = False, synthetic_drift: bool = False) -> None:
    if Path("/.dockerenv").exists():
        root = Path("/workspace/hbot")
    else:
        root = Path(__file__).resolve().parents[2]
    data_root = Path(os.getenv("HB_DATA_ROOT", str(root / "data")))
    reports_root = root / "reports" / "reconciliation"
    reports_root.mkdir(parents=True, exist_ok=True)

    inv_warn = float(os.getenv("RECON_INVENTORY_DRIFT_WARN", "0.25"))
    inv_critical = float(os.getenv("RECON_INVENTORY_DRIFT_CRITICAL", "0.45"))
    interval_sec = int(os.getenv("RECON_INTERVAL_SEC", "300"))
    alert_webhook_url = os.getenv("RECON_ALERT_WEBHOOK_URL", "").strip()
    alert_min_severity = os.getenv("RECON_ALERT_MIN_SEVERITY", "critical").strip().lower()
    exchange_source_enabled = os.getenv("RECON_EXCHANGE_SOURCE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    exchange_snapshot_path = Path(
        os.getenv("RECON_EXCHANGE_SNAPSHOT_PATH", str(root / "reports" / "exchange_snapshots" / "latest.json"))
    )
    thresholds_path = Path(
        os.getenv("RECON_THRESHOLDS_PATH", str(root / "config" / "reconciliation_thresholds.json"))
    )

    while True:
        threshold_cfg = _load_thresholds(thresholds_path)
        findings: List[Dict[str, object]] = []
        accounting_snapshots: List[Dict[str, object]] = []
        checked_bots = 0
        processed_bots = set()
        event_file = root / "reports" / "event_store" / f"events_{_today()}.jsonl"

        for minute_file in data_root.glob("*/logs/epp_v24/*/minute.csv"):
            bot = minute_file.parts[-5]
            if bot in processed_bots:
                continue
            minute = _read_last_csv_row(minute_file) or {}
            minute_window = _read_last_n_csv_rows(minute_file, n=2)
            minute_prev = minute_window[0] if len(minute_window) == 2 else None
            if not minute:
                findings.append(_severity("warning", "balance", "missing_minute_snapshot", bot, {"file": str(minute_file)}))
                continue

            equity_quote = _safe_float(minute.get("equity_quote"), -1.0)
            base_pct = _safe_float(minute.get("base_pct"), -1.0)
            target_base_pct = _safe_float(minute.get("target_base_pct"), base_pct)
            bot_cfg = _bot_thresholds(threshold_cfg, bot)
            if not bot_cfg.get("enabled", True):
                continue
            processed_bots.add(bot)
            checked_bots += 1
            bot_inv_warn = bot_cfg["inventory_warn"] if bot_cfg["inventory_warn"] > 0 else inv_warn
            bot_inv_critical = (
                bot_cfg["inventory_critical"] if bot_cfg["inventory_critical"] > bot_inv_warn else inv_critical
            )

            if equity_quote <= 0:
                findings.append(_severity("critical", "balance", "equity_non_positive", bot, {"equity_quote": equity_quote}))
            if base_pct < 0 or base_pct > 1:
                findings.append(_severity("critical", "balance", "base_pct_out_of_range", bot, {"base_pct": base_pct}))

            accounting_snapshots.append(
                {
                    "bot": bot,
                    "exchange": str(minute.get("exchange", "")),
                    "trading_pair": str(minute.get("trading_pair", "")),
                    "mid": _safe_float(minute.get("mid"), 0.0),
                    "equity_quote": equity_quote,
                    "base_balance": _safe_float(minute.get("base_balance"), 0.0),
                    "quote_balance": _safe_float(minute.get("quote_balance"), 0.0),
                    "fees_paid_today_quote": _safe_float(minute.get("fees_paid_today_quote"), 0.0),
                    "funding_paid_today_quote": _safe_float(minute.get("funding_paid_today_quote"), 0.0),
                    "daily_loss_pct": _safe_float(minute.get("daily_loss_pct"), 0.0),
                    "drawdown_pct": _safe_float(minute.get("drawdown_pct"), 0.0),
                    "fee_source": str(minute.get("fee_source", "")),
                }
            )

            if bot_cfg.get("inventory_check_enabled", True):
                inv_drift = abs(base_pct - target_base_pct)
                if inv_drift >= bot_inv_critical:
                    findings.append(
                        _severity(
                            "critical",
                            "inventory",
                            "inventory_drift_critical",
                            bot,
                            {"drift": inv_drift, "warn_threshold": bot_inv_warn, "critical_threshold": bot_inv_critical},
                        )
                    )
                elif inv_drift >= bot_inv_warn:
                    findings.append(
                        _severity(
                            "warning",
                            "inventory",
                            "inventory_drift_warning",
                            bot,
                            {"drift": inv_drift, "warn_threshold": bot_inv_warn, "critical_threshold": bot_inv_critical},
                        )
                    )

            if exchange_source_enabled and bot_cfg.get("exchange_check_enabled", True):
                _apply_exchange_snapshot_check(
                    findings=findings,
                    bot=bot,
                    base_pct=base_pct,
                    exchange_snapshot_path=exchange_snapshot_path,
                    exchange_warn=bot_cfg["exchange_drift_warn"],
                    exchange_critical=bot_cfg["exchange_drift_critical"],
                )

            if bot_cfg.get("fill_parity_check_enabled", True):
                fills_events = _count_event_fills(event_file, bot)
                # IMPORTANT: `fills.csv` is cumulative across days, while `event_file` is per-day.
                # Only flag when the bot has activity *today* (per-minute snapshot) but no `order_filled`
                # events were persisted for today.
                today_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                minute_ts = str(minute.get("ts", "")).strip()
                minute_day = minute_ts.split("T", 1)[0] if "T" in minute_ts else ""
                fills_today = int(_safe_float(minute.get("fills_count_today"), 0.0))
                if minute_day == today_day and fills_today > 0 and fills_events == 0:
                    findings.append(
                        _severity(
                            "warning",
                            "fill_parity",
                            "fills_present_without_order_filled_events",
                            bot,
                            {"fills_today": fills_today, "fills_events": fills_events, "event_file": str(event_file)},
                        )
                    )

            if bot_cfg.get("accounting_check_enabled", True):
                curr_fee = _safe_float(minute.get("fees_paid_today_quote"), 0.0)
                curr_turnover = _safe_float(minute.get("turnover_today_x"), 0.0)
                fee_source = str(minute.get("fee_source", "")).strip()
                maker_fee = _safe_float(minute.get("maker_fee_pct"), 0.0)
                taker_fee = _safe_float(minute.get("taker_fee_pct"), 0.0)
                if curr_fee < -1e-6:
                    findings.append(
                        _severity(
                            "critical",
                            "accounting",
                            "fees_paid_negative",
                            bot,
                            {"fees_paid_today_quote": curr_fee},
                        )
                    )
                if minute_prev:
                    prev_fee = _safe_float(minute_prev.get("fees_paid_today_quote"), curr_fee)
                    prev_turnover = _safe_float(minute_prev.get("turnover_today_x"), curr_turnover)
                    fee_delta = curr_fee - prev_fee
                    turnover_delta = curr_turnover - prev_turnover
                    if fee_delta < -abs(bot_cfg["fee_drop_critical"]):
                        findings.append(
                            _severity(
                                "critical",
                                "accounting",
                                "fees_counter_decreased_critical",
                                bot,
                                {
                                    "prev_fee": prev_fee,
                                    "curr_fee": curr_fee,
                                    "fee_delta": fee_delta,
                                    "critical_threshold": -abs(bot_cfg["fee_drop_critical"]),
                                },
                            )
                        )
                    elif fee_delta < -abs(bot_cfg["fee_drop_warn"]):
                        findings.append(
                            _severity(
                                "warning",
                                "accounting",
                                "fees_counter_decreased_warning",
                                bot,
                                {
                                    "prev_fee": prev_fee,
                                    "curr_fee": curr_fee,
                                    "fee_delta": fee_delta,
                                    "warn_threshold": -abs(bot_cfg["fee_drop_warn"]),
                                },
                            )
                        )
                    # If turnover increases in a fee-paying profile while fees do not move, flag accounting gap.
                    if (
                        turnover_delta > abs(bot_cfg["turnover_fee_gap_warn"])
                        and fee_delta <= 0.0
                        and fee_source != ""
                        and (maker_fee > 0.0 or taker_fee > 0.0)
                    ):
                        findings.append(
                            _severity(
                                "warning",
                                "accounting",
                                "turnover_without_fee_accrual",
                                bot,
                                {
                                    "turnover_delta": turnover_delta,
                                    "fee_delta": fee_delta,
                                    "fee_source": fee_source,
                                    "maker_fee_pct": maker_fee,
                                    "taker_fee_pct": taker_fee,
                                },
                            )
                        )
                elif fills_csv != fills_events:
                    findings.append(
                        _severity(
                            "warning",
                            "fill_parity",
                            "fill_count_mismatch",
                            bot,
                            {"fills_csv": fills_csv, "fills_events": fills_events},
                        )
                    )

        if synthetic_drift:
            findings.append(
                _severity(
                    "critical",
                    "synthetic_drift_test",
                    "synthetic_reconciliation_drift_triggered",
                    "test-bot",
                    {"source": "manual_test"},
                )
            )

        critical_count = sum(1 for f in findings if f.get("severity") == "critical")
        warning_count = sum(1 for f in findings if f.get("severity") == "warning")
        status = "critical" if critical_count > 0 else ("warning" if warning_count > 0 else "ok")

        report = {
            "ts_utc": _utc_now(),
            "checked_bots": checked_bots,
            "status": status,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "exchange_source_enabled": exchange_source_enabled,
            "exchange_snapshot_path": str(exchange_snapshot_path),
            "thresholds_path": str(thresholds_path),
            "accounting_snapshots": accounting_snapshots,
            "findings": findings,
        }
        report_path = reports_root / f"reconciliation_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        _write_json(report_path, report)

        latest_path = reports_root / "latest.json"
        _write_json(latest_path, report)

        webhook_sent = False
        if alert_webhook_url:
            webhook_sent = _emit_webhook_alert(report=report, webhook_url=alert_webhook_url, min_severity=alert_min_severity)
        if webhook_sent:
            marker_path = reports_root / "last_webhook_sent.json"
            _write_json(
                marker_path,
                {"ts_utc": _utc_now(), "status": status, "critical_count": critical_count, "warning_count": warning_count},
            )

        if once:
            break
        time.sleep(max(30, interval_sec))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single reconciliation cycle then exit.")
    parser.add_argument("--synthetic-drift", action="store_true", help="Inject synthetic critical drift finding.")
    args = parser.parse_args()
    run(once=args.once, synthetic_drift=args.synthetic_drift)
