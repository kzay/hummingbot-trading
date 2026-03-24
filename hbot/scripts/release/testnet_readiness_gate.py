#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _check(name: str, ok: bool, reason: str, evidence_paths: list[str]) -> dict:
    return {
        "name": name,
        "pass": bool(ok),
        "reason": reason,
        "evidence_paths": evidence_paths,
    }


def _minutes_since(ts: str) -> float:
    s = (ts or "").strip()
    if not s:
        return 1e9
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return (datetime.now(UTC) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


def build_kill_switch_evidence(kill_report: dict, *, max_age_min: float) -> dict:
    ts_utc = str(kill_report.get("ts_utc", ""))
    age_min = _minutes_since(ts_utc)
    dry_run = str(kill_report.get("dry_run", True)).strip().lower() in {"true", "1", "yes"}
    result = kill_report.get("result", {}) if isinstance(kill_report.get("result"), dict) else {}
    result_status = str(result.get("status", "")).strip().lower()
    executed = result_status in {"executed", "partial"}
    has_entry = bool(str(kill_report.get("entry_id", "")).strip())
    checks = {
        "non_dry_run": not dry_run,
        "execution_status_ok": executed,
        "fresh_evidence": age_min <= max_age_min,
        "entry_id_present": has_entry,
    }
    status = "pass" if all(checks.values()) else "fail"
    return {
        "ts_utc": _utc_now(),
        "status": status,
        "max_age_min": float(max_age_min),
        "kill_switch_report_ts_utc": ts_utc,
        "kill_switch_report_age_min": age_min,
        "kill_switch_result_status": result_status,
        "checks": checks,
        "source": kill_report,
    }


def _read_env_map(env_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="ROAD-5 testnet readiness gate.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero on failed gate.")
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    env_map = _read_env_map(root / "env" / ".env")

    kill_switch_report_path = root / "reports" / "kill_switch" / "latest.json"
    bot_cfg_path = root / "data" / "bot1" / "conf" / "controllers" / "epp_v2_4_bot_a.yml"
    checklist_path = root / "reports" / "ops" / "go_live_checklist_evidence_latest.json"
    kill_evidence_path = root / "reports" / "ops" / "kill_switch_non_dry_run_evidence_latest.json"
    kill_evidence_ts_dir = root / "reports" / "ops"

    checks: list[dict] = []

    # 1) kill-switch dry-run must be disabled for ROAD-5
    dry_run_off = str(env_map.get("KILL_SWITCH_DRY_RUN", "true")).lower() in {"0", "false", "no"}
    checks.append(
        _check(
            "kill_switch_non_dry_run_config",
            dry_run_off,
            "KILL_SWITCH_DRY_RUN=false" if dry_run_off else "KILL_SWITCH_DRY_RUN not set to false",
            [str(root / "env" / ".env")],
        )
    )

    # 2) kill-switch execution evidence present and fresh (dedicated artifact)
    kill_rep = _read_json(kill_switch_report_path)
    max_ks_age_min = float(env_map.get("KILL_SWITCH_EVIDENCE_MAX_AGE_MIN", "1440"))
    kill_evidence = build_kill_switch_evidence(kill_rep, max_age_min=max_ks_age_min)
    kill_evidence_ts_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    kill_evidence_ts = kill_evidence_ts_dir / f"kill_switch_non_dry_run_evidence_{stamp}.json"
    kill_evidence_ts.write_text(json.dumps(kill_evidence, indent=2), encoding="utf-8")
    kill_evidence_path.write_text(json.dumps(kill_evidence, indent=2), encoding="utf-8")
    ks_executed = str(kill_evidence.get("status", "fail")).lower() == "pass"
    ks_reason = (
        "non-dry-run kill switch evidence present and fresh"
        if ks_executed
        else (
            "non-dry-run kill switch evidence failed checks: "
            + ",".join([k for k, v in (kill_evidence.get("checks", {}) or {}).items() if not bool(v)])
        )
    )
    checks.append(
        _check(
            "kill_switch_execution_evidence",
            ks_executed,
            ks_reason,
            [str(kill_switch_report_path), str(kill_evidence_path), str(kill_evidence_ts)],
        )
    )

    # 3) bot1 connector set for testnet/live path (bitget_perpetual, not paper connector)
    cfg_txt = bot_cfg_path.read_text(encoding="utf-8") if bot_cfg_path.exists() else ""
    connector_ok = "connector_name: bitget_perpetual" in cfg_txt
    checks.append(
        _check(
            "bot1_connector_target",
            connector_ok,
            "bot1 configured for bitget_perpetual" if connector_ok else "bot1 still not configured for bitget_perpetual",
            [str(bot_cfg_path)],
        )
    )

    # 4) go-live checklist evidence exists
    checklist = _read_json(checklist_path)
    checklist_ok = str(checklist.get("overall_status", "")).lower() in {"pass", "in_progress"}
    checks.append(
        _check(
            "go_live_checklist_evidence",
            checklist_ok,
            "checklist evidence present" if checklist_ok else "checklist evidence missing",
            [str(checklist_path)],
        )
    )

    status = "pass" if all(bool(c["pass"]) for c in checks) else "fail"
    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "checks": checks,
    }
    out_dir = root / "reports" / "ops"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "testnet_readiness_latest.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[testnet-readiness] status={status}")
    print(f"[testnet-readiness] evidence={out_path}")
    if args.strict and status != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
