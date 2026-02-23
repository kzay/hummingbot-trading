from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Dict[str, object]) -> Dict[str, object]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else default
    except Exception:
        return default


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _minutes_since(ts: str) -> float:
    dt = _parse_ts(ts)
    if dt is None:
        return 1e9
    return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0


def _status_from_report(payload: Dict[str, object], status_key: str = "status", default: str = "unknown") -> str:
    return str(payload.get(status_key, default)).strip().lower()


def _build_snapshot(root: Path, freshness_max_min: int) -> Dict[str, object]:
    reports = root / "reports"
    day2_path = reports / "event_store" / "day2_gate_eval_latest.json"
    recon_path = reports / "reconciliation" / "latest.json"
    parity_path = reports / "parity" / "latest.json"
    risk_path = reports / "portfolio_risk" / "latest.json"
    strict_cycle_path = reports / "promotion_gates" / "strict_cycle_latest.json"

    day2 = _read_json(day2_path, {})
    recon = _read_json(recon_path, {})
    parity = _read_json(parity_path, {})
    risk = _read_json(risk_path, {})
    strict_cycle = _read_json(strict_cycle_path, {})

    day2_go = bool(day2.get("go", False))
    recon_ok = int(recon.get("critical_count", 1)) == 0 and _status_from_report(recon) in {"ok", "warning"}
    parity_ok = _status_from_report(parity) == "pass"
    risk_ok = _status_from_report(risk) in {"ok", "warning"}
    strict_ok = str(strict_cycle.get("strict_gate_status", "FAIL")).upper() == "PASS"

    freshness = {
        "reconciliation_fresh": _minutes_since(str(recon.get("ts_utc", ""))) <= freshness_max_min,
        "parity_fresh": _minutes_since(str(parity.get("ts_utc", ""))) <= freshness_max_min,
        "portfolio_risk_fresh": _minutes_since(str(risk.get("ts_utc", ""))) <= freshness_max_min,
        "strict_cycle_fresh": _minutes_since(str(strict_cycle.get("ts_utc", ""))) <= freshness_max_min,
    }
    freshness_ok = all(freshness.values())

    blockers: List[str] = []
    if not day2_go:
        blockers.append("day2_event_store_gate")
    if not recon_ok:
        blockers.append("reconciliation_not_healthy")
    if not parity_ok:
        blockers.append("parity_not_pass")
    if not risk_ok:
        blockers.append("portfolio_risk_not_healthy")
    if not strict_ok:
        blockers.append("strict_cycle_not_pass")
    if not freshness_ok:
        blockers.append("stale_reports")

    status = "ready" if len(blockers) == 0 else "hold"
    return {
        "ts_utc": _utc_now(),
        "status": status,
        "blockers": blockers,
        "freshness": freshness,
        "day2_gate": {
            "go": day2_go,
            "checks": day2.get("checks", []),
            "path": str(day2_path),
        },
        "reconciliation": {
            "status": _status_from_report(recon),
            "critical_count": int(recon.get("critical_count", 0)),
            "warning_count": int(recon.get("warning_count", 0)),
            "path": str(recon_path),
        },
        "parity": {
            "status": _status_from_report(parity),
            "failed_bots": int(parity.get("failed_bots", 0)),
            "checked_bots": int(parity.get("checked_bots", 0)),
            "path": str(parity_path),
        },
        "portfolio_risk": {
            "status": _status_from_report(risk),
            "critical_count": int(risk.get("critical_count", 0)),
            "warning_count": int(risk.get("warning_count", 0)),
            "path": str(risk_path),
        },
        "strict_cycle": {
            "status": str(strict_cycle.get("strict_gate_status", "UNKNOWN")).upper(),
            "rc": int(strict_cycle.get("strict_gate_rc", 999)),
            "critical_failures": strict_cycle.get("critical_failures", []),
            "path": str(strict_cycle_path),
        },
    }


def _write_snapshot(root: Path, payload: Dict[str, object]) -> Path:
    out_root = root / "reports" / "soak"
    out_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_root / f"soak_snapshot_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_root / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def run(once: bool, interval_sec: int, freshness_max_min: int) -> None:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    while True:
        payload = _build_snapshot(root=root, freshness_max_min=freshness_max_min)
        out = _write_snapshot(root=root, payload=payload)
        print(f"[soak-monitor] status={payload.get('status')} blockers={payload.get('blockers')} evidence={out}")
        if once:
            break
        time.sleep(max(30, interval_sec))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aggregate soak-readiness snapshot across all gates/services.")
    parser.add_argument("--once", action="store_true", help="Run once and exit.")
    parser.add_argument("--interval-sec", type=int, default=300, help="Polling interval in seconds.")
    parser.add_argument("--freshness-max-min", type=int, default=30, help="Max report age in minutes.")
    args = parser.parse_args()
    run(once=args.once, interval_sec=args.interval_sec, freshness_max_min=args.freshness_max_min)
