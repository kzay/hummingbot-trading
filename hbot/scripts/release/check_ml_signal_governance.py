from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _minutes_since(ts: str) -> float:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _check(name: str, ok: bool, reason: str, details: Dict[str, object]) -> Dict[str, object]:
    return {"name": name, "pass": bool(ok), "reason": reason, "details": details}


def _write(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    policy_path = root / "config" / "ml_governance_policy_v1.json"
    report_path = root / "reports" / "ml" / "latest.json"
    out_root = root / "reports" / "policy"

    policy = _read_json(policy_path)
    ml_enabled = _env_bool("ML_ENABLED", bool(policy.get("enabled_default", False)))
    report = _read_json(report_path)
    checks: List[Dict[str, object]] = []

    required_top = {
        "version",
        "policy_id",
        "enabled_default",
        "require_report_when_enabled",
        "report_max_age_min",
        "baseline",
        "promotion_thresholds",
        "drift_limits",
        "retirement_criteria",
    }
    missing_top = sorted([k for k in required_top if k not in policy])
    checks.append(
        _check(
            "policy_shape",
            len(missing_top) == 0,
            "required policy keys present" if len(missing_top) == 0 else "policy missing required keys",
            {"missing_keys": missing_top},
        )
    )

    if not ml_enabled:
        checks.append(
            _check(
                "ml_disabled_safe_mode",
                True,
                "ML disabled; baseline-only execution mode accepted",
                {"ml_enabled": False},
            )
        )
    else:
        require_report = bool(policy.get("require_report_when_enabled", True))
        report_max_age_min = float(policy.get("report_max_age_min", 60.0))
        report_ts = str(report.get("ts_utc", "")).strip()
        report_age_min = _minutes_since(report_ts)
        report_ok = bool(report) and bool(report_ts) and report_age_min <= report_max_age_min
        checks.append(
            _check(
                "ml_report_fresh",
                (report_ok if require_report else True),
                "ML report is present and fresh" if report_ok else "ML report missing or stale",
                {
                    "require_report_when_enabled": require_report,
                    "report_path": str(report_path),
                    "report_ts_utc": report_ts,
                    "report_age_min": round(report_age_min, 3),
                    "report_max_age_min": report_max_age_min,
                },
            )
        )

        baseline = report.get("baseline", {}) if isinstance(report.get("baseline"), dict) else {}
        candidate = report.get("candidate", {}) if isinstance(report.get("candidate"), dict) else {}
        thresholds = (
            policy.get("promotion_thresholds", {}) if isinstance(policy.get("promotion_thresholds"), dict) else {}
        )
        min_sharpe_delta = float(thresholds.get("min_sharpe_delta", 0.0))
        min_pnl_bps_delta = float(thresholds.get("min_pnl_bps_delta", 0.0))
        sharpe_delta = float(candidate.get("sharpe", 0.0)) - float(baseline.get("sharpe", 0.0))
        pnl_bps_delta = float(candidate.get("pnl_bps", 0.0)) - float(baseline.get("pnl_bps", 0.0))
        checks.append(
            _check(
                "baseline_outperformance",
                sharpe_delta >= min_sharpe_delta and pnl_bps_delta >= min_pnl_bps_delta,
                "candidate outperforms baseline thresholds"
                if (sharpe_delta >= min_sharpe_delta and pnl_bps_delta >= min_pnl_bps_delta)
                else "candidate fails baseline outperformance thresholds",
                {
                    "sharpe_delta": round(sharpe_delta, 6),
                    "pnl_bps_delta": round(pnl_bps_delta, 6),
                    "min_sharpe_delta": min_sharpe_delta,
                    "min_pnl_bps_delta": min_pnl_bps_delta,
                },
            )
        )

        drift_limits = policy.get("drift_limits", {}) if isinstance(policy.get("drift_limits"), dict) else {}
        drift = report.get("drift", {}) if isinstance(report.get("drift"), dict) else {}
        max_feature_psi = float(drift_limits.get("max_feature_psi", 0.2))
        max_confidence_drop = float(drift_limits.get("max_confidence_drop", 0.15))
        feature_psi = float(drift.get("feature_psi", 0.0))
        confidence_drop = float(drift.get("confidence_drop", 0.0))
        checks.append(
            _check(
                "drift_limits",
                feature_psi <= max_feature_psi and confidence_drop <= max_confidence_drop,
                "drift metrics within limits"
                if (feature_psi <= max_feature_psi and confidence_drop <= max_confidence_drop)
                else "drift metrics exceed limits",
                {
                    "feature_psi": feature_psi,
                    "max_feature_psi": max_feature_psi,
                    "confidence_drop": confidence_drop,
                    "max_confidence_drop": max_confidence_drop,
                },
            )
        )

        retirement_cfg = (
            policy.get("retirement_criteria", {}) if isinstance(policy.get("retirement_criteria"), dict) else {}
        )
        retirement = report.get("retirement", {}) if isinstance(report.get("retirement"), dict) else {}
        max_underperf_days = int(retirement_cfg.get("max_consecutive_underperformance_days", 5))
        max_incidents_7d = int(retirement_cfg.get("max_critical_incidents_7d", 1))
        underperf_days = int(retirement.get("consecutive_underperformance_days", 0))
        incidents_7d = int(retirement.get("critical_incidents_7d", 0))
        checks.append(
            _check(
                "retirement_thresholds",
                underperf_days <= max_underperf_days and incidents_7d <= max_incidents_7d,
                "retirement thresholds not breached"
                if (underperf_days <= max_underperf_days and incidents_7d <= max_incidents_7d)
                else "retirement thresholds breached",
                {
                    "consecutive_underperformance_days": underperf_days,
                    "max_consecutive_underperformance_days": max_underperf_days,
                    "critical_incidents_7d": incidents_7d,
                    "max_critical_incidents_7d": max_incidents_7d,
                    "fail_action": str(retirement_cfg.get("fail_action", "disable_ml")),
                },
            )
        )

    status = "pass" if all(bool(c.get("pass", False)) for c in checks) else "fail"
    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "ml_enabled": ml_enabled,
        "policy_path": str(policy_path),
        "report_path": str(report_path),
        "checks": checks,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_root / f"ml_governance_check_{stamp}.json"
    _write(out, payload)
    _write(out_root / "ml_governance_latest.json", payload)
    print(f"[ml-governance] status={status}")
    print(f"[ml-governance] evidence={out}")
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
