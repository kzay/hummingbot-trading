from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_incident_note(incidents_path: Path, message: str) -> None:
    incidents_path.parent.mkdir(parents=True, exist_ok=True)
    if not incidents_path.exists():
        incidents_path.write_text("# Incident Playbook\n\n", encoding="utf-8")
    with incidents_path.open("a", encoding="utf-8") as f:
        f.write(f"- {_utc_now()} - {message}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run strict promotion cycle with parity refresh.")
    parser.add_argument("--max-report-age-min", type=int, default=20, help="Max freshness window in minutes.")
    parser.add_argument(
        "--append-incident-on-fail",
        action="store_true",
        help="Append a short incident note to docs/ops/incidents.md when strict gate fails.",
    )
    args = parser.parse_args()

    root = Path("/workspace/hbot") if Path("/.dockerenv").exists() else Path(__file__).resolve().parents[2]
    cmd = [
        sys.executable,
        str(root / "scripts" / "release" / "run_promotion_gates.py"),
        "--ci",
        "--require-day2-go",
        "--refresh-parity-once",
        "--max-report-age-min",
        str(args.max_report_age_min),
    ]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, check=False)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")

    reports = root / "reports" / "promotion_gates"
    latest_path = reports / "latest.json"
    latest = {}
    if latest_path.exists():
        try:
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
        except Exception:
            latest = {}

    cycle_summary = {
        "ts_utc": _utc_now(),
        "strict_gate_rc": int(proc.returncode),
        "strict_gate_status": latest.get("status", "UNKNOWN"),
        "critical_failures": latest.get("critical_failures", []),
        "gate_latest_path": str(latest_path),
        "stdout": out[:4000],
    }
    cycle_path = reports / "strict_cycle_latest.json"
    cycle_path.write_text(json.dumps(cycle_summary, indent=2), encoding="utf-8")

    if proc.returncode != 0 and args.append_incident_on_fail:
        failures = latest.get("critical_failures", [])
        msg = f"strict promotion cycle failed; critical_failures={failures}; evidence={latest_path}"
        _append_incident_note(root / "docs" / "ops" / "incidents.md", msg)

    print(f"[strict-cycle] rc={proc.returncode}")
    print(f"[strict-cycle] status={cycle_summary['strict_gate_status']}")
    print(f"[strict-cycle] evidence={cycle_path}")
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
