from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


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


def _minutes_since(ts: str) -> float:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


def _minutes_since_file_mtime(path: Path) -> float:
    try:
        dt = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    except Exception:
        return 1e9


def _report_age_min(path: Path, payload: Dict[str, object]) -> float:
    ts = str(payload.get("ts_utc") or payload.get("last_update_utc") or "").strip()
    if ts:
        return _minutes_since(ts)
    return _minutes_since_file_mtime(path)


def _report_timestamp(path: Path, payload: Dict[str, object]) -> Optional[datetime]:
    ts = str(payload.get("ts_utc") or payload.get("last_update_utc") or "").strip()
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except Exception:
        return None


def _fmt_list(items: List[str]) -> str:
    if not items:
        return "- (none)"
    return "\n".join(f"- {x}" for x in items)


def run(root: Path, *, max_artifact_age_min: float = 20.0) -> Tuple[Dict[str, object], str]:
    reports = root / "reports"
    docs_ops = root / "docs" / "ops"
    docs_ops.mkdir(parents=True, exist_ok=True)

    evidence_specs = {
        "strict_cycle": reports / "promotion_gates" / "strict_cycle_latest.json",
        "promotion_gates_latest": reports / "promotion_gates" / "latest.json",
        "soak_latest": reports / "soak" / "latest.json",
        "day2_gate": reports / "event_store" / "day2_gate_eval_latest.json",
        "reconciliation": reports / "reconciliation" / "latest.json",
        "parity": reports / "parity" / "latest.json",
        "portfolio_risk": reports / "portfolio_risk" / "latest.json",
        "runtime_performance_budgets": reports / "verification" / "runtime_performance_budgets_latest.json",
    }
    evidence_payloads = {name: _read_json(path, {}) for name, path in evidence_specs.items()}
    freshness: Dict[str, Dict[str, object]] = {}
    missing_evidence: List[str] = []
    stale_evidence: List[str] = []
    for name, path in evidence_specs.items():
        exists = path.exists()
        payload = evidence_payloads[name]
        age_min = _report_age_min(path, payload) if exists else 1e9
        is_fresh = exists and age_min <= float(max_artifact_age_min)
        freshness[name] = {
            "path": str(path),
            "exists": exists,
            "age_min": round(age_min, 3),
            "max_age_min": float(max_artifact_age_min),
            "fresh": is_fresh,
        }
        if not exists:
            missing_evidence.append(name)
        elif not is_fresh:
            stale_evidence.append(name)

    strict = evidence_payloads["strict_cycle"]
    promotion_latest = evidence_payloads["promotion_gates_latest"]
    soak = evidence_payloads["soak_latest"]
    day2 = evidence_payloads["day2_gate"]
    recon = evidence_payloads["reconciliation"]
    parity = evidence_payloads["parity"]
    risk = evidence_payloads["portfolio_risk"]
    runtime_perf = evidence_payloads["runtime_performance_budgets"]

    strict_pass = str(strict.get("strict_gate_status", "FAIL")).upper() == "PASS"
    promotion_latest_status = str(promotion_latest.get("status", "FAIL")).upper()
    promotion_latest_pass = promotion_latest_status == "PASS"
    day2_go = bool(day2.get("go", False))
    soak_ready = str(soak.get("status", "hold")).lower() == "ready"
    recon_pass = str(recon.get("status", "fail")).strip().lower() in {"pass", "ok"}
    parity_pass = str(parity.get("status", "fail")).strip().lower() in {"pass", "ok"}
    risk_pass = str(risk.get("status", "fail")).strip().lower() in {"pass", "ok"}
    runtime_perf_pass = str(runtime_perf.get("status", "fail")).strip().lower() == "pass"

    strict_ts = _report_timestamp(evidence_specs["strict_cycle"], strict)
    promotion_latest_ts = _report_timestamp(evidence_specs["promotion_gates_latest"], promotion_latest)
    promotion_newer_than_strict = bool(
        strict_ts is not None and promotion_latest_ts is not None and promotion_latest_ts > strict_ts
    )

    blockers: List[str] = []
    blockers.extend(f"missing_evidence:{name}" for name in missing_evidence)
    blockers.extend(f"stale_evidence:{name}" for name in stale_evidence)
    if not day2_go:
        blockers.append("day2_event_store_gate")
    if not strict_pass:
        blockers.append("strict_cycle_not_pass")
    if not promotion_latest_pass:
        blockers.append("promotion_gates_latest_not_pass")
    if promotion_latest_pass != strict_pass:
        blockers.append("promotion_gate_status_mismatch")
    if promotion_newer_than_strict and promotion_latest_status != str(strict.get("strict_gate_status", "UNKNOWN")).upper():
        blockers.append("promotion_gates_latest_newer_than_strict_cycle")
    if not soak_ready:
        blockers.append("soak_not_ready")
    if not recon_pass:
        blockers.append("reconciliation_not_pass")
    if not parity_pass:
        blockers.append("parity_not_pass")
    if not risk_pass:
        blockers.append("portfolio_risk_not_pass")
    if not runtime_perf_pass:
        blockers.append("runtime_performance_not_pass")

    status = "GO" if not blockers else "HOLD"

    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "blockers": blockers,
        "evidence": {name: str(path) for name, path in evidence_specs.items()},
        "summary": {
            "strict_gate_status": strict.get("strict_gate_status", "UNKNOWN"),
            "strict_critical_failures": strict.get("critical_failures", []),
            "promotion_gates_latest_status": promotion_latest.get("status", "UNKNOWN"),
            "promotion_gates_latest_critical_failures": promotion_latest.get("critical_failures", []),
            "day2_go": day2_go,
            "soak_status": soak.get("status", "unknown"),
            "reconciliation_status": recon.get("status", "unknown"),
            "parity_status": parity.get("status", "unknown"),
            "portfolio_risk_status": risk.get("status", "unknown"),
            "runtime_performance_status": runtime_perf.get("status", "unknown"),
        },
        "diagnostics": {
            "max_artifact_age_min": float(max_artifact_age_min),
            "missing_evidence": missing_evidence,
            "stale_evidence": stale_evidence,
            "artifact_freshness": freshness,
            "strict_cycle_ts_utc": strict_ts.isoformat() if strict_ts is not None else "",
            "promotion_gates_latest_ts_utc": promotion_latest_ts.isoformat() if promotion_latest_ts is not None else "",
            "promotion_gates_latest_newer_than_strict_cycle": promotion_newer_than_strict,
        },
    }

    out_reports = reports / "readiness"
    out_reports.mkdir(parents=True, exist_ok=True)
    (out_reports / "final_decision_latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md = f"""# Option 4 Readiness Decision (Latest)

## Decision Timestamp
- {payload["ts_utc"]}

## Decision
- **Status: {status}**

## Decision Inputs
- Strict gate status: `{payload["summary"]["strict_gate_status"]}`
- Promotion gates latest status: `{payload["summary"]["promotion_gates_latest_status"]}`
- Day2 gate GO: `{payload["summary"]["day2_go"]}`
- Soak aggregate status: `{payload["summary"]["soak_status"]}`
- Reconciliation status: `{payload["summary"]["reconciliation_status"]}`
- Parity status: `{payload["summary"]["parity_status"]}`
- Portfolio risk status: `{payload["summary"]["portfolio_risk_status"]}`
- Runtime performance status: `{payload["summary"]["runtime_performance_status"]}`

## Blockers
{_fmt_list(blockers)}

## Stale Evidence
{_fmt_list(stale_evidence)}

## Missing Evidence
{_fmt_list(missing_evidence)}

## Evidence
- Strict cycle: `{evidence_specs["strict_cycle"]}`
- Promotion gates latest: `{evidence_specs["promotion_gates_latest"]}`
- Soak latest: `{evidence_specs["soak_latest"]}`
- Day2 gate: `{evidence_specs["day2_gate"]}`
- Reconciliation: `{evidence_specs["reconciliation"]}`
- Parity: `{evidence_specs["parity"]}`
- Portfolio risk: `{evidence_specs["portfolio_risk"]}`
- Runtime performance budgets: `{evidence_specs["runtime_performance_budgets"]}`
"""

    latest_doc = docs_ops / "option4_readiness_decision_latest.md"
    latest_doc.write_text(md, encoding="utf-8")
    return payload, md


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize readiness decision from latest strict/soak/day2 evidence.")
    parser.add_argument(
        "--apply-to-primary",
        action="store_true",
        help="Also overwrite docs/ops/option4_readiness_decision.md with latest generated decision.",
    )
    parser.add_argument(
        "--max-artifact-age-min",
        type=float,
        default=20.0,
        help="Maximum allowed age for readiness/performance evidence before GO is blocked.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    payload, md = run(root, max_artifact_age_min=float(args.max_artifact_age_min))
    docs_ops = root / "docs" / "ops"
    latest_doc = docs_ops / "option4_readiness_decision_latest.md"

    if args.apply_to_primary:
        (docs_ops / "option4_readiness_decision.md").write_text(md, encoding="utf-8")

    print(str(latest_doc))
    print(str(root / "reports" / "readiness" / "final_decision_latest.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
