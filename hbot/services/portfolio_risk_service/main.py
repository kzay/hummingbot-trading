from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from services.contracts.stream_names import (
    AUDIT_STREAM,
    BOT_TELEMETRY_STREAM,
    EXECUTION_INTENT_STREAM,
    PORTFOLIO_RISK_STREAM,
    STREAM_RETENTION_MAXLEN,
)
from services.hb_bridge.redis_client import RedisStreamClient


from services.common.utils import (
    now_ms as _now_ms,
    safe_bool as _safe_bool,
    safe_float as _safe_float,
    today_utc as _today,
    utc_now as _utc_now,
)
from services.common.event_store_reader import load_bot_snapshot_windows


def _read_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _append_jsonl(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def _load_limits(path: Path) -> Dict[str, object]:
    default = {
        "version": 1,
        "global_daily_loss_cap_pct": 0.03,
        "cross_bot_net_exposure_cap_quote": 25000.0,
        "concentration_cap_pct": 0.70,
        "concentration_min_equity_quote": 100.0,
        "warn_buffer_ratio": 0.80,
        "bot_action_scope": ["bot1", "bot4"],
        "bot_overrides": {},
    }
    payload = _read_json(path, default)
    merged = default.copy()
    merged.update(payload if isinstance(payload, dict) else {})
    return merged


def _severity_and_action(value: float, cap: float, warn_buffer_ratio: float, hard_action: str) -> Dict[str, object]:
    warn_level = cap * warn_buffer_ratio
    if value >= cap:
        return {"severity": "critical", "action": hard_action, "warn_level": warn_level}
    if value >= warn_level:
        return {"severity": "warning", "action": "soft_pause", "warn_level": warn_level}
    return {"severity": "ok", "action": "allow", "warn_level": warn_level}


def _build_intent_payload(bot: str, action: str, reason: str, details: Dict[str, object]) -> Dict[str, object]:
    event_id = str(uuid.uuid4())
    now_ms = _now_ms()
    event = {
        "schema_version": "1.0",
        "event_type": "execution_intent",
        "event_id": event_id,
        "correlation_id": event_id,
        "producer": "portfolio_risk_service",
        "timestamp_ms": now_ms,
        "instance_name": bot,
        "controller_id": "portfolio_risk_v1",
        "action": action,
        "target_base_pct": None,
        "expires_at_ms": now_ms + 300000,
        "metadata": {"reason": reason, "details": json.dumps(details)},
    }
    return event


def _build_audit_payload(
    severity: str,
    category: str,
    message: str,
    bot: str,
    details: Dict[str, object],
    correlation_id: Optional[str] = None,
) -> Dict[str, object]:
    event_id = str(uuid.uuid4())
    event = {
        "schema_version": "1.0",
        "event_type": "audit",
        "event_id": event_id,
        "correlation_id": correlation_id or event_id,
        "producer": "portfolio_risk_service",
        "timestamp_ms": _now_ms(),
        "instance_name": bot,
        "severity": "error" if severity == "critical" else ("warning" if severity == "warning" else "info"),
        "category": category,
        "message": message,
        "metadata": {"details": json.dumps(details)},
    }
    return event


def _build_portfolio_snapshot_payload(
    *,
    portfolio_action: str,
    status: str,
    critical_count: int,
    warning_count: int,
    risk_scope_bots: List[str],
    metrics: Dict[str, object],
) -> Dict[str, object]:
    event_id = str(uuid.uuid4())
    return {
        "schema_version": "1.0",
        "event_type": "portfolio_risk_snapshot",
        "event_id": event_id,
        "correlation_id": event_id,
        "producer": "portfolio_risk_service",
        "timestamp_ms": _now_ms(),
        "portfolio_action": portfolio_action,
        "status": status,
        "critical_count": int(critical_count),
        "warning_count": int(warning_count),
        "risk_scope_bots": list(risk_scope_bots),
        "metrics": metrics,
    }


def run(once: bool = False, synthetic_breach: bool = False) -> None:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    event_store_root = Path(os.getenv("PORTFOLIO_RISK_EVENT_STORE_ROOT", str(root / "reports" / "event_store")))
    reports_root = root / "reports" / "portfolio_risk"
    reports_root.mkdir(parents=True, exist_ok=True)
    interval_sec = int(os.getenv("PORTFOLIO_RISK_INTERVAL_SEC", "300"))
    limits_path = Path(os.getenv("PORTFOLIO_RISK_LIMITS_PATH", str(root / "config" / "portfolio_limits_v1.json")))
    publish_actions = _safe_bool(os.getenv("PORTFOLIO_RISK_PUBLISH_ACTIONS", "true"), True)
    realtime_enabled = _safe_bool(os.getenv("PORTFOLIO_RISK_REALTIME_ENABLED", "true"), True)
    realtime_poll_ms = max(250, int(os.getenv("PORTFOLIO_RISK_REALTIME_POLL_MS", "1000")))
    telemetry_group = os.getenv("PORTFOLIO_RISK_REALTIME_GROUP", "hb_portfolio_risk_v1")
    telemetry_consumer = f"portfolio-risk-{os.getenv('SERVICE_INSTANCE_NAME', 'default')}"
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_db = int(os.getenv("REDIS_DB", "0"))
    redis_password = os.getenv("REDIS_PASSWORD", "") or None

    client = RedisStreamClient(
        host=redis_host,
        port=redis_port,
        db=redis_db,
        password=redis_password,
        enabled=publish_actions,
    )
    if realtime_enabled and client.enabled:
        client.create_group(BOT_TELEMETRY_STREAM, telemetry_group)

    while True:
        limits = _load_limits(limits_path)
        warn_buffer_ratio = _safe_float(limits.get("warn_buffer_ratio"), 0.8)
        action_scope = limits.get("bot_action_scope", [])
        action_scope = action_scope if isinstance(action_scope, list) else []
        bot_overrides = limits.get("bot_overrides", {})
        bot_overrides = bot_overrides if isinstance(bot_overrides, dict) else {}

        bots: Dict[str, Dict[str, object]] = {}
        snapshot_windows = load_bot_snapshot_windows(event_store_root, max_snapshots_per_bot=1)
        for bot, snapshots in snapshot_windows.items():
            row = snapshots[0] if snapshots else {}
            equity_quote = _safe_float(row.get("equity_quote"), 0.0)
            if equity_quote <= 0:
                continue
            base_pct = _safe_float(row.get("base_pct"), 0.0)
            daily_loss_pct = _safe_float(row.get("daily_loss_pct"), 0.0)
            drawdown_pct = _safe_float(row.get("drawdown_pct"), 0.0)
            bots[bot] = {
                "equity_quote": equity_quote,
                "base_pct": base_pct,
                "daily_loss_pct": max(0.0, daily_loss_pct),
                "drawdown_pct": max(0.0, drawdown_pct),
                "directional_exposure_quote": (2.0 * base_pct - 1.0) * equity_quote,
                "base_exposure_abs_quote": abs(base_pct * equity_quote),
            }

        scoped_bots = {k: v for k, v in bots.items() if (not action_scope or k in action_scope)}
        if not scoped_bots:
            scoped_bots = bots

        total_equity = sum(float(v["equity_quote"]) for v in scoped_bots.values())
        if synthetic_breach and total_equity <= 0:
            total_equity = 10000.0
            bots["synthetic_bot"] = {
                "equity_quote": 10000.0,
                "base_pct": 1.0,
                "daily_loss_pct": 0.08,
                "drawdown_pct": 0.09,
                "directional_exposure_quote": 10000.0,
                "base_exposure_abs_quote": 10000.0,
            }

        weighted_daily_loss = 0.0
        if total_equity > 0:
            weighted_daily_loss = sum(
                float(v["equity_quote"]) * float(v["daily_loss_pct"]) for v in scoped_bots.values()
            ) / total_equity

        net_exposure_quote = abs(sum(float(v["directional_exposure_quote"]) for v in scoped_bots.values()))
        concentration_min_equity = _safe_float(limits.get("concentration_min_equity_quote"), 100.0)
        concentration_candidates = {
            bot: payload
            for bot, payload in scoped_bots.items()
            if _safe_float(payload.get("equity_quote"), 0.0) >= concentration_min_equity
        }
        concentration_total_equity = sum(float(v["equity_quote"]) for v in concentration_candidates.values())
        max_equity_share = 0.0
        if concentration_total_equity > 0 and len(concentration_candidates) >= 2:
            max_equity_share = max(
                float(v["equity_quote"]) / concentration_total_equity for v in concentration_candidates.values()
            )

        if synthetic_breach:
            weighted_daily_loss = max(weighted_daily_loss, _safe_float(limits.get("global_daily_loss_cap_pct"), 0.03) + 0.02)
            net_exposure_quote = max(
                net_exposure_quote, _safe_float(limits.get("cross_bot_net_exposure_cap_quote"), 25000.0) + 5000.0
            )
            max_equity_share = max(max_equity_share, _safe_float(limits.get("concentration_cap_pct"), 0.70) + 0.10)

        findings: List[Dict[str, object]] = []
        actions: List[Dict[str, object]] = []

        daily_cfg = _severity_and_action(
            value=weighted_daily_loss,
            cap=_safe_float(limits.get("global_daily_loss_cap_pct"), 0.03),
            warn_buffer_ratio=warn_buffer_ratio,
            hard_action="kill_switch",
        )
        if daily_cfg["severity"] != "ok":
            findings.append(
                {
                    "severity": daily_cfg["severity"],
                    "check": "global_daily_loss_cap",
                    "message": "portfolio_daily_loss_breach" if daily_cfg["severity"] == "critical" else "portfolio_daily_loss_warning",
                    "details": {
                        "portfolio_daily_loss_pct": weighted_daily_loss,
                        "cap_pct": _safe_float(limits.get("global_daily_loss_cap_pct"), 0.03),
                        "warn_level_pct": daily_cfg["warn_level"],
                    },
                }
            )

        exposure_cfg = _severity_and_action(
            value=net_exposure_quote,
            cap=_safe_float(limits.get("cross_bot_net_exposure_cap_quote"), 25000.0),
            warn_buffer_ratio=warn_buffer_ratio,
            hard_action="kill_switch",
        )
        if exposure_cfg["severity"] != "ok":
            findings.append(
                {
                    "severity": exposure_cfg["severity"],
                    "check": "cross_bot_net_exposure_cap",
                    "message": "cross_bot_net_exposure_breach"
                    if exposure_cfg["severity"] == "critical"
                    else "cross_bot_net_exposure_warning",
                    "details": {
                        "abs_net_exposure_quote": net_exposure_quote,
                        "cap_quote": _safe_float(limits.get("cross_bot_net_exposure_cap_quote"), 25000.0),
                        "warn_level_quote": exposure_cfg["warn_level"],
                    },
                }
            )

        if len(concentration_candidates) >= 2:
            concentration_cfg = _severity_and_action(
                value=max_equity_share,
                cap=_safe_float(limits.get("concentration_cap_pct"), 0.70),
                warn_buffer_ratio=warn_buffer_ratio,
                hard_action="soft_pause",
            )
            if concentration_cfg["severity"] != "ok":
                findings.append(
                    {
                        "severity": concentration_cfg["severity"],
                        "check": "concentration_cap",
                        "message": "concentration_breach"
                        if concentration_cfg["severity"] == "critical"
                        else "concentration_warning",
                        "details": {
                            "max_equity_share_pct": max_equity_share,
                            "cap_pct": _safe_float(limits.get("concentration_cap_pct"), 0.70),
                            "warn_level_pct": concentration_cfg["warn_level"],
                            "candidate_bot_count": len(concentration_candidates),
                            "min_equity_quote": concentration_min_equity,
                        },
                    }
                )

        critical_count = sum(1 for f in findings if f.get("severity") == "critical")
        warning_count = sum(1 for f in findings if f.get("severity") == "warning")
        portfolio_action = "allow"
        if critical_count > 0:
            portfolio_action = "kill_switch"
        elif warning_count > 0:
            portfolio_action = "soft_pause"

        # Convert portfolio-level action to per-bot intents for active live bots.
        action_bots = [b for b in sorted(bots.keys()) if (not action_scope or b in action_scope)]
        for bot in action_bots:
            override = bot_overrides.get(bot, {}) if isinstance(bot_overrides.get(bot, {}), dict) else {}
            bot_enabled = _safe_bool(override.get("enabled"), True)
            if not bot_enabled:
                continue
            bot_action = portfolio_action
            if bot_action == "kill_switch" and _safe_bool(override.get("kill_switch_disabled"), False):
                bot_action = "soft_pause"
            if bot_action == "allow":
                continue
            reason = "portfolio_risk_breach"
            details = {
                "portfolio_action": portfolio_action,
                "critical_count": critical_count,
                "warning_count": warning_count,
                "findings": findings,
            }
            intent = _build_intent_payload(bot=bot, action=bot_action, reason=reason, details=details)
            actions.append({"bot": bot, "action": bot_action, "event": intent})

            audit = _build_audit_payload(
                severity="critical" if bot_action == "kill_switch" else "warning",
                category="portfolio_risk_action",
                message=f"portfolio_risk_{bot_action}",
                bot=bot,
                details=details,
                correlation_id=str(intent.get("event_id")),
            )
            if client.enabled:
                client.xadd(
                    stream=AUDIT_STREAM,
                    payload=audit,
                    maxlen=STREAM_RETENTION_MAXLEN.get(AUDIT_STREAM),
                )

        if client.enabled and publish_actions:
            for row in actions:
                event = row.get("event", {})
                if isinstance(event, dict):
                    client.xadd(
                        stream=EXECUTION_INTENT_STREAM,
                        payload=event,
                        maxlen=STREAM_RETENTION_MAXLEN.get(EXECUTION_INTENT_STREAM),
                    )

        report = {
            "ts_utc": _utc_now(),
            "status": "critical" if critical_count > 0 else ("warning" if warning_count > 0 else "ok"),
            "critical_count": critical_count,
            "warning_count": warning_count,
            "portfolio_action": portfolio_action,
            "limits_path": str(limits_path),
            "event_store_root": str(event_store_root),
            "publish_actions_enabled": bool(client.enabled and publish_actions),
            "synthetic_breach": synthetic_breach,
            "metrics": {
                "portfolio_daily_loss_pct": weighted_daily_loss,
                "abs_net_exposure_quote": net_exposure_quote,
                "max_equity_share_pct": max_equity_share,
                "total_equity_quote": total_equity,
                "concentration_candidate_bot_count": len(concentration_candidates),
                "concentration_min_equity_quote": concentration_min_equity,
            },
            "risk_scope_bots": sorted(scoped_bots.keys()),
            "bots": bots,
            "findings": findings,
            "actions": [{"bot": a["bot"], "action": a["action"], "event_id": a["event"].get("event_id")} for a in actions],
        }

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_path = reports_root / f"portfolio_risk_{stamp}.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        (reports_root / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        _append_jsonl(reports_root / f"audit_{_today()}.jsonl", report)
        if client.enabled:
            snapshot = _build_portfolio_snapshot_payload(
                portfolio_action=str(report["portfolio_action"]),
                status=str(report["status"]),
                critical_count=int(report["critical_count"]),
                warning_count=int(report["warning_count"]),
                risk_scope_bots=list(report["risk_scope_bots"]),
                metrics=dict(report["metrics"]),
            )
            client.xadd(
                stream=PORTFOLIO_RISK_STREAM,
                payload=snapshot,
                maxlen=STREAM_RETENTION_MAXLEN.get(PORTFOLIO_RISK_STREAM),
            )

        if once:
            break
        if realtime_enabled and client.enabled:
            # Near-real-time mode: wake on bot telemetry events, but always
            # re-evaluate at least once per configured interval.
            deadline = time.time() + max(1, interval_sec)
            triggered = False
            while time.time() < deadline:
                remaining_ms = int(max(0, (deadline - time.time()) * 1000))
                block_ms = max(250, min(realtime_poll_ms, remaining_ms))
                entries = client.read_group(
                    stream=BOT_TELEMETRY_STREAM,
                    group=telemetry_group,
                    consumer=telemetry_consumer,
                    count=50,
                    block_ms=block_ms,
                )
                for entry_id, _payload in entries:
                    client.ack(BOT_TELEMETRY_STREAM, telemetry_group, entry_id)
                if entries:
                    triggered = True
                    break
            if not triggered and time.time() < deadline:
                time.sleep(max(0.0, deadline - time.time()))
        else:
            time.sleep(max(1, interval_sec))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single portfolio risk cycle then exit.")
    parser.add_argument("--synthetic-breach", action="store_true", help="Inject a synthetic breach for control testing.")
    args = parser.parse_args()
    run(once=args.once, synthetic_breach=args.synthetic_breach)
