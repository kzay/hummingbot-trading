from __future__ import annotations

import argparse
import csv
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.request import Request, urlopen

from services.common.activity_scope import active_bots_from_minute_logs
from services.common.event_store_reader import count_bot_fill_events, load_bot_snapshot_windows
from services.common.utils import safe_bool as _safe_bool, safe_float as _safe_float, today_utc as _today, utc_now as _utc_now
from services.contracts.stream_names import EXECUTION_INTENT_STREAM, STREAM_RETENTION_MAXLEN
from services.hb_bridge.redis_client import RedisStreamClient


def _count_event_fills(path: Path, bot: str) -> int:
    if path.exists():
        count = 0
        try:
            for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line:
                    continue
                event = json.loads(line)
                event_type = str(event.get("event_type", "")).strip().lower()
                if event_type not in {"order_filled", "bot_fill"}:
                    continue
                if str(event.get("instance_name", "")).strip() != str(bot).strip():
                    continue
                count += 1
        except Exception:
            return count
        return count
    return count_bot_fill_events(path.parent, bot, day_utc=path.stem.replace("events_", ""))


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


def _load_recent_minute_rows(path: Path, *, max_rows: int = 2) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    rows: List[Dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if isinstance(row, dict):
                    rows.append(row)
    except Exception:
        return []
    if not rows:
        return []
    return list(reversed(rows[-max(1, int(max_rows)) :]))


def _snapshot_windows_with_minute_log_fallback(
    event_store_root: Path,
    data_root: Path,
    *,
    max_snapshots_per_bot: int = 2,
) -> Tuple[Dict[str, List[Dict[str, object]]], List[str]]:
    snapshot_windows = load_bot_snapshot_windows(event_store_root, max_snapshots_per_bot=max_snapshots_per_bot)
    fallback_bots: List[str] = []
    for minute_file in data_root.glob("*/logs/epp_v24/*/minute.csv"):
        try:
            bot = minute_file.parts[-5]
        except Exception:
            continue
        if bot in snapshot_windows and len(snapshot_windows[bot]) >= max_snapshots_per_bot:
            continue
        fallback_rows = _load_recent_minute_rows(minute_file, max_rows=max_snapshots_per_bot)
        if not fallback_rows:
            continue
        merged_rows: List[Dict[str, object]] = []
        for row in fallback_rows:
            merged = dict(row)
            merged.setdefault("instance_name", bot)
            merged.setdefault("ts", str(row.get("ts", "")))
            merged["snapshot_source"] = "minute_log_fallback"
            merged["minute_path"] = str(minute_file)
            merged_rows.append(merged)
        snapshot_windows[bot] = merged_rows
        fallback_bots.append(bot)
    return snapshot_windows, sorted(set(fallback_bots))


def _load_fill_reconciliation_report(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _apply_fill_reconciliation_report(
    findings: List[Dict[str, object]],
    report: Dict[str, object],
) -> None:
    bots = report.get("bots", [])
    if not isinstance(bots, list):
        return
    for row in bots:
        if not isinstance(row, dict):
            continue
        bot = str(row.get("bot", "")).strip()
        if not bot:
            continue
        status = str(row.get("status", "")).strip().lower()
        if status not in {"warning", "critical", "error"}:
            continue
        missing_local_count = int(_safe_float(row.get("missing_local_count"), 0.0))
        missing_exchange_count = int(_safe_float(row.get("missing_exchange_count"), 0.0))
        price_mismatch_count = int(_safe_float(row.get("price_mismatch_count"), 0.0))
        amount_mismatch_count = int(_safe_float(row.get("amount_mismatch_count"), 0.0))
        fee_mismatch_count = int(_safe_float(row.get("fee_mismatch_count"), 0.0))
        timestamp_mismatch_count = int(_safe_float(row.get("timestamp_mismatch_count"), 0.0))
        severity = "warning" if status == "warning" else "critical"
        findings.append(
            _severity(
                severity,
                "exchange_fill_reconciliation",
                "exchange_truth_fill_reconciliation_mismatch",
                bot,
                {
                    "exchange": str(report.get("exchange", "")),
                    "status": status,
                    "missing_local_count": missing_local_count,
                    "missing_exchange_count": missing_exchange_count,
                    "price_mismatch_count": price_mismatch_count,
                    "amount_mismatch_count": amount_mismatch_count,
                    "fee_mismatch_count": fee_mismatch_count,
                    "timestamp_mismatch_count": timestamp_mismatch_count,
                    "local_fill_count": int(_safe_float(row.get("local_fill_count"), 0.0)),
                    "exchange_fill_count": int(_safe_float(row.get("exchange_fill_count"), 0.0)),
                    "missing_local": row.get("missing_local", []),
                    "missing_exchange": row.get("missing_exchange", []),
                    "price_mismatches": row.get("price_mismatches", []),
                    "amount_mismatches": row.get("amount_mismatches", []),
                    "fee_mismatches": row.get("fee_mismatches", []),
                    "timestamp_mismatches": row.get("timestamp_mismatches", []),
                },
            )
        )


def _parse_action_scope(raw: str) -> Set[str]:
    return {part.strip() for part in raw.split(",") if part.strip()}


def _critical_action_name(raw: str) -> str:
    val = str(raw).strip().lower()
    if val in {"soft_pause", "kill_switch"}:
        return val
    return "soft_pause"


def _derive_reconciliation_actions(
    findings: List[Dict[str, object]],
    previous_critical_bots: Set[str],
    allowed_scope: Set[str],
) -> Tuple[List[Tuple[str, str]], Set[str]]:
    """Return action transitions as ``[(bot, action)]`` and current critical set."""
    critical_bots: Set[str] = set()
    for finding in findings:
        if str(finding.get("severity", "")) != "critical":
            continue
        bot = str(finding.get("bot", "")).strip()
        if not bot:
            continue
        if allowed_scope and bot not in allowed_scope:
            continue
        critical_bots.add(bot)

    actions: List[Tuple[str, str]] = []
    for bot in sorted(critical_bots - previous_critical_bots):
        actions.append((bot, "enter_critical"))
    for bot in sorted(previous_critical_bots - critical_bots):
        actions.append((bot, "recover"))
    return actions, critical_bots


def _build_execution_intent(bot: str, action: str, reason: str, details: Dict[str, object]) -> Dict[str, object]:
    event_id = str(uuid.uuid4())
    now_ms = int(time.time() * 1000)
    return {
        "schema_version": "1.0",
        "event_type": "execution_intent",
        "event_id": event_id,
        "correlation_id": event_id,
        "producer": "reconciliation_service",
        "timestamp_ms": now_ms,
        "instance_name": bot,
        "controller_id": "reconciliation_v1",
        "action": action,
        "target_base_pct": None,
        "expires_at_ms": now_ms + 300000,
        "metadata": {
            "reason": reason,
            "details": json.dumps(details),
        },
    }


def _inventory_drift_from_minute(minute: Dict[str, str], is_perp: bool, bot_cfg: Dict[str, object]) -> Dict[str, object]:
    """Compute inventory drift using a deterministic, mode-aware basis.

    Basis choices:
    - ``target_delta``: abs(base_pct - target_base_pct)
    - ``position_drift_pct``: abs(position_drift_pct)

    For perps, default basis is ``position_drift_pct`` to measure accounting
    consistency against exchange-sourced position sync, not directional inventory
    targeting handled by the controller risk engine.
    """
    perp_basis = str(bot_cfg.get("perp_inventory_basis", "position_drift_pct")).strip().lower()
    if is_perp and perp_basis == "position_drift_pct":
        drift = abs(_safe_float(minute.get("position_drift_pct"), 0.0))
        return {
            "drift": drift,
            "basis": "position_drift_pct",
            "actual": _safe_float(minute.get("position_drift_pct"), 0.0),
            "target": 0.0,
        }

    base_pct = _safe_float(minute.get("base_pct"), -1.0)
    target_base_pct = _safe_float(minute.get("target_base_pct"), base_pct)
    drift = abs(base_pct - target_base_pct)
    return {
        "drift": drift,
        "basis": "target_base_pct_delta",
        "actual": base_pct,
        "target": target_base_pct,
    }


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
            "perp_inventory_basis": "position_drift_pct",
            "exchange_drift_warn": 0.10,
            "exchange_drift_critical": 0.20,
            "fee_rate_warn_mult": 2.5,
            "fee_rate_min_turnover_x": 0.25,
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


def _bot_thresholds(cfg: Dict[str, object], bot: str) -> Dict[str, object]:
    defaults = cfg.get("defaults", {}) if isinstance(cfg.get("defaults"), dict) else {}
    bots = cfg.get("bots", {}) if isinstance(cfg.get("bots"), dict) else {}
    row = bots.get(bot, {}) if isinstance(bots.get(bot, {}), dict) else {}
    return {
        "inventory_warn": _safe_float(row.get("inventory_warn"), _safe_float(defaults.get("inventory_warn"), 0.25)),
        "inventory_critical": _safe_float(
            row.get("inventory_critical"), _safe_float(defaults.get("inventory_critical"), 0.45)
        ),
        "perp_inventory_basis": str(row.get("perp_inventory_basis", defaults.get("perp_inventory_basis", "position_drift_pct"))),
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
        "fee_rate_warn_mult": _safe_float(
            row.get("fee_rate_warn_mult"), _safe_float(defaults.get("fee_rate_warn_mult"), 2.5)
        ),
        "fee_rate_min_turnover_x": _safe_float(
            row.get("fee_rate_min_turnover_x"), _safe_float(defaults.get("fee_rate_min_turnover_x"), 0.25)
        ),
    }


def run(once: bool = False, synthetic_drift: bool = False) -> None:
    if Path("/.dockerenv").exists():
        root = Path("/workspace/hbot")
    else:
        root = Path(__file__).resolve().parents[2]
    event_store_root = Path(
        os.getenv("RECON_EVENT_STORE_ROOT", str(root / "reports" / "event_store"))
    )
    reports_root = root / "reports" / "reconciliation"
    reports_root.mkdir(parents=True, exist_ok=True)

    inv_warn = float(os.getenv("RECON_INVENTORY_DRIFT_WARN", "0.25"))
    inv_critical = float(os.getenv("RECON_INVENTORY_DRIFT_CRITICAL", "0.45"))
    interval_sec = int(os.getenv("RECON_INTERVAL_SEC", "300"))
    alert_webhook_url = os.getenv("RECON_ALERT_WEBHOOK_URL", "").strip()
    alert_min_severity = os.getenv("RECON_ALERT_MIN_SEVERITY", "critical").strip().lower()
    publish_actions_enabled = _safe_bool(os.getenv("RECON_PUBLISH_ACTIONS", "true"), True)
    critical_action = _critical_action_name(os.getenv("RECON_CRITICAL_ACTION", "soft_pause"))
    action_scope = _parse_action_scope(os.getenv("RECON_ACTION_SCOPE", ""))
    exchange_source_enabled = os.getenv("RECON_EXCHANGE_SOURCE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    exchange_snapshot_path = Path(
        os.getenv("RECON_EXCHANGE_SNAPSHOT_PATH", str(root / "reports" / "exchange_snapshots" / "latest.json"))
    )
    thresholds_path = Path(
        os.getenv("RECON_THRESHOLDS_PATH", str(root / "config" / "reconciliation_thresholds.json"))
    )
    fill_reconciliation_enabled = _safe_bool(os.getenv("RECON_FILL_RECON_REPORT_ENABLED", "true"), True)
    fill_reconciliation_report_path = Path(
        os.getenv(
            "RECON_FILL_RECON_REPORT_PATH",
            str(root / "reports" / "reconciliation" / "exchange_fill_reconciliation_latest.json"),
        )
    )
    active_bot_window_min = max(1, int(os.getenv("RECON_ACTIVE_BOT_WINDOW_MIN", "30")))
    data_root = Path(os.getenv("HB_DATA_ROOT", str(root / "data")))
    redis_client = RedisStreamClient(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        password=os.getenv("REDIS_PASSWORD", "") or None,
        enabled=publish_actions_enabled,
    )
    critical_latched_bots: Set[str] = set()

    while True:
        threshold_cfg = _load_thresholds(thresholds_path)
        findings: List[Dict[str, object]] = []
        accounting_snapshots: List[Dict[str, object]] = []
        checked_bot_names: Set[str] = set()
        raw_snapshot_windows = load_bot_snapshot_windows(event_store_root, max_snapshots_per_bot=2)
        snapshot_windows, fallback_snapshot_bots = _snapshot_windows_with_minute_log_fallback(
            event_store_root,
            data_root,
            max_snapshots_per_bot=2,
        )
        active_bots = active_bots_from_minute_logs(data_root, active_within_minutes=active_bot_window_min)

        for bot, activity in active_bots.items():
            if bot in raw_snapshot_windows:
                continue
            checked_bot_names.add(bot)
            findings.append(
                _severity(
                    "critical",
                    "event_store",
                    "missing_bot_minute_snapshot_for_active_bot",
                    bot,
                    {
                        "event_store_root": str(event_store_root),
                        "minute_path": str(activity.get("minute_path", "")),
                        "active_within_minutes": active_bot_window_min,
                        "minute_age_seconds": float(activity.get("age_seconds", 0.0)),
                    },
                )
            )

        for bot, minute_window in snapshot_windows.items():
            minute = minute_window[0] if minute_window else {}
            minute_prev = minute_window[1] if len(minute_window) >= 2 else None
            if not minute:
                findings.append(
                    _severity("warning", "balance", "missing_bot_minute_snapshot", bot, {"event_store_root": str(event_store_root)})
                )
                continue

            equity_quote = _safe_float(minute.get("equity_quote"), -1.0)
            base_pct = _safe_float(minute.get("base_pct"), -1.0)
            target_base_pct = _safe_float(minute.get("target_base_pct"), base_pct)
            exchange_name = str(minute.get("connector_name", minute.get("exchange", ""))).lower()
            is_perp = ("perpetual" in exchange_name) or exchange_name.endswith("_perp") or ("_perp_" in exchange_name)
            bot_cfg = _bot_thresholds(threshold_cfg, bot)
            if not bot_cfg.get("enabled", True):
                continue
            checked_bot_names.add(bot)
            bot_inv_warn = bot_cfg["inventory_warn"] if bot_cfg["inventory_warn"] > 0 else inv_warn
            bot_inv_critical = (
                bot_cfg["inventory_critical"] if bot_cfg["inventory_critical"] > bot_inv_warn else inv_critical
            )

            if equity_quote <= 0:
                findings.append(_severity("critical", "balance", "equity_non_positive", bot, {"equity_quote": equity_quote}))
            # Perpetual connectors can legitimately exceed 1.0 gross base_pct.
            if base_pct < 0 or (base_pct > 1 and not is_perp):
                findings.append(_severity("critical", "balance", "base_pct_out_of_range", bot, {"base_pct": base_pct}))

            accounting_snapshots.append(
                {
                    "bot": bot,
                    "exchange": str(minute.get("connector_name", minute.get("exchange", ""))),
                    "trading_pair": str(minute.get("trading_pair", "")),
                    "mid": _safe_float(minute.get("mid"), 0.0),
                    "equity_quote": equity_quote,
                    "base_balance": _safe_float(minute.get("base_balance"), 0.0),
                    "quote_balance": _safe_float(minute.get("quote_balance"), 0.0),
                    "fees_paid_today_quote": _safe_float(minute.get("fees_paid_today_quote"), 0.0),
                    "funding_paid_today_quote": _safe_float(
                        minute.get("funding_cost_today_quote", minute.get("funding_paid_today_quote")),
                        0.0,
                    ),
                    "net_realized_pnl_today_quote": _safe_float(
                        minute.get("net_realized_pnl_today_quote"),
                        _safe_float(minute.get("realized_pnl_today_quote"), 0.0)
                        - _safe_float(minute.get("funding_cost_today_quote", minute.get("funding_paid_today_quote")), 0.0),
                    ),
                    "daily_loss_pct": _safe_float(minute.get("daily_loss_pct"), 0.0),
                    "drawdown_pct": _safe_float(minute.get("drawdown_pct"), 0.0),
                    "fee_source": str(minute.get("fee_source", "")),
                }
            )

            if bot_cfg.get("inventory_check_enabled", True):
                inv = _inventory_drift_from_minute(minute, is_perp=is_perp, bot_cfg=bot_cfg)
                inv_drift = float(inv["drift"])
                risk_reasons_raw = str(minute.get("risk_reasons", "") or "")
                derisk_only_active = "derisk_only" in risk_reasons_raw.split("|")
                if inv_drift >= bot_inv_critical:
                    if derisk_only_active and str(inv.get("basis", "")) == "target_base_pct_delta":
                        findings.append(
                            _severity(
                                "warning",
                                "inventory",
                                "inventory_drift_warning_derisk_only",
                                bot,
                                {
                                    "drift": inv_drift,
                                    "basis": inv.get("basis"),
                                    "actual": inv.get("actual"),
                                    "target": inv.get("target"),
                                    "warn_threshold": bot_inv_warn,
                                    "critical_threshold": bot_inv_critical,
                                },
                            )
                        )
                    else:
                        findings.append(
                            _severity(
                                "critical",
                                "inventory",
                                "inventory_drift_critical",
                                bot,
                                {
                                    "drift": inv_drift,
                                    "basis": inv.get("basis"),
                                    "actual": inv.get("actual"),
                                    "target": inv.get("target"),
                                    "warn_threshold": bot_inv_warn,
                                    "critical_threshold": bot_inv_critical,
                                },
                            )
                        )
                elif inv_drift >= bot_inv_warn:
                    findings.append(
                        _severity(
                            "warning",
                            "inventory",
                            "inventory_drift_warning",
                            bot,
                            {
                                "drift": inv_drift,
                                "basis": inv.get("basis"),
                                "actual": inv.get("actual"),
                                "target": inv.get("target"),
                                "warn_threshold": bot_inv_warn,
                                "critical_threshold": bot_inv_critical,
                            },
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
                minute_ts = str(minute.get("ts", "")).strip()
                minute_day = minute_ts.split("T", 1)[0] if "T" in minute_ts else ""
                fills_events = count_bot_fill_events(event_store_root, bot, day_utc=minute_day or None)
                # IMPORTANT: `fills.csv` is cumulative across days, while `event_file` is per-day.
                # Only flag when the bot has activity *today* (per-minute snapshot) but no `order_filled`
                # events were persisted for today.
                today_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                fills_today = int(_safe_float(minute.get("fills_count_today"), 0.0))
                if minute_day == today_day and fills_today > 0 and fills_events == 0:
                    findings.append(
                        _severity(
                            "critical",
                            "fill_parity",
                            "fills_present_without_order_filled_events",
                            bot,
                            {
                                "fills_today": fills_today,
                                "fills_events": fills_events,
                                "event_store_root": str(event_store_root),
                                "minute_day": minute_day,
                                "today_day": today_day,
                                "active_day_scope": True,
                            },
                        )
                    )

            if bot_cfg.get("accounting_check_enabled", True):
                curr_fee = _safe_float(minute.get("fees_paid_today_quote"), 0.0)
                curr_turnover = _safe_float(minute.get("turnover_today_x"), 0.0)
                fee_source = str(minute.get("fee_source", "")).strip()
                maker_fee = _safe_float(minute.get("maker_fee_pct"), 0.0)
                taker_fee = _safe_float(minute.get("taker_fee_pct"), 0.0)
                if (
                    equity_quote > 0.0
                    and curr_turnover >= bot_cfg.get("fee_rate_min_turnover_x", 0.25)
                    and curr_fee >= 0.0
                    and (maker_fee > 0.0 or taker_fee > 0.0)
                ):
                    notional_today = curr_turnover * equity_quote
                    if notional_today > 0.0:
                        eff_fee_bps = (curr_fee / notional_today) * 10000.0
                        fee_lo_bps = min(maker_fee, taker_fee) * 10000.0
                        fee_hi_bps = max(maker_fee, taker_fee) * 10000.0
                        warn_mult = max(1.1, bot_cfg.get("fee_rate_warn_mult", 2.5))
                        upper = fee_hi_bps * warn_mult
                        lower = fee_lo_bps / warn_mult if fee_lo_bps > 0.0 else 0.0
                        if eff_fee_bps > upper or (fee_lo_bps > 0.0 and eff_fee_bps < lower):
                            findings.append(
                                _severity(
                                    "warning",
                                    "accounting",
                                    "fee_rate_out_of_expected_band",
                                    bot,
                                    {
                                        "effective_fee_bps_today": eff_fee_bps,
                                        "expected_fee_bps_low": fee_lo_bps,
                                        "expected_fee_bps_high": fee_hi_bps,
                                        "warn_multiplier": warn_mult,
                                        "lower_bound_bps": lower,
                                        "upper_bound_bps": upper,
                                        "turnover_today_x": curr_turnover,
                                        "equity_quote": equity_quote,
                                        "fee_source": fee_source,
                                    },
                                )
                            )
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
                elif minute_day == today_day and fills_today != fills_events:
                    findings.append(
                        _severity(
                            "warning",
                            "fill_parity",
                            "fill_count_mismatch",
                            bot,
                            {"fills_today": fills_today, "fills_events": fills_events},
                        )
                    )

        fill_reconciliation_report: Dict[str, object] = {}
        if fill_reconciliation_enabled:
            fill_reconciliation_report = _load_fill_reconciliation_report(fill_reconciliation_report_path)
            _apply_fill_reconciliation_report(findings, fill_reconciliation_report)

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
        transition_actions, current_critical_bots = _derive_reconciliation_actions(
            findings=findings,
            previous_critical_bots=critical_latched_bots,
            allowed_scope=action_scope,
        )
        published_actions: List[Dict[str, object]] = []
        for bot, transition in transition_actions:
            if transition == "enter_critical":
                action = critical_action
                reason = "reconciliation_critical"
            else:
                action = "resume"
                reason = "reconciliation_recovered"
            details = {
                "status": status,
                "critical_count": critical_count,
                "warning_count": warning_count,
                "transition": transition,
            }
            intent = _build_execution_intent(bot=bot, action=action, reason=reason, details=details)
            entry_id = redis_client.xadd(
                stream=EXECUTION_INTENT_STREAM,
                payload=intent,
                maxlen=STREAM_RETENTION_MAXLEN.get(EXECUTION_INTENT_STREAM),
            )
            published_actions.append(
                {
                    "bot": bot,
                    "transition": transition,
                    "action": action,
                    "reason": reason,
                    "event_id": intent.get("event_id"),
                    "entry_id": entry_id,
                }
            )
        critical_latched_bots = current_critical_bots

        report = {
            "ts_utc": _utc_now(),
            "checked_bots": len(checked_bot_names),
            "checked_bot_names": sorted(checked_bot_names),
            "status": status,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "exchange_source_enabled": exchange_source_enabled,
            "exchange_snapshot_path": str(exchange_snapshot_path),
            "event_store_root": str(event_store_root),
            "thresholds_path": str(thresholds_path),
            "active_bot_window_min": active_bot_window_min,
            "active_bots": sorted(active_bots.keys()),
            "active_bot_count": len(active_bots),
            "covered_active_bots": sorted(bot for bot in active_bots if bot in checked_bot_names),
            "covered_active_bot_count": sum(1 for bot in active_bots if bot in checked_bot_names),
            "active_bots_without_snapshots": sorted(bot for bot in active_bots if bot not in raw_snapshot_windows),
            "active_bots_unchecked": sorted(bot for bot in active_bots if bot not in checked_bot_names),
            "fallback_snapshot_bots": fallback_snapshot_bots,
            "fill_reconciliation_report_path": str(fill_reconciliation_report_path),
            "fill_reconciliation_report_status": str(fill_reconciliation_report.get("status", "missing")),
            "publish_actions_enabled": publish_actions_enabled,
            "critical_action": critical_action,
            "action_scope": sorted(action_scope),
            "accounting_snapshots": accounting_snapshots,
            "findings": findings,
            "actions": published_actions,
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
