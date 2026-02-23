from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


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


def _fmt_list(items: List[str]) -> str:
    if not items:
        return "- (none)"
    return "\n".join(f"- {x}" for x in items)


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize readiness decision from latest strict/soak/day2 evidence.")
    parser.add_argument(
        "--apply-to-primary",
        action="store_true",
        help="Also overwrite docs/ops/option4_readiness_decision.md with latest generated decision.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    reports = root / "reports"
    docs_ops = root / "docs" / "ops"
    docs_ops.mkdir(parents=True, exist_ok=True)

    strict_path = reports / "promotion_gates" / "strict_cycle_latest.json"
    soak_path = reports / "soak" / "latest.json"
    day2_path = reports / "event_store" / "day2_gate_eval_latest.json"
    recon_path = reports / "reconciliation" / "latest.json"
    parity_path = reports / "parity" / "latest.json"
    risk_path = reports / "portfolio_risk" / "latest.json"

    strict = _read_json(strict_path, {})
    soak = _read_json(soak_path, {})
    day2 = _read_json(day2_path, {})
    recon = _read_json(recon_path, {})
    parity = _read_json(parity_path, {})
    risk = _read_json(risk_path, {})

    strict_pass = str(strict.get("strict_gate_status", "FAIL")).upper() == "PASS"
    day2_go = bool(day2.get("go", False))
    soak_ready = str(soak.get("status", "hold")).lower() == "ready"

    blockers: List[str] = []
    if not day2_go:
        blockers.append("day2_event_store_gate")
    if not strict_pass:
        blockers.append("strict_cycle_not_pass")
    if not soak_ready:
        blockers.append("soak_not_ready")

    status = "GO" if not blockers else "HOLD"

    payload = {
        "ts_utc": _utc_now(),
        "status": status,
        "blockers": blockers,
        "evidence": {
            "strict_cycle": str(strict_path),
            "soak_latest": str(soak_path),
            "day2_gate": str(day2_path),
            "reconciliation": str(recon_path),
            "parity": str(parity_path),
            "portfolio_risk": str(risk_path),
        },
        "summary": {
            "strict_gate_status": strict.get("strict_gate_status", "UNKNOWN"),
            "strict_critical_failures": strict.get("critical_failures", []),
            "day2_go": day2_go,
            "soak_status": soak.get("status", "unknown"),
            "reconciliation_status": recon.get("status", "unknown"),
            "parity_status": parity.get("status", "unknown"),
            "portfolio_risk_status": risk.get("status", "unknown"),
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
- Day2 gate GO: `{payload["summary"]["day2_go"]}`
- Soak aggregate status: `{payload["summary"]["soak_status"]}`
- Reconciliation status: `{payload["summary"]["reconciliation_status"]}`
- Parity status: `{payload["summary"]["parity_status"]}`
- Portfolio risk status: `{payload["summary"]["portfolio_risk_status"]}`

## Blockers
{_fmt_list(blockers)}

## Evidence
- Strict cycle: `{strict_path}`
- Soak latest: `{soak_path}`
- Day2 gate: `{day2_path}`
- Reconciliation: `{recon_path}`
- Parity: `{parity_path}`
- Portfolio risk: `{risk_path}`
"""

    latest_doc = docs_ops / "option4_readiness_decision_latest.md"
    latest_doc.write_text(md, encoding="utf-8")

    if args.apply_to_primary:
        (docs_ops / "option4_readiness_decision.md").write_text(md, encoding="utf-8")

    print(str(latest_doc))
    print(str(out_reports / "final_decision_latest.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
